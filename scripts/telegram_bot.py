#!/usr/bin/env python3
"""Long-poll Telegram for authorized Minecraft RCON commands."""

from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from mcrcon import MCRcon

ROOT = Path(__file__).resolve().parents[1]
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
AUTHORIZED_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
RCON_PASSWORD = os.environ.get("RCON_PASSWORD", "")
RCON_PORT = int(os.environ.get("RCON_PORT", "25575"))
API_URL = f"https://api.telegram.org/bot{TOKEN}"


def validate_environment() -> None:
    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", TOKEN),
            ("TELEGRAM_CHAT_ID", AUTHORIZED_CHAT_ID),
            ("RCON_PASSWORD", RCON_PASSWORD),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


def rcon_command(command: str) -> str:
    with MCRcon("127.0.0.1", RCON_PASSWORD, port=RCON_PORT) as connection:
        return connection.command(command)


def send_message(chat_id: int | str, text: str, *, html_format: bool = False) -> None:
    data = {"chat_id": chat_id, "text": text[:4000]}
    if html_format:
        data["parse_mode"] = "HTML"
    response = requests.post(
        f"{API_URL}/sendMessage",
        data=data,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram rejected the reply")


def code_block(text: str) -> str:
    safe_text = html.escape(text.strip())
    if len(safe_text) > 3500:
        truncated = safe_text[-3450:]
        last_ampersand = truncated.rfind("&")
        last_semicolon = truncated.rfind(";")
        if last_ampersand > last_semicolon:
            truncated = truncated[:last_ampersand]
        safe_text = "... (truncated)\n" + truncated
    return f"<pre>{safe_text or 'No output'}</pre>"


def process_metrics() -> str:
    result = subprocess.run(
        ["pgrep", "-f", "[j]ava.*-jar paper[.]jar"],
        capture_output=True,
        text=True,
        check=False,
    )
    pid = result.stdout.splitlines()[0] if result.returncode == 0 and result.stdout else ""
    if not pid:
        return "Paper JVM: not running"
    usage = subprocess.run(
        ["ps", "-o", "%cpu=,rss=", "-p", pid],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if not usage:
        return f"Paper JVM PID {pid}: usage unavailable"
    cpu, rss_kib = usage.split(maxsplit=1)
    return f"Paper JVM PID {pid}: CPU {cpu}%, RAM {int(rss_kib) // 1024} MiB RSS"


def persist_world() -> str:
    interpreter = Path(sys.executable)
    helper = ROOT / "scripts" / "persist_world.py"
    result = subprocess.run(
        [str(interpreter), str(helper)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise RuntimeError(output or f"Persistence helper exited with {result.returncode}")
    return output or "World save and Git push completed."


def handle_message(message: dict) -> None:
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    if chat_id is None or str(chat_id) != AUTHORIZED_CHAT_ID:
        return

    text = message.get("text", "").strip()
    if not text.startswith("/"):
        return
    command_text, _, arguments = text.partition(" ")
    command = command_text.split("@", 1)[0].lower()
    arguments = arguments.strip()

    try:
        if command in {"/help", "/start"}:
            reply = (
                "/logs - last 25 server log lines\n"
                "/op <player> - grant operator status\n"
                "/cmd <command> - run a console command\n"
                "/save - save and push world data\n"
                "/status - players and JVM CPU/RAM\n"
                "/help - show this message"
            )
        elif command == "/logs":
            log_path = ROOT / "server" / "logs" / "latest.log"
            if not log_path.is_file():
                reply = "Server log is not available yet."
            else:
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
                reply = code_block("\n".join(lines))
        elif command == "/op":
            if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", arguments):
                reply = "Usage: /op <player>"
            else:
                reply = code_block(rcon_command(f"op {arguments}"))
        elif command == "/cmd":
            if not arguments:
                reply = "Usage: /cmd <command>"
            else:
                reply = code_block(rcon_command(arguments))
        elif command == "/save":
            reply = code_block(persist_world())
        elif command == "/status":
            players = rcon_command("list")
            reply = f"{players or 'Player list unavailable'}\n{process_metrics()}"
        else:
            return
        send_message(chat_id, reply, html_format=command in {"/logs", "/op", "/cmd", "/save"})
    except Exception as exc:
        send_message(chat_id, f"Command failed: {str(exc)[:3500]}")


def main() -> int:
    try:
        validate_environment()
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    offset = 0
    print("Telegram RCON bot started; only the configured chat ID is authorized.", flush=True)
    while True:
        try:
            response = requests.get(
                f"{API_URL}/getUpdates",
                params={"offset": offset, "timeout": 30, "allowed_updates": '["message"]'},
                timeout=40,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                raise RuntimeError("Telegram getUpdates request was rejected")
            for update in payload.get("result", []):
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                message = update.get("message")
                if isinstance(message, dict):
                    handle_message(message)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"Telegram polling error: {exc}", file=sys.stderr, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
