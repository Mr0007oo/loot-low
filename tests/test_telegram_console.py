from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts.telegram_console import TelegramConsole


class FakeTelegramApi:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def request(self, method: str, payload: dict[str, Any]) -> Any:
        self.requests.append((method, payload))
        return True


class TelegramConsoleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.fifo = root / "console.fifo"
        os.mkfifo(self.fifo)
        self.stop_file = root / "stop.request"
        self.api = FakeTelegramApi()
        self.console = TelegramConsole(
            api=self.api,  # type: ignore[arg-type]
            admin_chat_id="123456789",
            console_fifo=self.fifo,
            stop_file=self.stop_file,
        )

    def make_update(
        self,
        text: str,
        *,
        chat_id: int = 123456789,
        chat_type: str = "private",
    ) -> dict[str, Any]:
        return {
            "message": {
                "chat": {"id": chat_id, "type": chat_type},
                "text": text,
            }
        }

    def test_admin_command_is_written_as_one_fifo_line(self) -> None:
        reader = os.open(self.fifo, os.O_RDWR | os.O_NONBLOCK)
        try:
            self.assertFalse(self.console.process_update(self.make_update("/cmd say hello")))
            self.assertEqual(os.read(reader, 128), b"say hello\n")
        finally:
            os.close(reader)
        self.assertIn(
            ("sendMessage", {"chat_id": "123456789", "text": "Command sent to the server console."}),
            self.api.requests,
        )

    def test_non_admin_or_group_chat_is_ignored(self) -> None:
        self.assertFalse(
            self.console.process_update(self.make_update("/cmd stop", chat_id=1))
        )
        self.assertFalse(
            self.console.process_update(
                self.make_update("/cmd stop", chat_type="group")
            )
        )
        self.assertEqual(self.api.requests, [])
        self.assertFalse(self.stop_file.exists())

    def test_multiline_command_is_rejected(self) -> None:
        reader = os.open(self.fifo, os.O_RDWR | os.O_NONBLOCK)
        try:
            self.assertFalse(
                self.console.process_update(self.make_update("/cmd say hello\nstop"))
            )
            with self.assertRaises(BlockingIOError):
                os.read(reader, 128)
        finally:
            os.close(reader)
        self.assertIn("Commands must be a single line.", self.api.requests[-1][1]["text"])

    def test_stop_sets_marker_without_sending_server_stop_command(self) -> None:
        self.assertTrue(self.console.process_update(self.make_update("/stop")))
        self.assertTrue(self.stop_file.is_file())
        self.assertEqual(self.stop_file.stat().st_mode & 0o777, 0o600)
        self.assertIn("Graceful server shutdown requested.", self.api.requests[-1][1]["text"])


if __name__ == "__main__":
    unittest.main()