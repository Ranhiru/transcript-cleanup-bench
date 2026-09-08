from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langfuse.model import ChatPromptClient

from .config import REPO, langfuse_client, load_env
from .vocabulary import VocabularyContext

SEEDS = (
    (REPO / "prompts" / "v1.txt", ["baseline"]),
    (REPO / "prompts" / "v2.txt", []),
    (REPO / "prompts" / "v3.txt", ["production"]),
)


def prompt_name() -> str:
    return os.environ["LANGFUSE_PROMPT_NAME"]


def prompt_label() -> str:
    return os.environ["LANGFUSE_PROMPT_LABEL"]


def chat_messages(instructions: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": instructions.strip()},
        {"role": "user", "content": "{{transcript}}"},
    ]


def compile_messages(
    prompt: ChatPromptClient,
    *,
    transcript: str,
    vocabulary: VocabularyContext,
) -> list[dict[str, str]]:
    """Compile a prompt that explicitly declares its vocabulary context."""
    messages = prompt.compile(transcript=transcript, vocabulary=vocabulary.prompt)
    if not any(
        message.get("role") == "system" and vocabulary.prompt in message.get("content", "")
        for message in messages
    ):
        raise ValueError("transcript-cleanup system prompt must contain {{vocabulary}}")
    return messages


def resolve(
    langfuse: Any,
    *,
    name: str,
    label: str | None = None,
    version: int | None = None,
) -> ChatPromptClient:
    resolved = langfuse.get_prompt(
        name,
        label=label,
        version=version,
        type="chat",
        cache_ttl_seconds=0,
    )
    if not isinstance(resolved, ChatPromptClient):
        raise TypeError(f"Langfuse prompt {name!r} must be a chat prompt")
    return resolved


def seed_messages(path: Path) -> list[dict[str, str]]:
    return chat_messages(path.read_text())


def is_legacy_seed(langfuse: Any, *, name: str, prompt: Any) -> bool:
    """Whether this is the unmodified v1/v2 prompt seeded before v3 existed."""
    if sorted(prompt.versions) != [1, 2]:
        return False

    v1 = langfuse.get_prompt(name, version=1, type="chat", cache_ttl_seconds=0)
    v2 = langfuse.get_prompt(name, version=2, type="chat", cache_ttl_seconds=0)

    return (
        set(v1.labels) == {"baseline"}
        and v1.tags == []
        and v1.config == {}
        and v1.compile() == seed_messages(REPO / "prompts" / "v1.txt")
        and set(v2.labels) in ({"production"}, {"production", "latest"})
        and v2.tags == []
        and v2.config == {}
        and v2.compile() == seed_messages(REPO / "prompts" / "v2.txt")
    )


def bootstrap(langfuse: Any, name: str | None = None) -> bool:
    name = name or prompt_name()
    response = langfuse.api.prompts.list(name=name, limit=100)
    matches = [prompt for prompt in response.data if prompt.name == name]

    if matches:
        prompt = matches[0]
        if prompt.type != "chat":
            raise SystemExit(
                f"Langfuse prompt {name!r} is not a chat prompt; delete or rename it, "
                "then run `make sync` again"
            )
        if is_legacy_seed(langfuse, name=name, prompt=prompt):
            path = REPO / "prompts" / "v3.txt"
            langfuse.create_prompt(
                name=name,
                prompt=seed_messages(path),
                labels=["production"],
                type="chat",
                commit_message="Migrate legacy production prompt to v3",
            )
            print(f"migrated {name} production from v2 to v3")
            return True
        if "production" not in prompt.labels:
            raise SystemExit(
                f"Langfuse prompt {name!r} has no production label; assign the label to "
                "a chat prompt version, then run `make sync` again"
            )
        print(f"prompt exists; leaving {name} unchanged")
        return False

    for path, labels in SEEDS:
        langfuse.create_prompt(
            name=name,
            prompt=seed_messages(path),
            labels=labels,
            type="chat",
            commit_message=f"Bootstrap seed {path.stem}",
        )
    print(f"bootstrapped {name} with baseline and production versions")
    return True


def main() -> None:
    load_env("prompts")
    langfuse = langfuse_client()
    try:
        bootstrap(langfuse)
    finally:
        langfuse.shutdown()


if __name__ == "__main__":
    main()
