from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langfuse.model import ChatPromptClient

from .dataset import client

REPO = Path(__file__).resolve().parents[2]
SEEDS = (
    (REPO / "prompts" / "v1.txt", ["baseline"]),
    (REPO / "prompts" / "v2.txt", ["production"]),
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
            prompt=chat_messages(path.read_text()),
            labels=labels,
            type="chat",
            commit_message=f"Bootstrap seed {path.stem}",
        )
    print(f"bootstrapped {name} with baseline and production versions")
    return True


def main() -> None:
    langfuse = client()
    try:
        bootstrap(langfuse)
    finally:
        langfuse.shutdown()


if __name__ == "__main__":
    main()
