from __future__ import annotations

import hashlib
from pathlib import Path

from langfuse.api.unstable.commons.types import (
    CodeEvaluatorSourceCodeLanguage,
    EvaluationRuleFilter_StringOptions,
    EvaluationRuleOptionsFilterOperator,
    EvaluationRuleTarget,
    EvaluatorScope,
)
from langfuse.api.unstable.evaluation_rules.types import (
    CodeEvaluationRuleEvaluatorReference,
    CreateCodeEvaluationRuleRequest,
)
from langfuse.api.unstable.evaluators.types import CreateEvaluatorRequest_Code

from . import DATASET_NAME
from .dataset import bootstrap, client

REPO = Path(__file__).resolve().parents[2]
EVALUATOR = REPO / "evaluators" / "transcript_cleanup.js"
EVALUATOR_NAME = "transcript-cleanup-assertions"
RULE_NAME = "transcript-cleanup-offline-experiments"


def source_hash(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def sync_evaluator(langfuse):
    source = EVALUATOR.read_text()
    evaluators = langfuse.api.unstable.evaluators.list(limit=100).data
    versions = [
        evaluator
        for evaluator in evaluators
        if evaluator.name == EVALUATOR_NAME and evaluator.scope == EvaluatorScope.PROJECT
    ]
    latest = max(versions, key=lambda evaluator: evaluator.version) if versions else None
    if latest is not None and source_hash(latest.source_code) == source_hash(source):
        print(f"evaluator unchanged at version {latest.version}")
        return latest

    created = langfuse.api.unstable.evaluators.create(
        request=CreateEvaluatorRequest_Code(
            name=EVALUATOR_NAME,
            source_code=source,
            source_code_language=CodeEvaluatorSourceCodeLanguage.TYPESCRIPT,
        )
    )
    print(f"created evaluator version {created.version}")
    return created


def desired_filter(dataset_id: str):
    return [
        EvaluationRuleFilter_StringOptions(
            column="datasetId",
            operator=EvaluationRuleOptionsFilterOperator.ANY_OF,
            value=[dataset_id],
        )
    ]


def sync_rule(langfuse) -> None:
    dataset = langfuse.get_dataset(DATASET_NAME, fetch_items_page_size=1)
    reference = CodeEvaluationRuleEvaluatorReference(
        name=EVALUATOR_NAME,
        scope=EvaluatorScope.PROJECT,
    )
    filters = desired_filter(dataset.id)
    rules = langfuse.api.unstable.evaluation_rules.list(limit=100).data
    matching = [rule for rule in rules if rule.name == RULE_NAME]
    if not matching:
        langfuse.api.unstable.evaluation_rules.create(
            request=CreateCodeEvaluationRuleRequest(
                name=RULE_NAME,
                evaluator=reference,
                target=EvaluationRuleTarget.EXPERIMENT,
                enabled=True,
                sampling=1.0,
                filter=filters,
            )
        )
        print("created offline experiment rule")
        return

    keep, *duplicates = matching
    for duplicate in duplicates:
        langfuse.api.unstable.evaluation_rules.delete(duplicate.id)
    expected_filter = [entry.model_dump(mode="json") for entry in filters]
    actual_filter = [entry.model_dump(mode="json") for entry in keep.filter]
    if (
        keep.evaluator.name == EVALUATOR_NAME
        and keep.target == EvaluationRuleTarget.EXPERIMENT
        and keep.enabled
        and keep.sampling == 1.0
        and actual_filter == expected_filter
    ):
        print("offline experiment rule unchanged")
        return
    langfuse.api.unstable.evaluation_rules.update(
        keep.id,
        evaluator=reference,
        target=EvaluationRuleTarget.EXPERIMENT,
        enabled=True,
        sampling=1.0,
        filter=filters,
    )
    print("updated offline experiment rule")


def main() -> None:
    langfuse = client()
    try:
        bootstrap(langfuse)
        sync_evaluator(langfuse)
        sync_rule(langfuse)
    finally:
        langfuse.shutdown()


if __name__ == "__main__":
    main()
