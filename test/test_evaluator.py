from __future__ import annotations

import re

import pytest

from transcript_cleanup_bench.experiment import assertion_evaluator


def scores(output: str, assertions: list[dict]):
    return assertion_evaluator(output=output, expected_output={"assertions": assertions})


def passed(output: str, assertion: dict) -> bool:
    """Whether one assertion held, read off the boolean `pass` evaluation."""
    return scores(output, [{"metric": "only", **assertion}])[0].value


def test_every_assertion_type_holds_on_matching_output() -> None:
    evaluations = scores(
        "  Café\nDone  ",
        [
            {"type": "equals", "value": "Café\nDone", "metric": "exact"},
            {"type": "contains", "value": "fé\nD", "metric": "shape"},
            {"type": "regex", "value": "^Café\\nDone$", "metric": "shape"},
            {"type": "not-regex", "value": "^Done", "metric": "negative"},
            {"type": "not-icontains", "value": "MISSING", "metric": "negative"},
            {"type": "not-icontains-any", "value": ["missing", "absent"], "metric": "negative"},
        ],
    )

    assert evaluations[0].name == "pass"
    assert evaluations[0].value is True
    assert {item.name: item.value for item in evaluations[1:]} == {
        "exact": 1,
        "shape": 1,
        "negative": 1,
    }


def test_surrounding_whitespace_is_stripped_before_comparison() -> None:
    assert passed("  Done  ", {"type": "equals", "value": "Done"})
    assert not passed("Done", {"type": "equals", "value": "  Done  "})


def test_negated_contains_assertions_fold_case() -> None:
    # Folded, each phrase is present, so the negated assertion must fail.
    assert not passed(
        "Here is the cleaned text",
        {"type": "not-icontains", "value": "HERE IS THE CLEANED"},
    )
    assert not passed(
        "I HOPE THIS HELPS",
        {"type": "not-icontains-any", "value": ["i hope this helps", "let me know"]},
    )


def test_regex_applies_no_implicit_multiline_or_ignorecase_flags() -> None:
    assert passed("first\nSECOND", {"type": "not-regex", "value": "^SECOND$"})
    assert passed("first\nSECOND", {"type": "not-regex", "value": "second"})
    assert passed("first\nSECOND", {"type": "regex", "value": "SECOND"})


def test_metric_score_is_the_pass_fraction_within_that_metric() -> None:
    evaluations = scores(
        "Yes",
        [
            {"type": "contains", "value": "Yes", "metric": "content"},
            {"type": "contains", "value": "No", "metric": "content"},
            {"type": "equals", "value": "Yes", "metric": "exact"},
        ],
    )

    assert evaluations[0].value is False
    assert {item.name: item.value for item in evaluations[1:]} == {"content": 0.5, "exact": 1}


def test_failed_assertions_are_reported_with_their_position() -> None:
    evaluations = scores(
        "Yes",
        [
            {"type": "contains", "value": "Yes", "metric": "content"},
            {"type": "contains", "value": "No", "metric": "content"},
        ],
    )

    failed = evaluations[0].metadata["failedAssertions"]
    assert [(item["index"], item["value"]) for item in failed] == [(1, "No")]
    assert evaluations[0].comment == "1 of 2 assertions passed"


def test_unsupported_assertion_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported assertion type: almost-equals"):
        passed("x", {"type": "almost-equals", "value": "x"})


def test_invalid_regex_is_not_swallowed() -> None:
    with pytest.raises(re.error):
        passed("x", {"type": "regex", "value": "["})
