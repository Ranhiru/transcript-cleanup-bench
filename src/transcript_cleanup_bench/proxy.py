from __future__ import annotations

import os
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from langfuse import Langfuse
from langfuse.openai import openai

from .prompts import prompt_label, prompt_name, resolve

REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / ".env")

app = FastAPI(title="OpenAI-compatible tracing proxy")

EXTRA_BODY_OPTIONS = {"top_k", "min_p", "repetition_penalty", "chat_template_kwargs"}


def api_host() -> str:
    host = os.environ["OPENAI_API_HOST"]
    if os.environ.get("CONTAINERIZED") == "true":
        host = host.replace("://localhost", "://host.docker.internal")
        host = host.replace("://127.0.0.1", "://host.docker.internal")
    return host


def client() -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(
        base_url=api_host(),
        api_key=os.environ["OPENAI_API_KEY"],
    )


def langfuse_client() -> Langfuse:
    return Langfuse(
        public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
        base_url=os.environ.get("LANGFUSE_BASE_URL", "http://localhost:4001"),
        additional_headers={"x-langfuse-ingestion-version": "4"},
    )


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


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
async def models():
    upstream = client()
    try:
        response = await upstream.models.list()
        return Response(
            content=response.model_dump_json(exclude_none=True),
            media_type="application/json",
        )
    except Exception as error:
        return upstream_error(error)
    finally:
        await upstream.close()


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
        langfuse_prompt = resolve(
            langfuse_client(),
            name=prompt_name(),
            label=prompt_label(),
        )
        compiled_messages = langfuse_prompt.compile(transcript=transcript)
    except Exception as error:
        return openai_error(
            503,
            message=f"Langfuse prompt is unavailable: {type(error).__name__}",
            error_type="prompt_service_error",
            code="prompt_unavailable",
        )

    body["messages"] = compiled_messages
    options = completion_options(body)
    options["langfuse_prompt"] = langfuse_prompt
    upstream = client()
    try:
        completion = await upstream.chat.completions.create(**options)
    except Exception as error:
        await upstream.close()
        return upstream_error(error)

    if options.get("stream") is True:
        async def events() -> AsyncIterator[str]:
            try:
                async for chunk in completion:
                    yield f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                await upstream.close()

        return StreamingResponse(events(), media_type="text/event-stream")

    try:
        content = completion.model_dump_json(exclude_none=True)
        return Response(content=content, media_type="application/json")
    finally:
        await upstream.close()
