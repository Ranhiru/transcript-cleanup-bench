#!/usr/bin/env python3
from __future__ import annotations

import time
import urllib.error
import urllib.request


def main() -> None:
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:4001/api/public/health", timeout=2) as response:
                if response.status == 200:
                    print("Langfuse is ready")
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(2)
    raise SystemExit("Langfuse did not become ready within five minutes")


if __name__ == "__main__":
    main()
