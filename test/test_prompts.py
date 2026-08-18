from __future__ import annotations

from types import SimpleNamespace

import pytest

from transcript_cleanup_bench import prompts


class FakeLangfuse:
    def __init__(self, existing=None):
        self.existing = existing or []
        self.created = []
        self.listed = []
        self.api = SimpleNamespace(
            prompts=SimpleNamespace(list=self.list_prompts),
        )

    def list_prompts(self, *, name, limit):
        self.listed.append({"name": name, "limit": limit})
        return SimpleNamespace(data=self.existing)

    def create_prompt(self, **values):
        self.created.append(values)


def prompt_meta(*, prompt_type="chat", labels=None):
    return SimpleNamespace(
        name="transcript-cleanup",
        type=prompt_type,
        labels=labels if labels is not None else ["production"],
    )


def test_bootstrap_creates_v1_then_v2_as_chat_messages() -> None:
    langfuse = FakeLangfuse()

    assert prompts.bootstrap(langfuse, "transcript-cleanup") is True

    assert [created["labels"] for created in langfuse.created] == [
        ["baseline"],
        ["production"],
    ]
    assert [created["type"] for created in langfuse.created] == ["chat", "chat"]
    assert all(created["prompt"][0]["role"] == "system" for created in langfuse.created)
    assert all(
        created["prompt"][1] == {"role": "user", "content": "{{transcript}}"}
        for created in langfuse.created
    )
    assert "{{transcript}}" not in langfuse.created[0]["prompt"][0]["content"]
    assert "{{transcript}}" not in langfuse.created[1]["prompt"][0]["content"]
    assert langfuse.listed == [{"name": "transcript-cleanup", "limit": 100}]


def test_bootstrap_preserves_an_existing_valid_prompt() -> None:
    langfuse = FakeLangfuse([prompt_meta()])

    assert prompts.bootstrap(langfuse, "transcript-cleanup") is False
    assert langfuse.created == []


def test_resolve_rejects_a_prompt_langfuse_returns_as_text() -> None:
    langfuse = SimpleNamespace(get_prompt=lambda *args, **values: object())

    with pytest.raises(TypeError, match="must be a chat prompt"):
        prompts.resolve(langfuse, name="transcript-cleanup", label="production")


@pytest.mark.parametrize(
    ("existing", "message"),
    [
        (prompt_meta(prompt_type="text"), "not a chat prompt"),
        (prompt_meta(labels=["candidate"]), "no production label"),
    ],
)
def test_bootstrap_rejects_invalid_existing_prompts(existing, message) -> None:
    with pytest.raises(SystemExit, match=message):
        prompts.bootstrap(FakeLangfuse([existing]), "transcript-cleanup")
