from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from langfuse import Langfuse

REPO = Path(__file__).resolve().parents[2]
DATASET_NAME = "evaluation/transcript-cleanup"

# Sampler settings the OpenAI-compatible schema rejects natively.
EXTRA_BODY_OPTIONS = ("top_k", "min_p", "repetition_penalty", "chat_template_kwargs")


def load_env() -> None:
    load_dotenv(REPO / ".env")


def langfuse_client() -> Langfuse:
    return Langfuse(
        public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
        base_url=os.environ.get("LANGFUSE_BASE_URL", "http://localhost:4001"),
        additional_headers={"x-langfuse-ingestion-version": "4"},
    )
