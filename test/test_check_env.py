from __future__ import annotations

import runpy
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_env.py"


def valid_values() -> dict[str, str]:
    values = {
        "LANGFUSE_PUBLIC_KEY": "public",
        "LANGFUSE_SECRET_KEY": "secret",
        "OMLX_API_KEY": "omlx",
        "LANGFUSE_INIT_ORG_ID": "org",
        "LANGFUSE_INIT_PROJECT_ID": "project",
        "LANGFUSE_INIT_PROJECT_PUBLIC_KEY": "public",
        "LANGFUSE_INIT_PROJECT_SECRET_KEY": "secret",
        "LANGFUSE_INIT_USER_EMAIL": "admin@example.test",
        "LANGFUSE_INIT_USER_PASSWORD": "password",
        "NEXTAUTH_SECRET": "nextauth",
        "SALT": "salt",
        "ENCRYPTION_KEY": "a" * 64,
        "POSTGRES_PASSWORD": "postgres",
        "CLICKHOUSE_PASSWORD": "clickhouse",
        "REDIS_AUTH": "redis",
        "MINIO_ROOT_PASSWORD": "minio",
    }
    return values


def write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text("\n".join(f'{key}="{value}"' for key, value in values.items()) + "\n")


def run_check(monkeypatch, tmp_path: Path, values: dict[str, str]) -> None:
    write_env(tmp_path / ".env", values)
    monkeypatch.chdir(tmp_path)
    for key in valid_values():
        monkeypatch.delenv(key, raising=False)
    runpy.run_path(str(SCRIPT), run_name="__main__")


def test_dotenv_quoting_and_valid_values(monkeypatch, tmp_path, capsys) -> None:
    run_check(monkeypatch, tmp_path, valid_values())
    assert capsys.readouterr().out == ".env is valid\n"


def test_environment_takes_precedence(monkeypatch, tmp_path) -> None:
    values = valid_values()
    values["OMLX_API_KEY"] = "change-me"
    write_env(tmp_path / ".env", values)
    monkeypatch.chdir(tmp_path)
    for key in values:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OMLX_API_KEY", "from-environment")
    runpy.run_path(str(SCRIPT), run_name="__main__")


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("OMLX_API_KEY", "", "missing"),
        ("OMLX_API_KEY", "change-me", "replace placeholders"),
        ("ENCRYPTION_KEY", "not-hex", "64 hexadecimal"),
        ("LANGFUSE_PUBLIC_KEY", "different", "must match"),
    ],
)
def test_invalid_values(monkeypatch, tmp_path, key, value, message) -> None:
    values = valid_values()
    values[key] = value
    with pytest.raises(SystemExit, match=message):
        run_check(monkeypatch, tmp_path, values)
