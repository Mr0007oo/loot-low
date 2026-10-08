#!/usr/bin/env python3
"""Relay admin-only Telegram messages to the local Bedrock console FIFO."""

from __future__ import annotations

import json
import os
import stat
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


POLL_TIMEOUT_SECONDS = 30
MAX_COMMAND_BYTES = 1_024


class TelegramApiError(RuntimeError):
    pass


class TelegramApi:
    def __init__(self, token: str) -> None:
        self._url = f"https://api.telegram.org/bot{token}/"

    def request(self, method: str, payload: dict[str, Any]) -> Any:
        request = urllib.request.Request(
            self._url + method,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=POLL_TIMEOUT_SECONDS + 10,
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                body = {}
            description = body.get("description") if isinstance(body, dict) else None
            detail = description if isinstance(description, str) else str(exc.reason)
            detail = " ".join(detail.split())[:240]
            raise TelegramApiError(
                f"Telegram API {method} returned HTTP {exc.code}: {detail}"
            ) from None
        except (
            OSError,
            TimeoutError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise TelegramApiError(
                f"Telegram API {method} request failed ({type(exc).__name__})"
            ) from None

        if not isinstance(result, dict) or result.get("ok") is not True:
            if isinstance(result, dict):
                error_code = result.get("error_code", "unknown")
                description = result.get("description", "request rejected")
                if not isinstance(description, str):
                    description = "request rejected"
                description = " ".join(description.split())[:240]
                raise TelegramApiError(
                    f"Telegram API {method} returned error {error_code}: {description}"
                )
            raise TelegramApiError(f"Telegram API {method} returned an invalid response")
        return result.get("result")


class TelegramConsole:
    def __init__(
        self,
        *,
        api: TelegramApi,
        admin_chat_id: str,
        console_fifo: Path,
        stop_file: Path,
    ) -> None:
        self.api = api
        self.admin_chat_id = admin_chat_id
        self.console_fifo = console_fifo
        self.stop_file = stop_file
        self.offset: int | None = None

    def run(self) -> None:
        self.api.request("getMe", {})
        pending = self.api.request(
            "getUpdates",
            {"timeout": 0, "allowed_updates": ["message"]},
        )
        if isinstance(pending, list):
            update_ids = [
                update["update_id"]
                for update in pending
                if isinstance(update, dict) and isinstance(update.get("update_id"), int)
            ]
            if update_ids:
                self.offset = max(update_ids) + 1

        self._reply("Telegram console is online. Use /help for commands.")
        while True:
            poll_payload: dict[str, Any] = {
                "timeout": POLL_TIMEOUT_SECONDS,
                "allowed_updates": ["message"],
            }
            if self.offset is not None:
                poll_payload["offset"] = self.offset
            try:
                updates = self.api.request("getUpdates", poll_payload)
            except TelegramApiError as exc:
                print(
                    f"Telegram polling failed: {exc}; retrying shortly.",
                    file=sys.stderr,
                )
                time.sleep(5)
                continue
            if not isinstance(updates, list):
                raise TelegramApiError("Telegram returned an invalid updates response")
            for update in updates:
                if not isinstance(update, dict):
                    continue
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    self.offset = update_id + 1
                try:
                    if self.process_update(update):
                        return
                except TelegramApiError:
                    print("Could not send a Telegram reply for an update.", file=sys.stderr)

    def process_update(self, update: dict[str, Any]) -> bool:
        message = update.get("message")
        if not isinstance(message, dict):
            return False
        chat = message.get("chat")
        if (
            not isinstance(chat, dict)
            or chat.get("type") != "private"
            or str(chat.get("id")) != self.admin_chat_id
        ):
            return False

        text = message.get("text")
        if not isinstance(text, str):
            return False
        command_text = text.strip()
        if not command_text.startswith("/"):
            return False

        head, _, arguments = command_text.partition(" ")
        command = head[1:].split("@", 1)[0].casefold()
        arguments = arguments.strip()

        if command in ("start", "help"):
            self._reply("Use /cmd <server command>, /status, or /stop.")
            return False
        if command == "status":
            self._reply("The server control workflow is running.")
            return False
        if command == "stop":
            if arguments:
                self._reply("Usage: /stop")
                return False
            return self._request_stop()
        if command != "cmd":
            self._reply("Unknown command. Use /help.")
            return False
        if not arguments:
            self._reply("Usage: /cmd <server command>")
            return False
        if any(character in arguments for character in "\0\r\n"):
            self._reply("Commands must be a single line.")
            return False
        encoded_command = arguments.encode("utf-8")
        if len(encoded_command) > MAX_COMMAND_BYTES:
            self._reply("Command is too long.")
            return False
        if arguments.lstrip("/").split(maxsplit=1)[0].casefold() in {
            "stop",
            "shutdown",
            "quit",
        }:
            return self._request_stop()

        try:
            self._write_console(encoded_command + b"\n")
        except OSError:
            self._reply("The server console is unavailable.")
            return False
        self._reply("Command sent to the server console.")
        return False

    def _write_console(self, data: bytes) -> None:
        if not stat.S_ISFIFO(self.console_fifo.stat().st_mode):
            raise OSError("Server console path is not a FIFO")
        descriptor = os.open(
            self.console_fifo,
            os.O_WRONLY | os.O_NONBLOCK,
        )
        try:
            os.write(descriptor, data)
        finally:
            os.close(descriptor)

    def _request_stop(self) -> bool:
        try:
            self._reply("Graceful server shutdown requested.")
            self.stop_file.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(
                    self.stop_file,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        except OSError:
            self._reply("Could not request server shutdown.")
            return False
        return True

    def _reply(self, text: str) -> None:
        self.api.request(
            "sendMessage",
            {"chat_id": self.admin_chat_id, "text": text},
        )


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    admin_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    fifo_value = os.environ.get("SERVER_CONSOLE_FIFO", "")
    stop_value = os.environ.get("SERVER_STOP_FILE", "")
    if not token or not admin_chat_id or not fifo_value or not stop_value:
        print(
            "TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SERVER_CONSOLE_FIFO, and "
            "SERVER_STOP_FILE are required.",
            file=sys.stderr,
        )
        return 2
    if not admin_chat_id.lstrip("-").isdigit():
        print("TELEGRAM_CHAT_ID must be a numeric private chat ID.", file=sys.stderr)
        return 2

    console = TelegramConsole(
        api=TelegramApi(token),
        admin_chat_id=admin_chat_id,
        console_fifo=Path(fifo_value),
        stop_file=Path(stop_value),
    )
    try:
        console.run()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(
            f"Telegram console stopped ({type(exc).__name__}).",
            file=sys.stderr,
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())