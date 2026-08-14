from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx

from transcript_cleanup_bench import runner


class Generation:
    id = "observation-id"
    trace_id = "trace-id"

    def __init__(self):
        self.updated = None
        self.ended = False

    def update(self, **values):
        self.updated = values

    def end(self):
        self.ended = True


class RunItems:
    def __init__(self):
        self.calls = []

    def create(self, **values):
        self.calls.append(values)
        return SimpleNamespace(dataset_run_id="experiment-id")


class Langfuse:
    def __init__(self):
        self.generation = Generation()
        self.run_items = RunItems()
        self.api = SimpleNamespace(dataset_run_items=self.run_items)

    def start_observation(self, **_values):
        return self.generation


def test_run_pair_links_generation_to_pinned_dataset_version(monkeypatch) -> None:
    requests = []

    class Client:
        def __init__(self, **_values):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_values):
            pass

        async def post(self, url, headers, json):
            requests.append((url, headers, json))
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "choices": [{"message": {"content": "clean"}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 3},
                },
            )

    monkeypatch.setattr(runner.httpx, "AsyncClient", Client)
    monkeypatch.setenv("OMLX_API_KEY", "secret")
    item = SimpleNamespace(
        id="item-id",
        input={"transcript": "dirty"},
        expected_output={
            "assertions": [
                {"type": "equals", "metric": "exact", "value": "clean"},
                {"type": "equals", "metric": "preservation", "value": "clean"},
            ]
        },
        metadata={"legacy_identifier": "case-1"},
    )
    dataset = SimpleNamespace(items=[item])
    langfuse = Langfuse()
    config = runner.load_config()
    version = datetime(2026, 8, 14, tzinfo=UTC)
    executions = runner.run_pair(
        langfuse,
        dataset,
        config,
        config["models"][0],
        config["prompts"][0],
        1,
        version,
        "sha",
        "bench-id",
    )
    assert len(executions) == 1
    assert executions[0].experiment_id == "experiment-id"
    assert executions[0].expected_score_names == ("exact", "pass", "preservation")
    assert langfuse.run_items.calls[0]["observation_id"] == "observation-id"
    assert langfuse.run_items.calls[0]["dataset_version"] == version
    assert requests[0][0] == "http://localhost:8000/v1/chat/completions"
    assert requests[0][2]["top_k"] == 0
    assert langfuse.generation.ended is True


def test_selected_accepts_ids_and_labels() -> None:
    values = [{"id": "one", "label": "One"}, {"id": "two", "label": "Two"}]
    assert runner.selected(values, ["one", "Two"]) == values
