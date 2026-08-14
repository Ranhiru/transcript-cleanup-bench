from __future__ import annotations

import asyncio
from types import SimpleNamespace

from transcript_cleanup_bench import experiment


class FakeModel:
    instances = []

    def __init__(self, **options):
        self.options = options
        self.calls = []
        self.instances.append(self)

    async def ainvoke(self, messages, config):
        self.calls.append((messages, config))
        return SimpleNamespace(content="clean")


class FakeDataset:
    def __init__(self):
        self.call = None

    def run_experiment(self, **values):
        self.call = values
        return "result"


def test_run_pair_passes_task_evaluator_metadata_and_concurrency(monkeypatch) -> None:
    FakeModel.instances.clear()
    monkeypatch.setattr(experiment, "ChatOpenAI", FakeModel)
    monkeypatch.setattr(experiment, "CallbackHandler", lambda: "callback")
    monkeypatch.setenv("OMLX_API_KEY", "secret")
    dataset = FakeDataset()
    config = experiment.load_config()
    model = config["models"][-1]
    prompt = config["prompts"][0]

    result = experiment.run_pair(dataset, config, model, prompt, 3, "eval-id")

    assert result == "result"
    assert dataset.call["max_concurrency"] == 3
    assert dataset.call["evaluators"] == [experiment.assertion_evaluator]
    assert dataset.call["metadata"] == {
        "model": model["id"],
        "model_label": model["label"],
        "prompt": prompt["id"],
    }
    item = SimpleNamespace(input={"transcript": "dirty"})
    assert asyncio.run(dataset.call["task"](item=item)) == "clean"
    llm = FakeModel.instances[0]
    assert llm.options["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert llm.calls[0][1] == {"callbacks": ["callback"]}


def test_selected_accepts_ids_and_labels() -> None:
    values = [{"id": "one", "label": "One"}, {"id": "two", "label": "Two"}]
    assert experiment.selected(values, ["one", "Two"]) == values


def test_filter_cases_accepts_item_id_and_legacy_identifier() -> None:
    dataset = SimpleNamespace(
        items=[
            SimpleNamespace(id="one", metadata={"legacy_identifier": "case-1"}),
            SimpleNamespace(id="two", metadata={"legacy_identifier": "case-2"}),
        ]
    )
    assert [item.id for item in experiment.filter_cases(dataset, ["case-2"]).items] == ["two"]
