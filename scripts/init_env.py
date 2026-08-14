#!/usr/bin/env python3
from __future__ import annotations

import getpass
import os
import secrets
import tempfile
from pathlib import Path

from dotenv import dotenv_values

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / ".env.example"
TARGET = REPO / ".env"

GENERATED = {
    "LANGFUSE_INIT_USER_PASSWORD": lambda: secrets.token_urlsafe(32),
    "NEXTAUTH_SECRET": lambda: secrets.token_urlsafe(48),
    "SALT": lambda: secrets.token_urlsafe(48),
    "ENCRYPTION_KEY": lambda: secrets.token_hex(32),
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(32),
    "CLICKHOUSE_PASSWORD": lambda: secrets.token_urlsafe(32),
    "REDIS_AUTH": lambda: secrets.token_urlsafe(32),
    "MINIO_ROOT_PASSWORD": lambda: secrets.token_urlsafe(32),
}


def usable(value: str | None) -> bool:
    return bool(value) and "change-me" not in value


def build_values(existing: dict[str, str | None], api_key: str) -> dict[str, str]:
    template = dotenv_values(TEMPLATE)
    values = {
        key: existing[key] if usable(existing.get(key)) else str(value)
        for key, value in template.items()
        if value is not None
    }
    values["OPENAI_API_KEY"] = api_key

    public_key = next(
        (
            value
            for value in (
                existing.get("LANGFUSE_PUBLIC_KEY"),
                existing.get("LANGFUSE_INIT_PROJECT_PUBLIC_KEY"),
            )
            if usable(value)
        ),
        f"pk-lf-{secrets.token_hex(16)}",
    )
    secret_key = next(
        (
            value
            for value in (
                existing.get("LANGFUSE_SECRET_KEY"),
                existing.get("LANGFUSE_INIT_PROJECT_SECRET_KEY"),
            )
            if usable(value)
        ),
        f"sk-lf-{secrets.token_hex(32)}",
    )
    values["LANGFUSE_PUBLIC_KEY"] = public_key
    values["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"] = public_key
    values["LANGFUSE_SECRET_KEY"] = secret_key
    values["LANGFUSE_INIT_PROJECT_SECRET_KEY"] = secret_key

    for key, generate in GENERATED.items():
        if not usable(existing.get(key)):
            values[key] = generate()
    return values


def render(values: dict[str, str]) -> str:
    lines = []
    for line in TEMPLATE.read_text().splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            lines.append(line)
            continue
        key = line.split("=", 1)[0]
        lines.append(f"{key}={values[key]}")
    return "\n".join(lines) + "\n"


def atomic_write(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    existing = dict(dotenv_values(TARGET)) if TARGET.exists() else {}
    api_key = os.environ.get("OPENAI_API_KEY") or existing.get("OPENAI_API_KEY")
    if not usable(api_key):
        api_key = getpass.getpass("OPENAI_API_KEY: ")
    if not usable(api_key):
        raise SystemExit("OPENAI_API_KEY must not be empty or contain change-me")
    atomic_write(TARGET, render(build_values(existing, api_key)))
    print("Generated and secured .env")


if __name__ == "__main__":
    main()
