from __future__ import annotations

from types import SimpleNamespace

from langfuse.api.unstable.commons.types import EvaluatorScope

from transcript_cleanup_bench import sync


class Evaluators:
    def __init__(self, values):
        self.values = values
        self.created = []

    def list(self, limit):
        assert limit == 100
        return SimpleNamespace(data=self.values)

    def create(self, request):
        self.created.append(request)
        return SimpleNamespace(version=2, source_code=request.source_code)


def fake_langfuse(evaluators):
    return SimpleNamespace(api=SimpleNamespace(unstable=SimpleNamespace(evaluators=evaluators)))


def test_evaluator_sync_is_idempotent() -> None:
    source = sync.EVALUATOR.read_text()
    api = Evaluators(
        [SimpleNamespace(name=sync.EVALUATOR_NAME, scope=EvaluatorScope.PROJECT, version=3, source_code=source)]
    )
    result = sync.sync_evaluator(fake_langfuse(api))
    assert result.version == 3
    assert not api.created


def test_evaluator_sync_creates_new_source_version() -> None:
    api = Evaluators(
        [SimpleNamespace(name=sync.EVALUATOR_NAME, scope=EvaluatorScope.PROJECT, version=1, source_code="old")]
    )
    result = sync.sync_evaluator(fake_langfuse(api))
    assert result.version == 2
    assert api.created[0].type == "code"


def test_rule_filters_to_the_authoritative_dataset() -> None:
    filters = {entry.column: entry.value for entry in sync.desired_filter("dataset-id")}
    assert filters == {"datasetId": ["dataset-id"]}
