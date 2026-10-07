#!/usr/bin/env python3
"""Apply the runtime RCON secret to a Bedrock server.properties file."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path


MIN_PASSWORD_LENGTH = 32
DEFAULT_RCON_PORT = 25575
RCON_KEYS = ("enable-rcon", "rcon.port", "rcon.password")


def configure_rcon(properties_file: Path, password: str, port: int) -> None:
    if len(password) < MIN_PASSWORD_LENGTH or "\n" in password or "\r" in password:
        raise ValueError(
            f"RCON_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters "
            "and contain no line breaks."
        )
    if not 1 <= port <= 65535:
        raise ValueError("RCON_PORT must be between 1 and 65535.")

    values = {
        "enable-rcon": "true",
        "rcon.port": str(port),
        "rcon.password": password,
    }
    lines = properties_file.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    found: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in values:
                if key not in found:
                    updated.append(f"{key}={values[key]}")
                    found.add(key)
                continue
        updated.append(line)
    updated.extend(f"{key}={values[key]}" for key in RCON_KEYS if key not in found)
    content = "\n".join(updated) + "\n"

    original_mode = properties_file.stat().st_mode & 0o777
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=properties_file.parent,
            prefix=f".{properties_file.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
        temporary_path.chmod(original_mode & 0o600)
        os.replace(temporary_path, properties_file)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("properties_file", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()

    password = os.environ.get("RCON_PASSWORD")
    if password is None:
        parser.error("RCON_PASSWORD environment variable is required.")
    try:
        port = args.port
        if port is None:
            port = int(os.environ.get("RCON_PORT", DEFAULT_RCON_PORT))
    except ValueError:
        parser.error("RCON_PORT must be an integer.")
    try:
        configure_rcon(args.properties_file, password, port)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
