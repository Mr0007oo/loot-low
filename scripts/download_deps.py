#!/usr/bin/env python3
"""Download and verify the pinned Endstone and native Bedrock runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
BDS_DIR = SERVER_DIR / "bedrock_server"
PLUGINS_DIR = SERVER_DIR / "plugins"
ENDSTONE_VERSION = "0.11.2"
ENDSTONE_BDS_VERSION = "26.3"
ENDSTONE_WHEEL_NAME = (
    "endstone-0.11.2-cp313-cp313-manylinux_2_31_x86_64.whl"
)
ENDSTONE_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/d3/23/2f2bf4852dc39c5a61296d99291437e4c28bbb4449b601f670b4216066cd/"
    + ENDSTONE_WHEEL_NAME
)
ENDSTONE_WHEEL_SHA256 = "0897be5407570b9209da47091b479ec37df8da2f7c7d9f61daebcb509d14bf7f"
BDS_VERSION = "1.26.3.1"
BDS_ARCHIVE_URL = (
    "https://www.minecraft.net/bedrockdedicatedserver/bin-linux/"
    "bedrock-server-1.26.3.1.zip"
)
BDS_ARCHIVE_SHA256 = "1b03ac717d239d47a3f374dba673125d3f2a6a05968b5933f9e87affceb6b9c8"
USER_AGENT = "loot-low-native-bedrock-downloader/1.0"
RETRIES = 3
PRESERVED_RUNTIME_PATHS = ("worlds", "plugins", "endstone.toml")


def request(url: str) -> urllib.request.urlopen:
    if urllib.parse.urlparse(url).scheme != "https":
        raise RuntimeError(f"Refusing non-HTTPS dependency URL: {url}")
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": USER_AGENT}),
        timeout=60,
    )


def download_verified(url: str, destination: Path, expected_sha256: str) -> None:
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}.",
                suffix=".part",
                dir=destination.parent,
                delete=False,
            ) as output:
                temp_path = Path(output.name)
                with request(url) as response:
                    hasher = hashlib.sha256()
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                        hasher.update(chunk)
            if hasher.hexdigest() != expected_sha256:
                raise RuntimeError(f"{destination.name} failed SHA-256 verification")
            temp_path.replace(destination)
            return
        except (OSError, urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last_error = exc
            print(
                f"Download attempt {attempt}/{RETRIES} failed for "
                f"{destination.name}: {exc}",
                file=sys.stderr,
            )
            if attempt < RETRIES:
                time.sleep(attempt)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()
    raise RuntimeError(f"Download failed after {RETRIES} attempts: {last_error}")


def validate_endstone_wheel(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            metadata_name = next(
                (
                    name
                    for name in archive.namelist()
                    if name.endswith(".dist-info/METADATA")
                    and name.startswith("endstone-")
                ),
                None,
            )
            if not metadata_name:
                raise RuntimeError("Endstone wheel is missing distribution metadata")
            metadata = archive.read(metadata_name).decode("utf-8")
            if f"Version: {ENDSTONE_VERSION}\n" not in metadata:
                raise RuntimeError("Endstone wheel version does not match the pinned release")
            if "endstone/_python" not in "\n".join(archive.namelist()):
                raise RuntimeError("Endstone wheel is missing its native runtime module")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"Invalid Endstone wheel: {exc}") from exc


def _safe_archive_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if archive.testzip():
        raise RuntimeError("Bedrock server archive contains a corrupt ZIP member")
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in member.filename:
            raise RuntimeError(f"Unsafe path in Bedrock server archive: {member.filename}")
        if stat.S_ISLNK(member.external_attr >> 16):
            raise RuntimeError(f"Symlinks are not allowed in Bedrock archive: {member.filename}")
    return members


def _preserve_runtime_data(
    old_dir: Path | None,
    staged_dir: Path,
    server_dir: Path,
) -> None:
    for name in PRESERVED_RUNTIME_PATHS:
        if old_dir is None:
            continue
        source = old_dir / name
        if not source.exists():
            continue
        if source.is_symlink():
            raise RuntimeError(f"Refusing symlink in existing Bedrock runtime: {source}")
        destination = staged_dir / name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        elif source.is_file():
            shutil.copy2(source, destination)

    old_worlds = server_dir / "worlds"
    if not (staged_dir / "worlds").exists() and old_worlds.is_dir():
        shutil.copytree(old_worlds, staged_dir / "worlds")

    for name in ("server.properties", "permissions.json", "allowlist.json"):
        source = server_dir / name
        if source.is_file():
            shutil.copy2(source, staged_dir / name)


def verify_bds_install(
    bds_dir: Path,
    *,
    expected_archive_sha256: str = BDS_ARCHIVE_SHA256,
) -> dict[str, Any]:
    executable = bds_dir / "bedrock_server"
    version_file = bds_dir / "version.txt"
    manifest_file = bds_dir / "runtime-manifest.json"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError(f"Bedrock server executable is missing or not executable: {executable}")
    if version_file.read_text(encoding="utf-8").strip() != ENDSTONE_BDS_VERSION:
        raise RuntimeError(
            f"BDS version file must contain {ENDSTONE_BDS_VERSION} "
            f"(Endstone format for BDS {BDS_VERSION})"
        )
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("Bedrock runtime manifest is not a JSON object")
    if manifest.get("bedrock_version") != BDS_VERSION:
        raise RuntimeError(f"BDS manifest does not declare {BDS_VERSION}")
    if manifest.get("endstone_version") != ENDSTONE_VERSION:
        raise RuntimeError(f"BDS manifest does not match Endstone {ENDSTONE_VERSION}")
    if manifest.get("archive_sha256") != expected_archive_sha256:
        raise RuntimeError("BDS manifest archive digest does not match the pinned archive")
    hasher = hashlib.sha256()
    with executable.open("rb") as binary:
        while chunk := binary.read(1024 * 1024):
            hasher.update(chunk)
    if manifest.get("executable_sha256") != hasher.hexdigest():
        raise RuntimeError("Bedrock server executable does not match its verified manifest")
    return manifest


def install_bds_archive(
    archive_path: Path,
    *,
    server_dir: Path = SERVER_DIR,
    expected_archive_sha256: str = BDS_ARCHIVE_SHA256,
) -> Path:
    bds_dir = server_dir / "bedrock_server"
    hasher = hashlib.sha256()
    with archive_path.open("rb") as archive_file:
        while chunk := archive_file.read(1024 * 1024):
            hasher.update(chunk)
    if hasher.hexdigest() != expected_archive_sha256:
        raise RuntimeError("Bedrock server archive failed SHA-256 verification")

    with tempfile.TemporaryDirectory(prefix=".bedrock-install-", dir=server_dir) as temp:
        temp_dir = Path(temp)
        staged_dir = temp_dir / "runtime"
        staged_dir.mkdir()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = _safe_archive_members(archive)
                if not any(PurePosixPath(member.filename).name == "bedrock_server" for member in members):
                    raise RuntimeError("Bedrock archive does not contain the Linux server executable")
                archive.extractall(staged_dir)
        except (OSError, zipfile.BadZipFile) as exc:
            raise RuntimeError(f"Could not extract Bedrock server archive: {exc}") from exc

        executable = staged_dir / "bedrock_server"
        if not executable.is_file():
            raise RuntimeError("Bedrock archive executable is not at the expected archive root")
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        old_dir = bds_dir
        if old_dir.exists():
            if old_dir.is_symlink() or not old_dir.is_dir():
                raise RuntimeError(f"Refusing to replace unexpected Bedrock runtime path: {old_dir}")
            _preserve_runtime_data(old_dir, staged_dir, server_dir)
        else:
            _preserve_runtime_data(None, staged_dir, server_dir)

        (staged_dir / "version.txt").write_text(
            f"{ENDSTONE_BDS_VERSION}\n",
            encoding="utf-8",
        )
        executable_hasher = hashlib.sha256()
        with executable.open("rb") as binary:
            while chunk := binary.read(1024 * 1024):
                executable_hasher.update(chunk)
        manifest = {
            "bedrock_version": BDS_VERSION,
            "endstone_version": ENDSTONE_VERSION,
            "archive_sha256": expected_archive_sha256,
            "executable_sha256": executable_hasher.hexdigest(),
        }
        (staged_dir / "runtime-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )

        backup_dir = server_dir / ".bedrock_server.previous"
        if backup_dir.exists():
            if backup_dir.is_symlink() or not backup_dir.is_dir():
                raise RuntimeError(f"Refusing to remove unexpected backup path: {backup_dir}")
            shutil.rmtree(backup_dir)
        if bds_dir.exists():
            bds_dir.replace(backup_dir)
        try:
            staged_dir.replace(bds_dir)
        except OSError:
            if backup_dir.exists() and not bds_dir.exists():
                backup_dir.replace(bds_dir)
            raise
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

    verify_bds_install(bds_dir, expected_archive_sha256=expected_archive_sha256)
    print(f"Installed verified Bedrock Dedicated Server {BDS_VERSION}")
    return bds_dir


def remove_legacy_artifacts(server_dir: Path = SERVER_DIR) -> None:
    plugin_dirs = (server_dir / "plugins", server_dir / "bedrock_server" / "plugins")
    for plugins_dir in plugin_dirs:
        plugins_dir.mkdir(parents=True, exist_ok=True)
        for plugin_jar in plugins_dir.rglob("*.jar"):
            plugin_jar.unlink()
            print(f"Removed legacy plugin artifact: {plugin_jar.name}")
    for server_jar in server_dir.glob("*.jar"):
        server_jar.unlink()
        print(f"Removed legacy server artifact: {server_jar.name}")
    for old_wheel in server_dir.glob("endstone-*.whl"):
        if old_wheel.name != ENDSTONE_WHEEL_NAME:
            old_wheel.unlink()
            print(f"Removed stale Endstone wheel: {old_wheel.name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the installed BDS version and executable without downloading.",
    )
    args = parser.parse_args()

    if os.environ.get("ENDSTONE_VERSION", ENDSTONE_VERSION).lstrip("v") != ENDSTONE_VERSION:
        parser.error(f"ENDSTONE_VERSION must be pinned to {ENDSTONE_VERSION}")
    if os.environ.get("BEDROCK_CLIENT_VERSION", "1.26.2") != "1.26.2":
        parser.error("BEDROCK_CLIENT_VERSION must remain 1.26.2")

    SERVER_DIR.mkdir(parents=True, exist_ok=True)
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if args.check:
            verify_bds_install(BDS_DIR)
            print(f"Bedrock runtime integrity check passed for {BDS_VERSION}.")
            return 0

        wheel_path = SERVER_DIR / ENDSTONE_WHEEL_NAME
        archive_path = SERVER_DIR / "bedrock-server-1.26.3.1.zip"
        download_verified(ENDSTONE_WHEEL_URL, wheel_path, ENDSTONE_WHEEL_SHA256)
        validate_endstone_wheel(wheel_path)
        download_verified(BDS_ARCHIVE_URL, archive_path, BDS_ARCHIVE_SHA256)
        install_bds_archive(archive_path)
        archive_path.unlink()
        remove_legacy_artifacts()
    except (OSError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"ERROR: native Bedrock dependency setup failed: {exc}", file=sys.stderr)
        return 1

    print(f"Endstone {ENDSTONE_VERSION} and BDS {BDS_VERSION} runtime are ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
