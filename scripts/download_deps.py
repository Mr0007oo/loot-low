#!/usr/bin/env python3
"""Download and validate the official native Endstone Bedrock server runtime."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
PLUGINS_DIR = SERVER_DIR / "plugins"
REPOSITORY = "EndstoneMC/endstone"
VERSION = os.environ.get("ENDSTONE_VERSION", "").strip()
BEDROCK_CLIENT_VERSION = os.environ.get("BEDROCK_CLIENT_VERSION", "1.26.2").strip()
USER_AGENT = "loot-low-native-bedrock-downloader/1.0"
RETRIES = 3


def request(url: str, accept: str = "*/*") -> urllib.request.urlopen:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise RuntimeError(f"Refusing non-HTTPS dependency URL: {url}")
    return urllib.request.urlopen(
        urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": accept},
        ),
        timeout=60,
    )


def fetch_json(url: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            with request(url, "application/vnd.github+json") as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"HTTP {response.status}")
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise RuntimeError("GitHub returned an unexpected JSON document")
            return payload
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            print(f"GitHub API attempt {attempt}/{RETRIES} failed: {exc}", file=sys.stderr)
            if attempt < RETRIES:
                time.sleep(attempt)
    raise RuntimeError(f"Could not retrieve Endstone release metadata: {last_error}")


def release_metadata() -> dict[str, Any]:
    if VERSION and not re.fullmatch(r"v?\d+\.\d+\.\d+", VERSION):
        raise RuntimeError(f"Invalid ENDSTONE_VERSION: {VERSION!r}")
    if VERSION:
        tag = VERSION if VERSION.startswith("v") else f"v{VERSION}"
        url = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{tag}"
    else:
        url = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
    release = fetch_json(url)
    if release.get("draft") or release.get("prerelease"):
        raise RuntimeError("Refusing to install a draft or prerelease Endstone build")
    return release


def report_protocol_target(release: dict[str, Any]) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", BEDROCK_CLIENT_VERSION):
        raise RuntimeError(f"Invalid BEDROCK_CLIENT_VERSION: {BEDROCK_CLIENT_VERSION!r}")
    release_notes = str(release.get("body", ""))
    match = re.search(
        r"(?:Bedrock Edition|BDS)\s+([0-9]+(?:\.[0-9]+){1,2})",
        release_notes,
    )
    if not match:
        print("WARNING: Endstone release notes do not declare a Bedrock version target.")
        return
    server_version = match.group(1)
    print(f"Endstone native Bedrock target: {server_version}")
    if server_version != BEDROCK_CLIENT_VERSION:
        print(
            f"WARNING: requested client {BEDROCK_CLIENT_VERSION} differs from the bundled "
            f"server target {server_version}; compatibility depends on "
            "allow-outdated-client=true and must be confirmed with a real client."
        )


def download_release(release: dict[str, Any]) -> Path:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("Endstone release metadata has no assets list")
    asset = next(
        (
            item
            for item in assets
            if item.get("name", "").endswith("-linux-x86_64.zip")
            and item.get("name", "").startswith("endstone-")
        ),
        None,
    )
    if not asset:
        raise RuntimeError("Endstone release has no Linux x86_64 server bundle")
    digest = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise RuntimeError(f"Endstone release asset has no valid SHA-256 digest: {asset.get('name')}")

    destination = SERVER_DIR / asset["name"]
    expected_digest = digest.removeprefix("sha256:")
    url = asset.get("browser_download_url", "")
    last_error: Exception | None = None

    for attempt in range(1, RETRIES + 1):
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}.",
                suffix=".part",
                dir=SERVER_DIR,
                delete=False,
            ) as output:
                temp_path = Path(output.name)
                with request(url) as response:
                    if not 200 <= response.status < 300:
                        raise RuntimeError(f"HTTP {response.status}")
                    hasher = hashlib.sha256()
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                        hasher.update(chunk)
            if hasher.hexdigest() != expected_digest:
                raise RuntimeError("Downloaded Endstone bundle failed SHA-256 verification")
            validate_bundle(temp_path)
            temp_path.replace(destination)
            print(f"Verified {asset['name']} ({asset.get('size', 'unknown')} bytes)")
            return destination
        except (OSError, urllib.error.URLError, TimeoutError, RuntimeError, zipfile.BadZipFile) as exc:
            last_error = exc
            print(f"Endstone download attempt {attempt}/{RETRIES} failed: {exc}", file=sys.stderr)
            if attempt < RETRIES:
                time.sleep(attempt)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()
    raise RuntimeError(f"Endstone download failed after {RETRIES} attempts: {last_error}")


def validate_bundle(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            bad_member = archive.testzip()
            if bad_member:
                raise RuntimeError(f"Corrupt Endstone ZIP member: {bad_member}")
            launcher = next((name for name in names if name.endswith("/start.sh")), None)
            wheel = next(
                (
                    name
                    for name in names
                    if re.fullmatch(
                        r"[^/]+/endstone-[^/]+-cp313-cp313-manylinux_[^/]+_x86_64\.whl",
                        name,
                    )
                ),
                None,
            )
            if not launcher or not wheel:
                raise RuntimeError("Endstone bundle is missing its launcher or CPython 3.13 Linux wheel")
            for name in (launcher, wheel):
                if Path(name).is_absolute() or ".." in Path(name).parts:
                    raise RuntimeError(f"Unsafe path in Endstone archive: {name}")
            return wheel
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise RuntimeError(f"Invalid Endstone release archive: {exc}") from exc


def install_bundle(path: Path) -> None:
    wheel_name = validate_bundle(path)
    with zipfile.ZipFile(path) as archive:
        wheel_path = SERVER_DIR / Path(wheel_name).name
        with archive.open(wheel_name) as source, wheel_path.open("wb") as destination:
            while chunk := source.read(1024 * 1024):
                destination.write(chunk)

    for old_wheel in SERVER_DIR.glob("endstone-*.whl"):
        if old_wheel != wheel_path:
            old_wheel.unlink()
    print(f"Installed Endstone wheel {wheel_path.name}")


def remove_legacy_artifacts() -> None:
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    for plugin_jar in PLUGINS_DIR.rglob("*.jar"):
        plugin_jar.unlink()
        print(f"Removed legacy plugin artifact: {plugin_jar.name}")
    for server_jar in SERVER_DIR.glob("*.jar"):
        server_jar.unlink()
        print(f"Removed legacy server artifact: {server_jar.name}")


def main() -> int:
    SERVER_DIR.mkdir(parents=True, exist_ok=True)
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        release = release_metadata()
        version = release.get("tag_name", "unknown")
        print(f"Downloading Endstone {version}: {release.get('html_url', '')}")
        report_protocol_target(release)
        bundle = download_release(release)
        install_bundle(bundle)
        bundle.unlink()
        remove_legacy_artifacts()
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        print(f"ERROR: native Bedrock dependency setup failed: {exc}", file=sys.stderr)
        return 1
    print("Native Endstone runtime is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
