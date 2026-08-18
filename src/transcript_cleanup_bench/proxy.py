from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from langfuse.openai import openai

from .config import EXTRA_BODY_OPTIONS, langfuse_client, load_env
from .prompts import prompt_label, prompt_name, resolve

load_env()

_upstream: openai.AsyncOpenAI | None = None


LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def api_host() -> str:
    """In a container, a loopback upstream means the host, reachable via the gateway.

    Matches the hostname exactly, so a real host merely starting with `localhost`
    is left alone.
    """
    host = os.environ["OPENAI_API_HOST"]
    if os.environ.get("CONTAINERIZED") != "true":
        return host
    parts = urlsplit(host)
    if parts.hostname not in LOOPBACK:
        return host
    gateway = "host.docker.internal"
    return urlunsplit(
        parts._replace(netloc=f"{gateway}:{parts.port}" if parts.port else gateway)
    )


def client() -> openai.AsyncOpenAI:
    """Hold one upstream client for the process so connections stay pooled."""
    global _upstream
    if _upstream is None:
        _upstream = openai.AsyncOpenAI(
            base_url=api_host(),
            api_key=os.environ["OPENAI_API_KEY"],
        )
    return _upstream


async def close_client() -> None:
    global _upstream
    if _upstream is not None:
        await _upstream.close()
        _upstream = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await close_client()


app = FastAPI(title="OpenAI-compatible tracing proxy", lifespan=lifespan)


def completion_options(body: dict[str, Any]) -> dict[str, Any]:
    options = {key: value for key, value in body.items() if key not in EXTRA_BODY_OPTIONS}
    extensions = {key: body[key] for key in EXTRA_BODY_OPTIONS if key in body}
    if extensions:
        options["extra_body"] = {**options.get("extra_body", {}), **extensions}
    return options


def openai_error(
    status_code: int,
    *,
    message: str,
    error_type: str,
    code: str,
    param: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": param,
                "code": code,
            }
        },
    )


def upstream_error(error: Exception) -> JSONResponse:
    return openai_error(
        502,
        message=f"OpenAI-compatible API is unavailable: {type(error).__name__}",
        error_type="upstream_connection_error",
        code="upstream_unavailable",
    )


def invalid_messages() -> JSONResponse:
    return openai_error(
        400,
        message="messages must contain exactly one user message with string content",
        error_type="invalid_request_error",
        code="invalid_messages",
        param="messages",
    )


def raw_transcript(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) != 1:
        return None
    message = messages[0]
    if not isinstance(message, dict) or message.get("role") != "user":
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None


def prepare_completion(body: dict[str, Any], transcript: str) -> dict[str, Any]:
    langfuse_prompt = resolve(
        langfuse_client(),
        name=prompt_name(),
        label=prompt_label(),
    )
    prepared = {
        **body,
        "messages": langfuse_prompt.compile(transcript=transcript),
    }
    prepared.setdefault("temperature", 0)
    options = completion_options(prepared)
    options["langfuse_prompt"] = langfuse_prompt
    return options


async def stream_events(completion: Any) -> AsyncIterator[str]:
    async for chunk in completion:
        yield f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"
    yield "data: [DONE]\n\n"


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
async def models():
    try:
        response = await client().models.list()
    except Exception as error:
        return upstream_error(error)
    return Response(
        content=response.model_dump_json(exclude_none=True),
        media_type="application/json",
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except Exception:
        return invalid_messages()
    transcript = raw_transcript(body)
    if transcript is None:
        return invalid_messages()

    try:
        options = await asyncio.to_thread(prepare_completion, body, transcript)
    except Exception as error:
        return openai_error(
            503,
            message=f"Langfuse prompt is unavailable: {type(error).__name__}",
            error_type="prompt_service_error",
            code="prompt_unavailable",
        )

    try:
        completion = await client().chat.completions.create(**options)
    except Exception as error:
        return upstream_error(error)

    if options.get("stream") is True:
        return StreamingResponse(stream_events(completion), media_type="text/event-stream")
    return Response(
        content=completion.model_dump_json(exclude_none=True),
        media_type="application/json",
    )
