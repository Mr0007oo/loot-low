#!/usr/bin/env python3
"""RCON connection helper with bounded startup retries."""

from __future__ import annotations

import os
import sys
import time

from mcrcon import MCRcon


def rcon_command(command: str) -> str:
    password = os.environ.get("RCON_PASSWORD", "")
    if not password:
        raise RuntimeError("RCON_PASSWORD is required for RCON access")

    port = int(os.environ.get("RCON_PORT", "25575"))
    timeout = int(os.environ.get("RCON_CONNECT_TIMEOUT", "60"))
    deadline = time.monotonic() + timeout
    delay = 5
    last_error: Exception | None = None

    while True:
        try:
            with MCRcon("127.0.0.1", password, port=port) as connection:
                return connection.command(command)
        except Exception as exc:
            last_error = exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            wait_seconds = min(delay, remaining)
            print(
                f"RCON unavailable ({exc}); retrying in {wait_seconds:.0f}s "
                f"for up to {remaining:.0f}s.",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(wait_seconds)
            delay = min(delay * 2, 20)

    raise RuntimeError(f"RCON did not become available within {timeout}s: {last_error}") from last_error
