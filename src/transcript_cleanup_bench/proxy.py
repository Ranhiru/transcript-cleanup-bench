from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from langfuse import Langfuse

from . import GENERATION_NAME

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "authorization",
}
SENSITIVE_PARTS = ("authorization", "password", "secret", "token", "api_key", "apikey")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(part in key.lower() for part in SENSITIVE_PARTS) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def filtered_headers(headers: httpx.Headers, *, response: bool = False) -> dict[str, str]:
    blocked = set(HOP_BY_HOP)
    connection = headers.get("connection")
    if connection:
        blocked.update(part.strip().lower() for part in connection.split(","))
    return {key: value for key, value in headers.items() if key.lower() not in blocked}


def request_headers(headers: httpx.Headers) -> dict[str, str]:
    outgoing = filtered_headers(headers)
    api_key = os.environ.get("OMLX_API_KEY")
    if api_key:
        outgoing["authorization"] = f"Bearer {api_key}"
    return outgoing


def response_details(payload: Any) -> tuple[Any, str | None, dict[str, int] | None]:
    if not isinstance(payload, dict):
        return payload, None, None
    choices = payload.get("choices") or []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    output = message.get("content", choice.get("text"))
    usage = payload.get("usage")
    return output, choice.get("finish_reason"), usage if isinstance(usage, dict) else None


class StreamDetails:
    def __init__(self) -> None:
        self.buffer = b""
        self.parts: list[str] = []
        self.finish_reason: str | None = None
        self.usage: dict[str, int] | None = None
        self.first_token_at: float | None = None

    def feed(self, chunk: bytes, now: float) -> None:
        self.buffer += chunk
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            line = line.rstrip(b"\r")
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if not data or data == b"[DONE]":
                continue
            try:
                payload = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(payload.get("usage"), dict):
                self.usage = payload["usage"]
            for choice in payload.get("choices") or []:
                if choice.get("finish_reason") is not None:
                    self.finish_reason = choice["finish_reason"]
                delta = choice.get("delta") or {}
                content = delta.get("content") if isinstance(delta, dict) else None
                if isinstance(content, str) and content:
                    if self.first_token_at is None:
                        self.first_token_at = now
                    self.parts.append(content)


class TraceGeneration:
    def __init__(self, body: dict[str, Any]) -> None:
        self.observation = None
        self.started = time.monotonic()
        self.wall_started = time.time()
        try:
            langfuse = trace_client()
            parameters = {key: value for key, value in body.items() if key not in {"messages", "model"}}
            self.observation = langfuse.start_observation(
                name=GENERATION_NAME,
                as_type="generation",
                input=redact(body.get("messages")),
                model=str(body.get("model", "")),
                model_parameters=redact(parameters),
            )
        except Exception:
            self.observation = None

    def finish(
        self,
        *,
        output: Any = None,
        finish_reason: str | None = None,
        usage: dict[str, int] | None = None,
        first_token_at: float | None = None,
        error: str | None = None,
        cancelled: bool = False,
    ) -> None:
        if self.observation is None:
            return
        try:
            elapsed_ms = round((time.monotonic() - self.started) * 1000, 3)
            metadata: dict[str, Any] = {
                "latency_ms": elapsed_ms,
                "finish_reason": finish_reason,
                "cancelled": cancelled,
            }
            if first_token_at is not None:
                metadata["time_to_first_token_ms"] = round((first_token_at - self.started) * 1000, 3)
            level = "ERROR" if error else "DEFAULT"
            self.observation.update(
                output=redact(output),
                usage_details=usage,
                completion_start_time=(
                    datetime.fromtimestamp(
                        self.wall_started + first_token_at - self.started,
                        UTC,
                    )
                    if first_token_at is not None
                    else None
                ),
                metadata=metadata,
                level=level,
                status_message=error,
            )
            self.observation.end()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.upstream = httpx.AsyncClient(timeout=None, follow_redirects=False)
    yield
    await app.state.upstream.aclose()
    global _trace_client
    if _trace_client is not None:
        try:
            _trace_client.shutdown()
        except Exception:
            pass
        _trace_client = None


app = FastAPI(title="oMLX tracing proxy", lifespan=lifespan)

_trace_client: Langfuse | None = None


def trace_client() -> Langfuse:
    global _trace_client
    if _trace_client is None:
        _trace_client = Langfuse(
            public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
            base_url=os.environ.get("LANGFUSE_BASE_URL", "http://langfuse-web:3000"),
            additional_headers={"x-langfuse-ingestion-version": "4"},
        )
    return _trace_client


def upstream_url(path: str) -> str:
    return f"{os.environ.get('OMLX_BASE_URL', 'http://host.docker.internal:8000/v1').rstrip('/')}/{path}"


async def send_upstream(request: Request, path: str, body: bytes = b"") -> httpx.Response:
    upstream: httpx.AsyncClient = request.app.state.upstream
    outgoing = upstream.build_request(
        request.method,
        upstream_url(path),
        headers=request_headers(request.headers),
        content=body,
    )
    return await upstream.send(outgoing, stream=True)


def unavailable(error: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "message": f"oMLX is unavailable: {type(error).__name__}",
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
async def models(request: Request) -> Response:
    try:
        response = await send_upstream(request, "models")
    except httpx.RequestError as error:
        return unavailable(error)
    try:
        content = await response.aread()
    except httpx.RequestError as error:
        await response.aclose()
        return unavailable(error)
    await response.aclose()
    return Response(
        content=content,
        status_code=response.status_code,
        headers=filtered_headers(response.headers, response=True),
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    raw = await request.body()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        body = {}
    generation = TraceGeneration(body if isinstance(body, dict) else {})
    try:
        response = await send_upstream(request, "chat/completions", raw)
    except httpx.RequestError as error:
        generation.finish(error=str(error))
        return unavailable(error)

    headers = filtered_headers(response.headers, response=True)
    if isinstance(body, dict) and body.get("stream") is True:
        details = StreamDetails()

        async def chunks() -> AsyncIterator[bytes]:
            error: str | None = None
            cancelled = False
            try:
                async for chunk in response.aiter_raw():
                    details.feed(chunk, time.monotonic())
                    yield chunk
            except asyncio.CancelledError:
                cancelled = True
                raise
            except Exception as stream_error:
                error = str(stream_error)
                raise
            finally:
                await response.aclose()
                generation.finish(
                    output="".join(details.parts),
                    finish_reason=details.finish_reason,
                    usage=details.usage,
                    first_token_at=details.first_token_at,
                    error=error,
                    cancelled=cancelled,
                )

        return StreamingResponse(chunks(), status_code=response.status_code, headers=headers)

    try:
        content = await response.aread()
    except httpx.RequestError as error:
        await response.aclose()
        generation.finish(error=str(error))
        return unavailable(error)
    await response.aclose()
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        payload = content.decode(errors="replace")
    output, finish_reason, usage = response_details(payload)
    if output is None:
        output = payload
    generation.finish(
        output=output,
        finish_reason=finish_reason,
        usage=usage,
        error=None if response.is_success else f"upstream status {response.status_code}",
    )
    return Response(content=content, status_code=response.status_code, headers=headers)
