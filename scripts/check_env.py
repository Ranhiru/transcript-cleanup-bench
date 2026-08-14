#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import dotenv_values

REQUIRED = {
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "OMLX_API_KEY",
    "LANGFUSE_INIT_ORG_ID",
    "LANGFUSE_INIT_PROJECT_ID",
    "LANGFUSE_INIT_PROJECT_PUBLIC_KEY",
    "LANGFUSE_INIT_PROJECT_SECRET_KEY",
    "LANGFUSE_INIT_USER_EMAIL",
    "LANGFUSE_INIT_USER_PASSWORD",
    "NEXTAUTH_SECRET",
    "SALT",
    "ENCRYPTION_KEY",
    "POSTGRES_PASSWORD",
    "CLICKHOUSE_PASSWORD",
    "REDIS_AUTH",
    "MINIO_ROOT_PASSWORD",
}


def main() -> None:
    path = Path(".env")
    if not path.exists():
        raise SystemExit("missing .env; copy .env.example and replace every change-me value")
    values = {**dotenv_values(path), **os.environ}
    missing = sorted(key for key in REQUIRED if not values.get(key))
    placeholders = sorted(key for key in REQUIRED if "change-me" in values.get(key, ""))
    if missing or placeholders:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if placeholders:
            details.append("replace placeholders: " + ", ".join(placeholders))
        raise SystemExit("invalid .env (" + "; ".join(details) + ")")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", values["ENCRYPTION_KEY"]):
        raise SystemExit("ENCRYPTION_KEY must contain exactly 64 hexadecimal characters")
    if values["LANGFUSE_PUBLIC_KEY"] != values["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"]:
        raise SystemExit("LANGFUSE_PUBLIC_KEY must match LANGFUSE_INIT_PROJECT_PUBLIC_KEY")
    if values["LANGFUSE_SECRET_KEY"] != values["LANGFUSE_INIT_PROJECT_SECRET_KEY"]:
        raise SystemExit("LANGFUSE_SECRET_KEY must match LANGFUSE_INIT_PROJECT_SECRET_KEY")
    print(".env is valid")


if __name__ == "__main__":
    main()
