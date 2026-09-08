import hashlib
from pathlib import Path

import pytest

from transcript_cleanup_bench.vocabulary import load_vocabulary


def write(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


def test_load_vocabulary_renders_canonical_terms_and_stable_revision(tmp_path: Path) -> None:
    path = write(
        tmp_path / "vocabulary.yaml",
        """
- term: Xero
  description: accounting software company
- term: TypeScript
  description: programming language
""".strip(),
    )

    first = load_vocabulary(path)
    second = load_vocabulary(path)

    assert first == second
    assert first.revision == hashlib.sha256(first.prompt.encode()).hexdigest()[:12]
    assert "contextual evidence, not unconditional substitutions" in first.prompt
    assert "- Xero: accounting software company" in first.prompt
    assert "- TypeScript: programming language" in first.prompt


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{}", "non-empty list"),
        ("- term: Xero", "only term and description"),
        (
            "- term: Xero\n  description: one\n- term: xero\n  description: two",
            "duplicate vocabulary term",
        ),
    ],
)
def test_load_vocabulary_rejects_invalid_entries(
    tmp_path: Path, content: str, message: str
) -> None:
    path = write(tmp_path / "vocabulary.yaml", content)

    with pytest.raises(ValueError, match=message):
        load_vocabulary(path)
