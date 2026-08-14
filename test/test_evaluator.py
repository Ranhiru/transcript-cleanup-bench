from __future__ import annotations

import pytest

from transcript_cleanup_bench.experiment import assertion_evaluator


def scores(output: str, assertions: list[dict]):
    return assertion_evaluator(output=output, expected_output={"assertions": assertions})


def test_all_assertion_types_named_metrics_and_whitespace_normalization() -> None:
    evaluations = scores(
        "  Café\nDone  ",
        [
            {"type": "equals", "value": "Café\nDone", "metric": "exact"},
            {"type": "contains", "value": "fé\nD", "metric": "shape"},
            {"type": "regex", "value": "^Café\\nDone$", "metric": "shape"},
            {"type": "not-regex", "value": "^Done", "metric": "negative"},
            {"type": "not-icontains", "value": "MISSING", "metric": "negative"},
            {
                "type": "not-icontains-any",
                "value": ["missing", "absent"],
                "metric": "negative",
            },
        ],
    )
    assert evaluations[0].name == "pass" and evaluations[0].value is True
    assert {evaluation.name: evaluation.value for evaluation in evaluations[1:]} == {
        "exact": 1,
        "shape": 1,
        "negative": 1,
    }


def test_failures_include_metadata_and_grouped_metric_fraction() -> None:
    evaluations = scores(
        "Yes Straße",
        [
            {"type": "contains", "value": "Yes", "metric": "content"},
            {"type": "contains", "value": "No", "metric": "content"},
            {"type": "not-icontains", "value": "STRASSE", "metric": "unicode"},
        ],
    )
    assert evaluations[0].value is False
    assert evaluations[0].metadata["failedAssertions"][0]["value"] == "No"
    metric_values = {evaluation.name: evaluation.value for evaluation in evaluations[1:]}
    assert metric_values["content"] == 0.5
    assert metric_values["unicode"] == 1


def test_regex_has_no_implicit_multiline_or_case_flags() -> None:
    evaluations = scores(
        "first\nSECOND",
        [
            {"type": "not-regex", "value": "^SECOND$", "metric": "anchored"},
            {"type": "not-regex", "value": "second", "metric": "case"},
        ],
    )
    assert evaluations[0].value is True


def test_invalid_regex_raises() -> None:
    with pytest.raises(Exception):
        scores("x", [{"type": "regex", "value": "[", "metric": "invalid"}])
