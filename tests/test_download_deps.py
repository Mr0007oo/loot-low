from __future__ import annotations

import hashlib
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

from scripts import download_deps


class BedrockRuntimeTests(unittest.TestCase):
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
        manifest = (
            Path(__file__).parents[1]
            / "server"
            / "plugins"
            / "lootlow_bedrock"
            / "pyproject.toml"
        )
        project = tomllib.loads(manifest.read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["dependencies"], ["endstone==0.11.2"])
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


if __name__ == "__main__":
    unittest.main()
