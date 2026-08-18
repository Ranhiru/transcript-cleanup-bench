from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from transcript_cleanup_bench.experiment import (
    assertion_evaluator,
    facet_pass_rates,
    leaderboard,
)


def scores(output: str, assertions: list[dict]):
    return assertion_evaluator(output=output, expected_output={"assertions": assertions})


def by_name(output: str, assertions: list[dict]) -> dict:
    return {item.name: item.value for item in scores(output, assertions)}


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

    assert [item.name for item in evaluations] == ["pass", "assertion_rate"]
    assert evaluations[0].value is True
    assert evaluations[1].value == 1.0


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


def test_assertion_rate_is_the_fraction_that_passed_and_is_always_defined() -> None:
    assert by_name(
        "Yes",
        [
            {"type": "contains", "value": "Yes", "metric": "content"},
            {"type": "contains", "value": "No", "metric": "content"},
            {"type": "equals", "value": "Yes", "metric": "exact"},
            {"type": "equals", "value": "No", "metric": "exact"},
        ],
    ) == {"pass": False, "assertion_rate": 0.5}

    # A single metric must not change the score names emitted.
    assert by_name("Yes", [{"type": "contains", "value": "Yes", "metric": "only"}]) == {
        "pass": True,
        "assertion_rate": 1.0,
    }


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


class Result:
    """Stands in for a Langfuse ExperimentItemResult."""

    def __init__(self, metadata: dict, outcome: bool) -> None:
        self.item = SimpleNamespace(metadata=metadata)
        self.evaluations = [
            SimpleNamespace(name="pass", value=outcome),
            SimpleNamespace(name="assertion_rate", value=1.0 if outcome else 0.0),
        ]


def test_run_evaluator_reports_a_denominator_per_facet() -> None:
    rates = facet_pass_rates(
        item_results=[
            Result({"category": "spelling"}, True),
            Result({"category": "spelling"}, False),
            Result({"category": "long-form", "negative_control": True}, True),
        ]
    )
    values = {item.name: item.value for item in rates}

    assert values["pass_rate"] == 2 / 3
    assert values["pass_rate:spelling"] == 0.5
    assert values["pass_rate:long-form"] == 1.0
    # The control split partitions every item, so the two halves cover the run.
    assert values["pass_rate:negative-control"] == 1.0
    assert values["pass_rate:positive-case"] == 0.5
    comments = {item.name: item.comment for item in rates}
    assert comments["pass_rate:spelling"] == "1 of 2 items passed"
    assert all(item.data_type == "NUMERIC" for item in rates)


def test_run_evaluator_skips_items_whose_task_produced_no_pass_score() -> None:
    broken = SimpleNamespace(item=SimpleNamespace(metadata={"category": "spelling"}),
                             evaluations=[])
    rates = facet_pass_rates(item_results=[Result({"category": "spelling"}, True), broken])

    assert {item.name: item.value for item in rates}["pass_rate"] == 1.0
    assert [item.metadata["items"] for item in rates if item.name == "pass_rate"] == [1]


def run_result(pass_rate: float, assertion_rate: float, **facets) -> SimpleNamespace:
    return SimpleNamespace(
        run_evaluations=[SimpleNamespace(name="pass_rate", value=pass_rate)]
        + [SimpleNamespace(name=f"pass_rate:{k}", value=v) for k, v in facets.items()],
        item_results=[
            SimpleNamespace(evaluations=[SimpleNamespace(name="assertion_rate", value=assertion_rate)])
        ],
    )


def test_leaderboard_breaks_a_pass_rate_tie_on_assertion_rate() -> None:
    rows = [
        ({"label": "Weaker"}, run_result(0.956, 0.956, spelling=1.0)),
        ({"label": "Stronger"}, run_result(0.956, 0.990, spelling=1.0)),
        ({"label": "Lowest"}, run_result(0.822, 0.999, spelling=1.0)),
    ]
    table = leaderboard(rows)
    header = next(line for line in table.splitlines() if line.startswith("measure"))

    # Columns are models, ordered best first; the tie is broken by assertion rate.
    assert header.split() == ["measure", "Stronger", "Weaker", "Lowest"]
    rates = next(line for line in table.splitlines() if line.startswith("pass_rate"))
    assert rates.split()[1:] == ["0.956", "0.956", "0.822"]


def test_leaderboard_marks_a_facet_a_run_never_reported() -> None:
    rows = [
        ({"label": "Has"}, run_result(1.0, 1.0, spelling=1.0, **{"long-form": 0.5})),
        ({"label": "Lacks"}, run_result(0.9, 1.0, spelling=1.0)),
    ]
    long_form = next(
        line for line in leaderboard(rows).splitlines() if line.startswith("long-form")
    )
    assert long_form.split()[1:] == ["0.500", "-"]
