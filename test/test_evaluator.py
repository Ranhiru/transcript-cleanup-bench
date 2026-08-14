from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = Path("evaluators/transcript_cleanup.js").read_text()


def run_evaluator(output: str, assertions: list[dict]) -> list[dict]:
    if shutil.which("node") is None:
        pytest.skip("Node is required to exercise the JavaScript evaluator")
    ctx = {"observation": {"output": output}, "experiment": {"itemExpectedOutput": {"assertions": assertions}}}
    program = f"{SOURCE}\nconsole.log(JSON.stringify(evaluate({json.dumps(ctx)}).scores));"
    result = subprocess.run(["node", "-e", program], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_all_assertion_types_and_named_metrics() -> None:
    assertions = [
        {"type": "equals", "value": "Café\nDone", "metric": "exact"},
        {"type": "contains", "value": "fé\nD", "metric": "shape"},
        {"type": "regex", "value": "^Café\\nDone$", "metric": "shape"},
        {"type": "not-regex", "value": "^Done", "metric": "negative"},
        {"type": "not-icontains", "value": "MISSING", "metric": "negative"},
        {"type": "not-icontains-any", "value": ["missing", "absent"], "metric": "negative"},
    ]
    scores = run_evaluator("  Café\nDone  ", assertions)
    assert scores[0]["name"] == "pass" and scores[0]["value"] is True
    assert {score["name"]: score["value"] for score in scores[1:]} == {
        "exact": 1,
        "shape": 1,
        "negative": 1,
    }


def test_failures_include_details_and_metric_fraction() -> None:
    assertions = [
        {"type": "contains", "value": "Yes", "metric": "content"},
        {"type": "contains", "value": "No", "metric": "content"},
        {"type": "not-icontains", "value": "STRASSE", "metric": "unicode"},
    ]
    scores = run_evaluator("Yes Straße", assertions)
    assert scores[0]["value"] is False
    assert scores[0]["metadata"]["failedAssertions"][0]["value"] == "No"
    assert {score["name"]: score["value"] for score in scores[1:]}["content"] == 0.5


def test_regex_has_no_implicit_multiline_or_case_flags() -> None:
    scores = run_evaluator(
        "first\nSECOND",
        [
            {"type": "not-regex", "value": "^SECOND$", "metric": "anchored"},
            {"type": "not-regex", "value": "second", "metric": "case"},
        ],
    )
    assert scores[0]["value"] is True


def test_invalid_regex_raises() -> None:
    if shutil.which("node") is None:
        pytest.skip("Node is required to exercise the JavaScript evaluator")
    with pytest.raises(subprocess.CalledProcessError):
        run_evaluator("x", [{"type": "regex", "value": "[", "metric": "invalid"}])
