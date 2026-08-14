from __future__ import annotations

from typing import Any

ASSERTION_TYPES = {
    "equals",
    "contains",
    "regex",
    "not-regex",
    "not-icontains",
    "not-icontains-any",
}

INPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["transcript"],
    "properties": {"transcript": {"type": "string"}},
}

ASSERTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", "metric", "value"],
    "properties": {
        "type": {"enum": sorted(ASSERTION_TYPES)},
        "metric": {"type": "string", "minLength": 1},
        "value": {},
    },
    "allOf": [
        {
            "if": {"properties": {"type": {"const": "not-icontains-any"}}},
            "then": {
                "properties": {
                    "value": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    }
                }
            },
            "else": {"properties": {"value": {"type": "string"}}},
        }
    ],
}

EXPECTED_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["assertions"],
    "properties": {
        "assertions": {"type": "array", "minItems": 1, "items": ASSERTION_SCHEMA}
    },
}


def validate_item(item: dict[str, Any]) -> None:
    transcript = item.get("input", {}).get("transcript")
    if not isinstance(transcript, str):
        raise ValueError("input.transcript must be a string")
    assertions = item.get("expectedOutput", {}).get("assertions")
    if not isinstance(assertions, list) or not assertions:
        raise ValueError("expectedOutput.assertions must be a non-empty array")
    for assertion in assertions:
        if not isinstance(assertion, dict) or assertion.get("type") not in ASSERTION_TYPES:
            raise ValueError(f"invalid assertion: {assertion!r}")
        if not isinstance(assertion.get("metric"), str) or not assertion["metric"]:
            raise ValueError(f"invalid metric: {assertion!r}")
        value = assertion.get("value")
        if assertion["type"] == "not-icontains-any":
            if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
                raise ValueError(f"invalid assertion value: {assertion!r}")
        elif not isinstance(value, str):
            raise ValueError(f"invalid assertion value: {assertion!r}")

