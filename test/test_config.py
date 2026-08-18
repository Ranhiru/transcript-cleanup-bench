from __future__ import annotations

from transcript_cleanup_bench import config


def test_langfuse_client_enables_v4_ingestion(monkeypatch) -> None:
    options = {}

    def fake_langfuse(**values):
        options.update(values)
        return "client"

    monkeypatch.setattr(config, "Langfuse", fake_langfuse)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example")

    assert config.langfuse_client() == "client"
    assert options == {
        "public_key": "public",
        "secret_key": "secret",
        "base_url": "https://langfuse.example",
        "additional_headers": {"x-langfuse-ingestion-version": "4"},
    }
