from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .config import REPO

VOCABULARY = REPO / "vocabulary.yaml"


@dataclass(frozen=True)
class VocabularyContext:
    prompt: str
    revision: str


@lru_cache
def load_vocabulary(path: Path = VOCABULARY) -> VocabularyContext:
    """Load and render the server-owned vocabulary used by prompts and traces."""
    entries: Any = yaml.safe_load(path.read_text())
    if not isinstance(entries, list) or not entries:
        raise ValueError("vocabulary must be a non-empty list")

    lines: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or set(entry) != {"term", "description"}:
            raise ValueError(
                f"vocabulary entry {index} must contain only term and description"
            )
        term = entry["term"]
        description = entry["description"]
        if not isinstance(term, str) or not term.strip() or "\n" in term:
            raise ValueError(f"vocabulary entry {index} has an invalid term")
        if (
            not isinstance(description, str)
            or not description.strip()
            or "\n" in description
        ):
            raise ValueError(f"vocabulary entry {index} has an invalid description")
        term = term.strip()
        description = description.strip()
        key = term.casefold()
        if key in seen:
            raise ValueError(f"duplicate vocabulary term: {term}")
        seen.add(key)
        lines.append(f"- {term}: {description}")

    prompt = "\n".join(
        [
            "KNOWN VOCABULARY",
            "",
            "The speaker commonly discusses the canonical terms below. Treat them as",
            "contextual evidence, not unconditional substitutions. When dictated speech",
            "contains a phonetically similar word or phrase, use the whole sentence to decide",
            "whether the known term was intended. Handle multiword and heavily distorted",
            "pronunciations. If the intended term remains uncertain, preserve the original.",
            "",
            *lines,
        ]
    )
    revision = hashlib.sha256(prompt.encode()).hexdigest()[:12]
    return VocabularyContext(prompt=prompt, revision=revision)
