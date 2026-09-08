from __future__ import annotations

from types import SimpleNamespace

import pytest

from transcript_cleanup_bench import prompts


class FakeLangfuse:
    def __init__(self, existing=None, versions=None):
        self.existing = existing or []
        self.versions = versions or {}
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

    def get_prompt(self, name, *, version, **_values):
        return self.versions[version]


def prompt_meta(*, prompt_type="chat", labels=None, versions=None):
    return SimpleNamespace(
        name="transcript-cleanup",
        type=prompt_type,
        labels=labels if labels is not None else ["production"],
        versions=versions if versions is not None else [1, 2, 3],
    )


class FakeChatPrompt:
    def __init__(self, messages, labels, *, config=None, tags=None):
        self.messages = messages
        self.labels = labels
        self.config = config if config is not None else {}
        self.tags = tags if tags is not None else []

    def compile(self):
        return self.messages


def test_bootstrap_creates_every_seed_as_chat_messages() -> None:
    langfuse = FakeLangfuse()

    assert prompts.bootstrap(langfuse, "transcript-cleanup") is True

    assert [created["labels"] for created in langfuse.created] == [
        ["baseline"],
        [],
        ["production"],
    ]
    assert [created["type"] for created in langfuse.created] == ["chat", "chat", "chat"]
    assert all(created["prompt"][0]["role"] == "system" for created in langfuse.created)
    assert all(
        created["prompt"][1] == {"role": "user", "content": "{{transcript}}"}
        for created in langfuse.created
    )
    assert all(
        "{{transcript}}" not in created["prompt"][0]["content"]
        for created in langfuse.created
    )
    assert langfuse.listed == [{"name": "transcript-cleanup", "limit": 100}]


def test_bootstrap_preserves_an_existing_valid_prompt() -> None:
    langfuse = FakeLangfuse([prompt_meta()])

    assert prompts.bootstrap(langfuse, "transcript-cleanup") is False
    assert langfuse.created == []


def test_bootstrap_migrates_the_unmodified_legacy_v2_production_prompt() -> None:
    langfuse = FakeLangfuse(
        [prompt_meta(versions=[1, 2])],
        {
            1: FakeChatPrompt(
                prompts.seed_messages(prompts.REPO / "prompts" / "v1.txt"), ["baseline"]
            ),
            2: FakeChatPrompt(
                prompts.seed_messages(prompts.REPO / "prompts" / "v2.txt"), ["latest", "production"]
            ),
        },
    )

    assert prompts.bootstrap(langfuse, "transcript-cleanup") is True
    assert len(langfuse.created) == 1
    assert langfuse.created[0]["labels"] == ["production"]
    assert langfuse.created[0]["prompt"] == prompts.seed_messages(
        prompts.REPO / "prompts" / "v3.txt"
    )

    langfuse.existing[0].versions.append(3)
    assert prompts.bootstrap(langfuse, "transcript-cleanup") is False
    assert len(langfuse.created) == 1


def test_bootstrap_preserves_a_modified_legacy_prompt() -> None:
    langfuse = FakeLangfuse(
        [prompt_meta(versions=[1, 2])],
        {
            1: FakeChatPrompt(
                prompts.seed_messages(prompts.REPO / "prompts" / "v1.txt"), ["baseline"]
            ),
            2: FakeChatPrompt([{"role": "system", "content": "operator managed"}], ["production"]),
        },
    )

    assert prompts.bootstrap(langfuse, "transcript-cleanup") is False
    assert langfuse.created == []


def test_bootstrap_preserves_a_legacy_prompt_with_operator_config() -> None:
    langfuse = FakeLangfuse(
        [prompt_meta(versions=[1, 2])],
        {
            1: FakeChatPrompt(
                prompts.seed_messages(prompts.REPO / "prompts" / "v1.txt"), ["baseline"]
            ),
            2: FakeChatPrompt(
                prompts.seed_messages(prompts.REPO / "prompts" / "v2.txt"), ["production"],
                config={"temperature": 0.2},
            ),
        },
    )

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
