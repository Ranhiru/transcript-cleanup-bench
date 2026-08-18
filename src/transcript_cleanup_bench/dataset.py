from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from langfuse import Langfuse
from langfuse.api import DatasetStatus, NotFoundError

from .config import DATASET_NAME, REPO, langfuse_client, load_env

SNAPSHOT = REPO / "datasets" / "evaluation-transcript-cleanup.jsonl"


def load_snapshot(path: Path = SNAPSHOT) -> list[dict[str, Any]]:
    items = [json.loads(line) for line in path.read_text().splitlines() if line]
    if len({item["id"] for item in items}) != len(items):
        raise ValueError("snapshot contains duplicate item IDs")
    return items


def normalize_item(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "input": item.input,
        "expectedOutput": item.expected_output,
        "metadata": item.metadata,
        "status": getattr(item.status, "value", str(item.status)),
    }


def normalized_bytes(items: Iterable[dict[str, Any]]) -> bytes:
    return "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for item in sorted(items, key=lambda value: value["id"])
    ).encode()


def snapshot_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def bootstrap(langfuse: Langfuse) -> bool:
    try:
        langfuse.get_dataset(DATASET_NAME, fetch_items_page_size=1)
        print(f"dataset exists; leaving {DATASET_NAME} unchanged")
        return False
    except NotFoundError:
        pass

    items = load_snapshot()
    langfuse.create_dataset(
        name=DATASET_NAME,
        description="Authoritative transcript-cleanup evaluation cases",
        metadata={"seed": str(SNAPSHOT.relative_to(REPO))},
    )
    for item in items:
        langfuse.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=item["id"],
            input=item["input"],
            expected_output=item["expectedOutput"],
            metadata=item["metadata"],
            status=DatasetStatus(item["status"]),
        )
    print(f"bootstrapped {DATASET_NAME} with {len(items)} items")
    return True


def fetch_version(langfuse: Langfuse, version: datetime | None = None) -> tuple[datetime, bytes]:
    pinned = version or datetime.now(UTC)
    dataset = langfuse.get_dataset(DATASET_NAME, fetch_items_page_size=100, version=pinned)
    return pinned, normalized_bytes(normalize_item(item) for item in dataset.items)


def export(langfuse: Langfuse) -> tuple[datetime, str]:
    pinned, content = fetch_version(langfuse)
    atomic_write(SNAPSHOT, content)
    digest = snapshot_hash(content)
    print(f"exported {DATASET_NAME} at {pinned.isoformat()} ({digest})")
    return pinned, digest


def check(langfuse: Langfuse) -> bool:
    pinned, content = fetch_version(langfuse)
    current = SNAPSHOT.read_bytes()
    if content != current:
        print(f"dataset drift at {pinned.isoformat()}; run `make dataset-export`")
        return False
    print(f"dataset matches snapshot ({snapshot_hash(current)})")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["bootstrap", "export", "check"])
    args = parser.parse_args()
    load_env()
    langfuse = langfuse_client()
    try:
        if args.command == "bootstrap":
            bootstrap(langfuse)
        elif args.command == "export":
            export(langfuse)
        elif not check(langfuse):
            raise SystemExit(1)
    finally:
        langfuse.shutdown()


if __name__ == "__main__":
    main()
