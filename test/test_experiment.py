from __future__ import annotations

import asyncio
from types import SimpleNamespace

from transcript_cleanup_bench import experiment


class FakeModel:
    instances = []

    def __init__(self, **options):
        self.options = options
        self.instances.append(self)


class FakeChain:
    def __init__(self, template, model):
        self.template = template
        self.model = model
        self.calls = []

    async def ainvoke(self, values, config):
        self.calls.append((values, config))
        return SimpleNamespace(content="clean")


class FakeTemplate:
    instances = []

    def __init__(self, messages):
        self.messages = messages
        self.metadata = None
        self.chain = None
        self.instances.append(self)

    @classmethod
    def from_messages(cls, messages):
        return cls(messages)

    def __or__(self, model):
        self.chain = FakeChain(self, model)
        return self.chain


class FakePrompt:
    def __init__(self, version, labels=None):
        self.name = "transcript-cleanup"
        self.version = version
        self.labels = labels or []

    def get_langchain_prompt(self):
        return [("system", "Clean it."), ("user", "{transcript}")]


class FakeDataset:
    def __init__(self):
        self.call = None

    def run_experiment(self, **values):
        self.call = values
        return "result"


def test_run_pair_uses_linked_chat_template_and_exact_prompt_metadata(monkeypatch) -> None:
    FakeModel.instances.clear()
    FakeTemplate.instances.clear()
    monkeypatch.setattr(experiment, "ChatOpenAI", FakeModel)
    monkeypatch.setattr(experiment, "ChatPromptTemplate", FakeTemplate)
    monkeypatch.setattr(experiment, "CallbackHandler", lambda: "callback")
    monkeypatch.setenv("OPENAI_API_HOST", "https://provider.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    dataset = FakeDataset()
    config = experiment.load_config()
    model = config["models"][-1]
    prompt = FakePrompt(12, ["production"])
    selection = experiment.PromptSelection(prompt, "production")

    result = experiment.run_pair(dataset, config, model, selection, 3, "eval-id")

    assert result == "result"
    assert dataset.call["max_concurrency"] == 3
    assert dataset.call["evaluators"] == [experiment.assertion_evaluator]
    assert dataset.call["metadata"] == {
        "model": model["id"],
        "model_label": model["label"],
        "prompt_name": "transcript-cleanup",
        "prompt_version": 12,
        "prompt_label": "production",
    }
    assert dataset.call["run_name"] == (
        "eval-id-Qwen3.6-35B-A3B-MLX-4bit-transcript-cleanup-v12-production"
    )
    item = SimpleNamespace(input={"transcript": "dirty"})
    assert asyncio.run(dataset.call["task"](item=item)) == "clean"
    llm = FakeModel.instances[0]
    assert llm.options["base_url"] == "https://provider.example/v1"
    assert llm.options["extra_body"]["chat_template_kwargs"] == {"enable_thinking": False}
    template = FakeTemplate.instances[0]
    assert template.metadata == {"langfuse_prompt": prompt}
    assert template.chain.calls == [
        ({"transcript": "dirty"}, {"callbacks": ["callback"]})
    ]


def test_resolve_prompt_selections_defaults_to_env_label(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")

    def resolve(langfuse, *, name, label=None, version=None):
        calls.append((name, label, version))
        return FakePrompt(8)

    monkeypatch.setattr(experiment, "resolve", resolve)

    selections = experiment.resolve_prompt_selections("client", "transcript-cleanup", None, None)

    assert [(selection.prompt.version, selection.requested_label) for selection in selections] == [
        (8, "production")
    ]
    assert calls == [("transcript-cleanup", "production", None)]


def test_resolve_prompt_selections_allows_both_selectors_and_deduplicates(monkeypatch) -> None:
    versions = {"production": 4, "candidate": 5}
    calls = []

    def resolve(langfuse, *, name, label=None, version=None):
        calls.append((label, version))
        return FakePrompt(versions[label] if label else version)

    monkeypatch.setattr(experiment, "resolve", resolve)

    selections = experiment.resolve_prompt_selections(
        "client",
        "transcript-cleanup",
        ["production", "candidate", "candidate"],
        [5, 6, 6],
    )

    assert [(selection.prompt.version, selection.requested_label) for selection in selections] == [
        (4, "production"),
        (5, "candidate"),
        (6, None),
    ]
    assert calls == [("production", None), ("candidate", None), (None, 5), (None, 6)]


def test_version_only_does_not_implicitly_add_default_label(monkeypatch) -> None:
    calls = []

    def resolve(langfuse, *, name, label=None, version=None):
        calls.append((label, version))
        return FakePrompt(version)

    monkeypatch.setattr(experiment, "resolve", resolve)

    selections = experiment.resolve_prompt_selections(
        "client", "transcript-cleanup", None, [1, 2]
    )

    assert [selection.prompt.version for selection in selections] == [1, 2]
    assert calls == [(None, 1), (None, 2)]


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
