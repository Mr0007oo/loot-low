from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import time
import tomllib
import unittest
import zipfile
from pathlib import Path

from scripts import download_deps


class BedrockRuntimeTests(unittest.TestCase):
    def test_server_uses_stable_bedrock_configuration_and_server_utils_plugin(self) -> None:
        root = Path(__file__).parents[1]
        properties = {}
        for line in (root / "server" / "server.properties").read_text(
            encoding="utf-8"
        ).splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                properties[key.strip()] = value.strip()
        self.assertEqual(
            {
                key: properties.get(key)
                for key in (
                    "server-port",
                    "server-ip",
                    "allow-outdated-client",
                    "emit-server-telemetry",
                )
            },
            {
                "server-port": "19132",
                "server-ip": "0.0.0.0",
                "allow-outdated-client": "true",
                "emit-server-telemetry": "false",
            },
        )

        launcher = (root / "server" / "start.sh").read_text(encoding="utf-8")
        self.assertIn("pip uninstall", launcher)
        self.assertEqual(launcher.count("pip install"), 4)
        self.assertIn('pip install --disable-pip-version-check "$wheel"', launcher)
        self.assertIn('"$SERVER_DIR/plugins/server_utils"', launcher)
        self.assertIn('"$SERVER_DIR/plugins/fun_plugins"', launcher)
        self.assertIn('"$SERVER_DIR/plugins/vein_miner"', launcher)
        self.assertIn("exec {server_stdin_fd}< <(tail -f /dev/null)", launcher)
        self.assertIn('--no-interactive <&"$server_stdin_fd" &', launcher)
        self.assertIn("close_server_stdin", launcher)

        plugin_manifest = root / "server" / "plugins" / "server_utils" / "pyproject.toml"
        project = tomllib.loads(plugin_manifest.read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["name"], "endstone-server-utils")
        self.assertEqual(project["dependencies"], ["endstone==0.11.2"])
        self.assertEqual(
            project["entry-points"]["endstone"]["server-utils"],
            "server_utils:ServerUtilsPlugin",
        )
        plugin_source = (
            root / "server" / "plugins" / "server_utils" / "src" / "server_utils" / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn('api_version = "0.11"', plugin_source)
        self.assertIn('"serverinfo"', plugin_source)
        self.assertNotIn("@event_handler", plugin_source)

        workflow = (root / ".github" / "workflows" / "minecraft.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("push:\n    branches: [main]", workflow)
        self.assertIn("pip wheel", workflow)
        self.assertIn("Server utilities enabled.", workflow)
        self.assertIn("fun_plugins", workflow)
        self.assertIn("Fun command utilities enabled.", workflow)

        fun_manifest = root / "server" / "plugins" / "fun_plugins" / "pyproject.toml"
        fun_project = tomllib.loads(fun_manifest.read_text(encoding="utf-8"))["project"]
        self.assertEqual(fun_project["name"], "endstone-fun-plugins")
        self.assertEqual(fun_project["dependencies"], ["endstone==0.11.2"])
        self.assertEqual(
            fun_project["entry-points"]["endstone"]["fun-plugins"],
            "fun_plugins:FunPlugins",
        )
        fun_source = (
            root / "server" / "plugins" / "fun_plugins" / "src" / "fun_plugins" / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"coinflip"', fun_source)
        self.assertIn('"roll"', fun_source)
        self.assertIn('"magic8ball"', fun_source)
        self.assertIn("ROLL_MAX_SIDES = 1_000", fun_source)
        for command in ("sethome", "home", "tpa", "tpaccept", "tpdeny"):
            self.assertIn(f'        "{command}": {{', fun_source)
        self.assertIn("self.homes = {}", fun_source)
        self.assertIn("self.tpa_requests = {}", fun_source)
        self.assertIn("sender.unique_id", fun_source)
        self.assertIn("sender.location", fun_source)
        self.assertNotIn("@event_handler", fun_source)

        launcher = (root / "server" / "start.sh").read_text(encoding="utf-8")
        self.assertNotIn("server/worlds", launcher)
        self.assertNotIn("server/world/", launcher)
        persistence = (root / "scripts" / "persist_world.py").read_text(encoding="utf-8")
        self.assertNotIn('"server/worlds"', persistence)
        self.assertNotIn('"server/world/"', persistence)
        workflow = (root / ".github" / "workflows" / "minecraft.yml").read_text(
            encoding="utf-8"
        )
        workflow_paths = {line.strip() for line in workflow.splitlines()}
        self.assertNotIn("server/worlds", workflow_paths)
        self.assertNotIn("server/world/", workflow_paths)

        vein_manifest = root / "server" / "plugins" / "vein_miner" / "pyproject.toml"
        vein_project = tomllib.loads(vein_manifest.read_text(encoding="utf-8"))["project"]
        self.assertEqual(vein_project["name"], "endstone-vein-miner")
        self.assertEqual(vein_project["dependencies"], ["endstone==0.11.2"])
        self.assertEqual(
            vein_project["entry-points"]["endstone"]["vein-miner"],
            "vein_miner:VeinMinerPlugin",
        )
        vein_source = (
            root / "server" / "plugins" / "vein_miner" / "src" / "vein_miner" / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn("MAX_BLOCKS_PER_BREAK = 32", vein_source)
        self.assertIn(
            "from endstone.event import BlockBreakEvent, EventPriority, event_handler",
            vein_source,
        )
        self.assertIn("ignore_cancelled=True", vein_source)
        self.assertIn("def on_block_break(self, event: BlockBreakEvent)", vein_source)
        self.assertIn('"veinmine"', vein_source)
        self.assertIn("self.register_events(self)", vein_source)

    def make_archive(self, archive_path: Path, executable: bytes = b"pinned-bds") -> str:
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("bedrock_server", executable)
            archive.writestr("server.properties", "server-port=19132\n")
        return hashlib.sha256(archive_path.read_bytes()).hexdigest()

    def test_install_replaces_runtime_preserving_worlds_and_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            server_dir = Path(temp)
            old_runtime = server_dir / "bedrock_server"
            old_runtime.mkdir()
            (old_runtime / "bedrock_server").write_bytes(b"stale-bds")
            (old_runtime / "obsolete-runtime-file").write_text("stale", encoding="utf-8")
            (old_runtime / "worlds").mkdir()
            (old_runtime / "worlds" / "level.dat").write_bytes(b"world")
            old_plugin = old_runtime / "plugins" / "custom" / "plugin.py"
            old_plugin.parent.mkdir(parents=True)
            old_plugin.write_text("old plugin", encoding="utf-8")
            (server_dir / "allowlist.json").write_text("[]\n", encoding="utf-8")
            (server_dir / "server.properties").write_text(
                "server-port=19132\n",
                encoding="utf-8",
            )
            archive_path = server_dir / "bds.zip"
            archive_hash = self.make_archive(archive_path)

            result = download_deps.install_bds_archive(
                archive_path,
                server_dir=server_dir,
                expected_archive_sha256=archive_hash,
            )

            self.assertEqual(result, old_runtime)
            self.assertEqual((result / "bedrock_server").read_bytes(), b"pinned-bds")
            self.assertFalse((result / "obsolete-runtime-file").exists())
            self.assertFalse((result / "plugins").exists())
            self.assertEqual((result / "worlds" / "level.dat").read_bytes(), b"world")
            self.assertEqual((result / "server.properties").read_text(), "server-port=19132\n")
            self.assertEqual((result / "allowlist.json").read_text(), "[]\n")
            self.assertEqual((result / "version.txt").read_text(), "26.3\n")
            self.assertEqual(
                download_deps.verify_bds_install(
                    result,
                    expected_archive_sha256=archive_hash,
                )["bedrock_version"],
                "1.26.3.1",
            )

    def test_verifier_rejects_version_file_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            server_dir = Path(temp)
            archive_path = server_dir / "bds.zip"
            archive_hash = self.make_archive(archive_path)
            bds_dir = download_deps.install_bds_archive(
                archive_path,
                server_dir=server_dir,
                expected_archive_sha256=archive_hash,
            )
            (bds_dir / "version.txt").write_text("26.51\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "version file must contain"):
                download_deps.verify_bds_install(
                    bds_dir,
                    expected_archive_sha256=archive_hash,
                )

    def test_checksum_mismatch_does_not_replace_existing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            server_dir = Path(temp)
            old_executable = server_dir / "bedrock_server" / "bedrock_server"
            old_executable.parent.mkdir()
            old_executable.write_bytes(b"keep-me")
            archive_path = server_dir / "bds.zip"
            self.make_archive(archive_path)

            with self.assertRaisesRegex(RuntimeError, "failed SHA-256"):
                download_deps.install_bds_archive(
                    archive_path,
                    server_dir=server_dir,
                    expected_archive_sha256="0" * 64,
                )
            self.assertEqual(old_executable.read_bytes(), b"keep-me")

    def test_verifier_rejects_changed_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            server_dir = Path(temp)
            archive_path = server_dir / "bds.zip"
            archive_hash = self.make_archive(archive_path)
            bds_dir = download_deps.install_bds_archive(
                archive_path,
                server_dir=server_dir,
                expected_archive_sha256=archive_hash,
            )
            (bds_dir / "bedrock_server").write_bytes(b"replaced-binary")

            with self.assertRaisesRegex(RuntimeError, "does not match its verified manifest"):
                download_deps.verify_bds_install(
                    bds_dir,
                    expected_archive_sha256=archive_hash,
                )

    def test_archive_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            server_dir = root / "server"
            server_dir.mkdir()
            archive_path = server_dir / "bds.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("bedrock_server", b"pinned-bds")
                archive.writestr("../outside", b"not allowed")
            archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()

            with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
                download_deps.install_bds_archive(
                    archive_path,
                    server_dir=server_dir,
                    expected_archive_sha256=archive_hash,
                )
            self.assertFalse((root / "outside").exists())

    def test_pins_match_selected_supported_pair(self) -> None:
        self.assertEqual(download_deps.ENDSTONE_VERSION, "0.11.2")
        self.assertEqual(download_deps.BDS_VERSION, "1.26.3.1")
        self.assertEqual(download_deps.ENDSTONE_BDS_VERSION, "26.3")
        self.assertIn("bedrock-server-1.26.3.1.zip", download_deps.BDS_ARCHIVE_URL)
        self.assertEqual(len(download_deps.BDS_ARCHIVE_SHA256), 64)
        launcher = (
            Path(__file__).parents[1] / "server" / "start.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('!= "0.11.2 26.3"', launcher)
        self.assertIn("--yes", launcher)
        self.assertIn("--no-interactive", launcher)
        self.assertIn("download_deps.py\" --check", launcher)
        self.assertLess(
            launcher.index('download_deps.py" --check'),
            launcher.index("-m endstone \\"),
        )
        workflow = (
            Path(__file__).parents[1] / ".github" / "workflows" / "minecraft.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("ENDSTONE_VERSION: 0.11.2", workflow)
        self.assertIn("BEDROCK_CLIENT_VERSION: 1.26.2", workflow)

    def test_watchdog_restarts_clean_server_exit_and_stays_alive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frpc = root / "frpc"
            launcher = root / "start-server"
            config = root / "frpc.toml"
            frpc_log = root / "frpc.log"
            server_log = root / "server.log"
            watchdog_log = root / "watchdog.log"
            counter = root / "launch-count"
            running = root / "server-running"
            output = root / "watchdog-stdout.log"
            config.write_text("config = true\n", encoding="utf-8")
            frpc.write_text(
                "#!/usr/bin/env python3\n"
                "import signal, time\n"
                "running = True\n"
                "def stop(*_):\n"
                "    global running\n"
                "    running = False\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                "while running:\n"
                "    time.sleep(0.1)\n",
                encoding="utf-8",
            )
            launcher.write_text(
                "#!/usr/bin/env python3\n"
                "import signal, time\n"
                "from pathlib import Path\n"
                f"counter = Path({str(counter)!r})\n"
                f"running_file = Path({str(running)!r})\n"
                "count = int(counter.read_text() if counter.exists() else '0') + 1\n"
                "counter.write_text(str(count))\n"
                "if count == 1:\n"
                "    raise SystemExit(0)\n"
                "running = True\n"
                "def stop(*_):\n"
                "    global running\n"
                "    running = False\n"
                "signal.signal(signal.SIGTERM, stop)\n"
                "running_file.touch()\n"
                "while running:\n"
                "    time.sleep(0.1)\n",
                encoding="utf-8",
            )
            frpc.chmod(0o755)
            launcher.chmod(0o755)
            env = os.environ | {
                "FRP_SERVER_IP": "127.0.0.1",
                "FRP_TOKEN": "test-token",
                "FRPC_BIN": str(frpc),
                "FRPC_CONFIG": str(config),
                "FRPC_LOG": str(frpc_log),
                "SERVER_LAUNCHER": str(launcher),
                "SERVER_LOG": str(server_log),
                "WATCHDOG_LOG": str(watchdog_log),
                "WATCHDOG_INTERVAL_SECONDS": "1",
            }
            with output.open("w", encoding="utf-8") as stdout:
                watchdog = subprocess.Popen(
                    ["bash", str(Path(__file__).parents[1] / "server" / "watchdog.sh")],
                    env=env,
                    stdout=stdout,
                    stderr=subprocess.STDOUT,
                )
                try:
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        if running.exists() and counter.exists() and counter.read_text() == "2":
                            break
                        if watchdog.poll() is not None:
                            self.fail(f"Watchdog exited unexpectedly with status {watchdog.returncode}")
                        time.sleep(0.1)
                    else:
                        self.fail("Watchdog did not restart after a clean server exit")

                    watchdog.terminate()
                    self.assertNotEqual(watchdog.wait(timeout=10), 0)
                finally:
                    if watchdog.poll() is None:
                        watchdog.terminate()
                        watchdog.wait(timeout=10)

            log_text = output.read_text(encoding="utf-8")
            self.assertIn(
                "Endstone supervisor exited with status 0; restarting in 5 seconds.",
                log_text,
            )


if __name__ == "__main__":
    unittest.main()
