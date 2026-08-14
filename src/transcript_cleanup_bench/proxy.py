from __future__ import annotations

import os
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from langfuse.openai import openai

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


def completion_options(body: dict[str, Any]) -> dict[str, Any]:
    options = {key: value for key, value in body.items() if key not in EXTRA_BODY_OPTIONS}
    extensions = {key: body[key] for key in EXTRA_BODY_OPTIONS if key in body}
    if extensions:
        options["extra_body"] = {**options.get("extra_body", {}), **extensions}
    return options


def error_response(error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "message": f"OpenAI-compatible API is unavailable: {type(error).__name__}",
                "type": "upstream_connection_error",
                "param": None,
                "code": "upstream_unavailable",
            }
        },
    )


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
        return error_response(error)
    finally:
        await upstream.close()


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    options = completion_options(await request.json())
    upstream = client()
    try:
        completion = await upstream.chat.completions.create(**options)
    except Exception as error:
        await upstream.close()
        return error_response(error)

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
