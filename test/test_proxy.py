from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from transcript_cleanup_bench import proxy


class FakeModel:
    def __init__(self, value):
        self.value = value

    def model_dump_json(self, *, exclude_none):
        assert exclude_none is True
        return json.dumps(self.value, separators=(",", ":"))


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield FakeModel(chunk)


class FakeCompletions:
    def __init__(self, owner):
        self.owner = owner

    async def create(self, **options):
        self.owner.calls.append(options)
        if self.owner.error:
            raise self.owner.error
        if options.get("stream") is True:
            return FakeStream(self.owner.stream_chunks)
        return FakeModel(self.owner.response)


class FakeOpenAI:
    instances: list["FakeOpenAI"] = []
    error: Exception | None = None
    response = {
        "id": "chatcmpl-upstream",
        "object": "chat.completion",
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "cleaned"},
                "finish_reason": "stop",
                "logprobs": {"content": []},
            }
        ],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }
    stream_chunks = [
        {
            "id": "chatcmpl-upstream",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"role": "assistant"}}],
        },
        {
            "id": "chatcmpl-upstream",
            "object": "chat.completion.chunk",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": "{}"},
                            }
                        ]
                    },
                }
            ],
        },
    ]

    def __init__(self, **options):
        self.options = options
        self.calls = []
        self.closed = False
        self.chat = SimpleNamespace(completions=FakeCompletions(self))
        self.instances.append(self)

    async def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def fake_openai(monkeypatch):
    FakeOpenAI.instances.clear()
    FakeOpenAI.error = None
    monkeypatch.setattr(proxy.openai, "AsyncOpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_HOST", "https://provider.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "server-secret")
    monkeypatch.delenv("CONTAINERIZED", raising=False)


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=proxy.app), base_url="http://proxy"
    )


@pytest.mark.asyncio
async def test_non_streaming_uses_native_openai_schema_and_option_routing() -> None:
    async with client() as http:
        response = await http.post(
            "/v1/chat/completions",
            headers={"authorization": "Bearer client-secret"},
            json={
                "model": "m",
                "messages": [{"role": "user", "content": "x"}],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "top_k": 4,
                "min_p": 0.1,
                "repetition_penalty": 1.1,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )

    assert response.status_code == 200
    assert response.json() == FakeOpenAI.response
    upstream = FakeOpenAI.instances[0]
    assert upstream.options["api_key"] == "server-secret"
    assert upstream.options["base_url"] == "https://provider.example/v1"
    assert upstream.calls[0]["temperature"] == 0.2
    assert upstream.calls[0]["response_format"] == {"type": "json_object"}
    assert upstream.calls[0]["extra_body"] == {
        "top_k": 4,
        "min_p": 0.1,
        "repetition_penalty": 1.1,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    assert upstream.closed is True


@pytest.mark.asyncio
async def test_streaming_serializes_native_openai_chunks_as_sse() -> None:
    async with client() as http:
        response = await http.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [], "stream": True},
        )

    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == "".join(
        f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n"
        for chunk in FakeOpenAI.stream_chunks
    ) + "data: [DONE]\n\n"
    assert FakeOpenAI.instances[0].closed is True


@pytest.mark.asyncio
async def test_models_lists_configured_models() -> None:
    async with client() as http:
        response = await http.get("/v1/models")
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "gemma-4-e4b-it-4bit"


@pytest.mark.asyncio
async def test_upstream_failure_returns_openai_502_and_closes_client() -> None:
    FakeOpenAI.error = RuntimeError("offline")
    async with client() as http:
        response = await http.post(
            "/v1/chat/completions", json={"model": "m", "messages": []}
        )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_unavailable"
    assert FakeOpenAI.instances[0].closed is True


def test_container_rewrites_only_loopback_api_hosts(monkeypatch) -> None:
    monkeypatch.setenv("CONTAINERIZED", "true")
    monkeypatch.setenv("OPENAI_API_HOST", "http://localhost:8000/v1")
    assert proxy.api_host() == "http://host.docker.internal:8000/v1"

    monkeypatch.setenv("OPENAI_API_HOST", "https://api.openai.com/v1")
    assert proxy.api_host() == "https://api.openai.com/v1"
