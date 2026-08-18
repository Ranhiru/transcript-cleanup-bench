from __future__ import annotations

import json

import httpx
import pytest
from langfuse.api import Prompt_Chat
from langfuse.model import ChatPromptClient

from transcript_cleanup_bench import proxy

COMPLETION = {
    "id": "chatcmpl-upstream",
    "object": "chat.completion",
    "created": 0,
    "model": "m",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "cleaned"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
}

MODELS = {
    "object": "list",
    "data": [{"id": "provider-model", "object": "model", "created": 0, "owned_by": "provider"}],
}

CHUNKS = [
    {
        "id": "chatcmpl-upstream",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": "cleaned"}}],
    },
    {
        "id": "chatcmpl-upstream",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "m",
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


def chat_prompt() -> ChatPromptClient:
    """A real prompt client, so compile() and Langfuse linking run the real code."""
    return ChatPromptClient(
        Prompt_Chat(
            name="transcript-cleanup",
            version=7,
            type="chat",
            labels=["production"],
            tags=[],
            config={},
            prompt=[
                {"role": "system", "content": "Clean the transcript."},
                {"role": "user", "content": "{{transcript}}"},
            ],
        )
    )


class Upstream:
    """The OpenAI-compatible server, faked at the HTTP layer so the real SDK runs."""

    def __init__(self) -> None:
        self.requests: list[dict | None] = []
        self.clients = 0
        self.offline = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.offline:
            raise httpx.ConnectError("offline", request=request)
        body = json.loads(request.content) if request.content else None
        self.requests.append(body)
        if not request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json=MODELS)
        if (body or {}).get("stream"):
            events = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in CHUNKS)
            return httpx.Response(
                200,
                text=events + "data: [DONE]\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json=COMPLETION)

    @property
    def sent(self) -> dict:
        return self.requests[0] or {}


@pytest.fixture(autouse=True)
def upstream(monkeypatch):
    server = Upstream()
    build_real = proxy.openai.AsyncOpenAI

    def build(**options):
        server.clients += 1
        return build_real(
            **options,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(server.handler)),
        )

    monkeypatch.setattr(proxy, "_upstream", None)
    monkeypatch.setattr(proxy.openai, "AsyncOpenAI", build)
    monkeypatch.setenv("OPENAI_API_HOST", "https://provider.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "server-secret")
    monkeypatch.setenv("LANGFUSE_PROMPT_NAME", "transcript-cleanup")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")
    monkeypatch.setattr(proxy, "langfuse_client", lambda: "langfuse")

    def resolve_prompt(langfuse, *, name, label):
        assert (langfuse, name, label) == ("langfuse", "transcript-cleanup", "production")
        return chat_prompt()

    monkeypatch.setattr(proxy, "resolve", resolve_prompt)
    return server


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=proxy.app), base_url="http://proxy"
    )


async def post(**body) -> httpx.Response:
    async with client() as http:
        return await http.post("/v1/chat/completions", json=body)


async def test_compiles_the_prompt_and_forwards_sampler_extensions(upstream) -> None:
    response = await post(
        model="m",
        messages=[{"role": "user", "content": "raw words"}],
        temperature=0.2,
        response_format={"type": "json_object"},
        top_k=4,
        min_p=0.1,
        repetition_penalty=1.1,
        chat_template_kwargs={"enable_thinking": False},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "cleaned"
    assert upstream.sent["messages"] == [
        {"role": "system", "content": "Clean the transcript."},
        {"role": "user", "content": "raw words"},
    ]
    assert upstream.sent["temperature"] == 0.2
    assert upstream.sent["response_format"] == {"type": "json_object"}
    # Extensions must reach the wire even though the OpenAI schema has no such fields.
    assert upstream.sent["top_k"] == 4
    assert upstream.sent["min_p"] == 0.1
    assert upstream.sent["repetition_penalty"] == 1.1
    assert upstream.sent["chat_template_kwargs"] == {"enable_thinking": False}


async def test_missing_temperature_defaults_to_zero(upstream) -> None:
    await post(model="m", messages=[{"role": "user", "content": "x"}])
    assert upstream.sent["temperature"] == 0


async def test_prepare_completion_links_the_resolved_prompt_version() -> None:
    options = proxy.prepare_completion(
        {"model": "m", "messages": [{"role": "user", "content": "x"}]}, "x"
    )
    linked = options["langfuse_prompt"]
    assert (linked.name, linked.version) == ("transcript-cleanup", 7)


async def test_streaming_relays_chunks_as_sse_preserving_tool_calls(upstream) -> None:
    response = await post(
        model="m", messages=[{"role": "user", "content": "x"}], stream=True
    )

    assert response.headers["content-type"].startswith("text/event-stream")
    assert upstream.sent["stream"] is True
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.strip().split("\n\n")
        if line and not line.endswith("[DONE]")
    ]
    assert response.text.endswith("data: [DONE]\n\n")
    assert payloads[0]["choices"][0]["delta"]["content"] == "cleaned"
    # Unset fields are omitted rather than serialized as nulls, matching native framing.
    assert "finish_reason" not in payloads[0]["choices"][0]
    assert payloads[1]["choices"][0]["delta"]["tool_calls"][0]["function"] == {
        "name": "lookup",
        "arguments": "{}",
    }


async def test_models_passes_through_the_upstream_listing() -> None:
    async with client() as http:
        response = await http.get("/v1/models")
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "provider-model"


@pytest.mark.parametrize("path", ["/v1/models", "/v1/chat/completions"])
async def test_unreachable_upstream_returns_openai_502(upstream, path) -> None:
    upstream.offline = True
    async with client() as http:
        response = (
            await http.get(path)
            if path.endswith("models")
            else await http.post(path, json={"model": "m", "messages": [{"role": "user", "content": "x"}]})
        )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_unavailable"


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "system", "content": "x"}],
        [{"role": "user", "content": ["x"]}],
        [{"role": "user", "content": "x"}, {"role": "user", "content": "y"}],
    ],
)
async def test_message_shapes_the_prompt_cannot_wrap_return_openai_400(
    upstream, messages
) -> None:
    response = await post(model="m", messages=messages)

    assert response.status_code == 400
    assert response.json()["error"] == {
        "message": "messages must contain exactly one user message with string content",
        "type": "invalid_request_error",
        "param": "messages",
        "code": "invalid_messages",
    }
    assert upstream.requests == []


async def test_unavailable_prompt_returns_openai_503(upstream, monkeypatch) -> None:
    def fail(*args, **values):
        raise RuntimeError("offline")

    monkeypatch.setattr(proxy, "resolve", fail)
    response = await post(model="m", messages=[{"role": "user", "content": "x"}])

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "prompt_unavailable"
    assert upstream.requests == []


async def test_upstream_client_is_pooled_and_closed_on_shutdown(upstream) -> None:
    for _ in range(2):
        await post(model="m", messages=[{"role": "user", "content": "x"}])

    assert upstream.clients == 1
    assert len(upstream.requests) == 2
    await proxy.close_client()
    assert proxy._upstream is None
