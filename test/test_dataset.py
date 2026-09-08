from __future__ import annotations

from types import SimpleNamespace

from transcript_cleanup_bench import dataset


class FakeLangfuse:
    def __init__(self, items):
        self.items = items
        self.created = []

    def get_dataset(self, name, *, fetch_items_page_size):
        assert name == dataset.DATASET_NAME
        assert fetch_items_page_size == 100
        return SimpleNamespace(items=self.items)

    def create_dataset_item(self, **values):
        self.created.append(values)


def test_bootstrap_imports_only_snapshot_ids_missing_from_existing_dataset(monkeypatch) -> None:
    snapshot = [
        {
            "id": "existing",
            "input": "new input",
            "expectedOutput": "new output",
            "metadata": {},
            "status": "ACTIVE",
        },
        {
            "id": "missing",
            "input": "input",
            "expectedOutput": "output",
            "metadata": {},
            "status": "ACTIVE",
        },
    ]
    monkeypatch.setattr(dataset, "load_snapshot", lambda: snapshot)
    existing = SimpleNamespace(id="existing", input="authoritative", expected_output="edited")
    langfuse = FakeLangfuse([existing])

    assert dataset.bootstrap(langfuse) is True
    assert [item["id"] for item in langfuse.created] == ["missing"]
    assert existing.input == "authoritative"
    assert existing.expected_output == "edited"

    langfuse.items.extend(SimpleNamespace(id=item["id"]) for item in langfuse.created)
    assert dataset.bootstrap(langfuse) is False
    assert [item["id"] for item in langfuse.created] == ["missing"]


def test_bootstrap_is_a_noop_when_existing_dataset_already_has_snapshot_ids(monkeypatch) -> None:
    snapshot = [
        {
            "id": "existing",
            "input": "input",
            "expectedOutput": "output",
            "metadata": {},
            "status": "ACTIVE",
        },
    ]
    monkeypatch.setattr(dataset, "load_snapshot", lambda: snapshot)
    langfuse = FakeLangfuse([SimpleNamespace(id="existing")])

    assert dataset.bootstrap(langfuse) is False
    assert langfuse.created == []
