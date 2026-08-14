from __future__ import annotations

import json

import httpx
import pytest

from transcript_cleanup_bench import proxy


class FakeTrace:
    instances = []

    def __init__(self, body):
        self.body = body
        self.finished = None
        self.instances.append(self)

    def finish(self, **values):
        self.finished = values


@pytest.fixture(autouse=True)
def fake_tracing(monkeypatch):
    FakeTrace.instances.clear()
    monkeypatch.setattr(proxy, "TraceGeneration", FakeTrace)
    monkeypatch.setenv("OMLX_API_KEY", "server-secret")


def app_client(handler) -> tuple[httpx.AsyncClient, httpx.AsyncClient]:
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    proxy.app.state.upstream = upstream
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=proxy.app), base_url="http://proxy")
    return client, upstream


@pytest.mark.asyncio
async def test_non_streaming_passthrough_and_credential_replacement() -> None:
    seen = {}

    def handler(request: httpx.Request):
        seen["headers"] = request.headers
        seen["json"] = json.loads(request.content)
        return httpx.Response(
            201,
            headers={"x-upstream": "kept", "connection": "x-secret", "x-secret": "drop"},
            json={
                "unknown": {"preserved": True},
                "choices": [{"message": {"content": " cleaned "}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    client, upstream = app_client(handler)
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            headers={"authorization": "Bearer client-secret", "connection": "x-hop", "x-hop": "drop"},
            json={"model": "m", "messages": [{"role": "user", "content": "x"}], "unknown": 7},
        )
    await upstream.aclose()
    assert response.status_code == 201
    assert response.json()["unknown"] == {"preserved": True}
    assert response.headers["x-upstream"] == "kept"
    assert "x-secret" not in response.headers
    assert seen["headers"]["authorization"] == "Bearer server-secret"
    assert "x-hop" not in seen["headers"]
    assert seen["json"]["unknown"] == 7
    assert FakeTrace.instances[0].finished["usage"]["total_tokens"] == 3


@pytest.mark.asyncio
async def test_streaming_bytes_are_unchanged_and_traced() -> None:
    body = (
        b'data: {"choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"!"},"finish_reason":"stop"}],'
        b'"usage":{"total_tokens":4}}\n\ndata: [DONE]\n\n'
    )

    class BodyStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield body[:23]
            yield body[23:]

    def handler(_request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=BodyStream())

    client, upstream = app_client(handler)
    async with client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "m", "messages": [], "stream": True, "top_k": 0},
        )
    await upstream.aclose()
    assert response.content == body
    assert FakeTrace.instances[0].finished["output"] == "Hi!"
    assert FakeTrace.instances[0].finished["finish_reason"] == "stop"
    assert FakeTrace.instances[0].finished["first_token_at"] is not None


@pytest.mark.asyncio
async def test_status_and_model_body_are_preserved() -> None:
    def handler(_request):
        return httpx.Response(418, content=b'{"custom":"teapot"}', headers={"content-type": "application/json"})

    client, upstream = app_client(handler)
    async with client:
        response = await client.get("/v1/models")
    await upstream.aclose()
    assert response.status_code == 418
    assert response.content == b'{"custom":"teapot"}'


@pytest.mark.asyncio
async def test_connection_failure_returns_openai_502_without_retry() -> None:
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)

    client, upstream = app_client(handler)
    async with client:
        response = await client.post("/v1/chat/completions", json={"model": "m", "messages": []})
    await upstream.aclose()
    assert calls == 1
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_unavailable"


def test_redaction_is_recursive() -> None:
    assert proxy.redact({"api_key": "x", "nested": [{"access_token": "y"}], "safe": 1}) == {
        "api_key": "[REDACTED]",
        "nested": [{"access_token": "[REDACTED]"}],
        "safe": 1,
    }
