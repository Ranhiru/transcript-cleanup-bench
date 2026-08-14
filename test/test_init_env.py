from __future__ import annotations

import importlib.util
import stat
from pathlib import Path

from dotenv import dotenv_values

SCRIPT = Path(__file__).parents[1] / "scripts" / "init_env.py"
SPEC = importlib.util.spec_from_file_location("init_env", SCRIPT)
assert SPEC and SPEC.loader
init_env = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(init_env)


def test_build_values_generates_secrets_and_matches_langfuse_keys() -> None:
    values = init_env.build_values({}, "local-key")

    assert values["OPENAI_API_KEY"] == "local-key"
    assert values["OPENAI_API_HOST"] == "http://localhost:8000/v1"
    assert values["LANGFUSE_PROMPT_NAME"] == "transcript-cleanup"
    assert values["LANGFUSE_PROMPT_LABEL"] == "production"
    assert values["LANGFUSE_PUBLIC_KEY"] == values["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"]
    assert values["LANGFUSE_SECRET_KEY"] == values["LANGFUSE_INIT_PROJECT_SECRET_KEY"]
    assert len(values["ENCRYPTION_KEY"]) == 64
    assert all("change-me" not in value for value in values.values())


def test_build_values_preserves_valid_existing_secrets() -> None:
    values = init_env.build_values(
        {
            "POSTGRES_PASSWORD": "existing-password",
            "LANGFUSE_INIT_PROJECT_PUBLIC_KEY": "existing-public-key",
        },
        "local-key",
    )

    assert values["POSTGRES_PASSWORD"] == "existing-password"
    assert values["LANGFUSE_PUBLIC_KEY"] == "existing-public-key"


def test_atomic_write_uses_owner_only_permissions(tmp_path) -> None:
    target = tmp_path / ".env"
    init_env.atomic_write(target, "KEY=value\n")

    assert dotenv_values(target) == {"KEY": "value"}
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_main_reuses_existing_api_key_when_adding_new_defaults(
    monkeypatch, tmp_path, capsys
) -> None:
    target = tmp_path / ".env"
    target.write_text("OPENAI_API_KEY=existing-key\n")
    monkeypatch.setattr(init_env, "TARGET", target)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def unexpected_prompt(_message):
        raise AssertionError("existing API key should avoid an interactive prompt")

    monkeypatch.setattr(init_env.getpass, "getpass", unexpected_prompt)

    init_env.main()

    values = dotenv_values(target)
    assert values["OPENAI_API_KEY"] == "existing-key"
    assert values["LANGFUSE_PROMPT_NAME"] == "transcript-cleanup"
    assert values["LANGFUSE_PROMPT_LABEL"] == "production"
    assert capsys.readouterr().out == "Generated and secured .env\n"
