from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from transcript_cleanup_bench import dataset
from transcript_cleanup_bench.schemas import EXPECTED_OUTPUT_SCHEMA, INPUT_SCHEMA, validate_item


def test_snapshot_is_normalized_and_complete() -> None:
    items = dataset.load_snapshot()
    assert len(items) == 45
    assert sum(len(item["expectedOutput"]["assertions"]) for item in items) == 121
    assert {assertion["type"] for item in items for assertion in item["expectedOutput"]["assertions"]} == {
        "equals",
        "contains",
        "regex",
        "not-regex",
        "not-icontains",
        "not-icontains-any",
    }
    assert dataset.normalized_bytes(items) == dataset.SNAPSHOT.read_bytes()


def test_stable_migration_id_and_expanded_aliases() -> None:
    items = dataset.load_snapshot()
    happy = next(item for item in items if item["metadata"]["legacy_identifier"] == "happy-1")
    assert happy["id"] == "7c46649d-2c90-5303-b1ea-0348a61244be"
    repeated = [
        item for item in items if item["metadata"]["legacy_identifier"] in {"numbers-8", "numbers-9"}
    ]
    assert repeated[0]["expectedOutput"]["assertions"][-1] == repeated[1]["expectedOutput"]["assertions"][-1]
    assert repeated[0]["expectedOutput"]["assertions"][-1] is not repeated[1]["expectedOutput"]["assertions"][-1]


def test_schemas_require_transcript_and_assertions() -> None:
    assert INPUT_SCHEMA["required"] == ["transcript"]
    assert EXPECTED_OUTPUT_SCHEMA["properties"]["assertions"]["minItems"] == 1
    with pytest.raises(ValueError, match="transcript"):
        validate_item({"input": {}, "expectedOutput": {"assertions": [{}]}})
    with pytest.raises(ValueError, match="non-empty"):
        validate_item({"input": {"transcript": "x"}, "expectedOutput": {"assertions": []}})
    with pytest.raises(ValueError, match="assertion value"):
        validate_item(
            {
                "input": {"transcript": "x"},
                "expectedOutput": {
                    "assertions": [{"type": "not-icontains-any", "metric": "m", "value": "x"}]
                },
            }
        )


class NotFound(Exception):
    status_code = 404


class FakeLangfuse:
    def __init__(self, exists: bool) -> None:
        self.exists = exists
        self.datasets: list[dict] = []
        self.items: list[dict] = []
        self.api = SimpleNamespace(
            datasets=SimpleNamespace(get=self.get_dataset),
        )

    def get_dataset(self, _name, fetch_items_page_size=None):
        if not self.exists:
            raise NotFound()
        return object()

    def create_dataset(self, **values):
        self.datasets.append(values)

    def create_dataset_item(self, **values):
        self.items.append(values)


def test_bootstrap_only_creates_an_absent_dataset() -> None:
    existing = FakeLangfuse(True)
    assert dataset.bootstrap(existing) is False
    assert not existing.datasets

    fresh = FakeLangfuse(False)
    assert dataset.bootstrap(fresh) is True
    assert len(fresh.datasets) == 1
    assert len(fresh.items) == 45
    assert fresh.datasets[0]["input_schema"] == INPUT_SCHEMA


def test_fetch_version_pins_timestamp_and_preserves_archived_status() -> None:
    expected_version = datetime(2026, 8, 14, tzinfo=UTC)
    item = SimpleNamespace(
        id="id",
        input={"transcript": "x"},
        expected_output={"assertions": [{"type": "equals", "metric": "m", "value": "x"}]},
        metadata={},
        status=SimpleNamespace(value="ARCHIVED"),
    )

    class Fake:
        def get_dataset(self, name, fetch_items_page_size, version):
            assert name == "evaluation/transcript-cleanup"
            assert fetch_items_page_size == 100
            assert version == expected_version
            return SimpleNamespace(items=[item])

    pinned, content = dataset.fetch_version(Fake(), expected_version)
    assert pinned == expected_version
    assert json.loads(content)["status"] == "ARCHIVED"


def test_atomic_write_replaces_content(tmp_path: Path) -> None:
    target = tmp_path / "snapshot.jsonl"
    target.write_bytes(b"old")
    dataset.atomic_write(target, b"new")
    assert target.read_bytes() == b"new"
    assert not list(tmp_path.glob(".snapshot.jsonl.*"))
