from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from scripts.configure_rcon import configure_rcon


class ConfigureRconTests(unittest.TestCase):
    def test_sets_password_port_and_enabled_flag_without_touching_other_properties(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            properties_file = Path(temporary_directory) / "server.properties"
            properties_file.write_text(
                "server-port=19132\n"
                "enable-rcon=false\n"
                "rcon.port=25575\n"
                "rcon.password=old-value\n",
                encoding="utf-8",
            )

            configure_rcon(properties_file, "a" * 32, 25576)

            properties = properties_file.read_text(encoding="utf-8").splitlines()
            self.assertIn("server-port=19132", properties)
            self.assertIn("enable-rcon=true", properties)
            self.assertIn("rcon.port=25576", properties)
            self.assertIn(f"rcon.password={'a' * 32}", properties)
            self.assertEqual(sum(line.startswith("rcon.") for line in properties), 2)
            mode = properties_file.stat().st_mode
            self.assertEqual(mode & stat.S_IRWXG, 0)
            self.assertEqual(mode & stat.S_IRWXO, 0)

    def test_adds_missing_rcon_properties(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            properties_file = Path(temporary_directory) / "server.properties"
            properties_file.write_text("server-port=19132\n", encoding="utf-8")

            configure_rcon(properties_file, "b" * 32, 25575)

            properties = properties_file.read_text(encoding="utf-8").splitlines()
            self.assertIn("enable-rcon=true", properties)
            self.assertIn("rcon.port=25575", properties)
            self.assertIn(f"rcon.password={'b' * 32}", properties)

    def test_rejects_weak_password_without_changing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            properties_file = Path(temporary_directory) / "server.properties"
            original = "server-port=19132\n"
            properties_file.write_text(original, encoding="utf-8")

            with self.assertRaises(ValueError):
                configure_rcon(properties_file, "short", 25575)

            self.assertEqual(properties_file.read_text(encoding="utf-8"), original)

    def test_rejects_invalid_port(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            properties_file = Path(temporary_directory) / "server.properties"
            properties_file.write_text("server-port=19132\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                configure_rcon(properties_file, "c" * 32, 65536)


if __name__ == "__main__":
    unittest.main()
