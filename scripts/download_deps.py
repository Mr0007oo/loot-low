#!/usr/bin/env python3
"""Download and validate Paper 1.21.1 and its server plugins."""

from __future__ import annotations

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
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
PLUGINS_DIR = SERVER_DIR / "plugins"
MIN_PLUGIN_BYTES = 100_000
MIN_PAPER_BYTES = 35_000_000
# These two verified upstream plugins are published as valid sub-100 KB JARs.
MIN_COMPACT_PLUGIN_BYTES = 30_000
RETRIES = 3
USER_AGENT = "loot-low-dependency-downloader/1.0 (https://github.com/Mr0007oo/loot-low)"
GEYSER_VERSION = os.environ.get("GEYSER_VERSION") or "2.11.2"
GEYSER_BUILD = os.environ.get("GEYSER_BUILD") or "1235"
GEYSER_BEDROCK_PROTOCOL = os.environ.get("GEYSER_BEDROCK_PROTOCOL") or "26_20"
FLOODGATE_VERSION = os.environ.get("FLOODGATE_VERSION") or "2.2.5"
FLOODGATE_BUILD = os.environ.get("FLOODGATE_BUILD") or "141"


@dataclass(frozen=True)
class Candidate:
    url: str
    source: str
    required_member: str | None = None


@dataclass(frozen=True)
class Artifact:
    filename: str
    minimum_bytes: int
    sources: tuple[Callable[[], Candidate], ...]
    cleanup_patterns: tuple[str, ...] = ()


def request(url: str, accept: str = "*/*") -> urllib.request.urlopen:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    )
    return urllib.request.urlopen(req, timeout=45)


def get_json(url: str) -> object:
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            with request(url, "application/json") as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"HTTP {response.status}")
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            print(f"  API attempt {attempt}/{RETRIES} failed for {url}: {exc}")
            if attempt < RETRIES:
                time.sleep(attempt)
    raise RuntimeError(f"API request failed after {RETRIES} attempts: {last_error}")


def paper_fill_api() -> Candidate:
    builds = get_json("https://fill.papermc.io/v3/projects/paper/versions/1.21.1/builds")
    if not isinstance(builds, list):
        raise RuntimeError("PaperMC fill API returned an unexpected response")
    stable = [build for build in builds if build.get("channel") == "STABLE"]
    if not stable:
        raise RuntimeError("PaperMC fill API returned no stable 1.21.1 builds")
    build = max(stable, key=lambda item: item["id"])
    return Candidate(build["downloads"]["server:default"]["url"], "PaperMC official fill API v3")


def geyser_api(
    project: str,
    label: str,
    version: str = "latest",
    build: str = "latest",
    required_member: str | None = None,
) -> Candidate:
    return Candidate(
        f"https://download.geysermc.org/v2/projects/{project}/versions/{version}/builds/{build}/downloads/spigot",
        f"GeyserMC API v2 ({label} {version} build {build})",
        required_member,
    )


def pinned_geyser() -> Candidate:
    if not re.fullmatch(r"\d+\.\d+\.\d+", GEYSER_VERSION):
        raise RuntimeError(f"Invalid GEYSER_VERSION: {GEYSER_VERSION!r}")
    if not re.fullmatch(r"\d+", GEYSER_BUILD):
        raise RuntimeError(f"Invalid GEYSER_BUILD: {GEYSER_BUILD!r}")
    if not re.fullmatch(r"\d+_\d+", GEYSER_BEDROCK_PROTOCOL):
        raise RuntimeError(f"Invalid GEYSER_BEDROCK_PROTOCOL: {GEYSER_BEDROCK_PROTOCOL!r}")
    return geyser_api(
        "geyser",
        "Geyser-Spigot",
        GEYSER_VERSION,
        GEYSER_BUILD,
        f"bedrock/runtime_item_states.{GEYSER_BEDROCK_PROTOCOL}.json",
    )


def pinned_floodgate() -> Candidate:
    if not re.fullmatch(r"\d+\.\d+\.\d+", FLOODGATE_VERSION):
        raise RuntimeError(f"Invalid FLOODGATE_VERSION: {FLOODGATE_VERSION!r}")
    if not re.fullmatch(r"\d+", FLOODGATE_BUILD):
        raise RuntimeError(f"Invalid FLOODGATE_BUILD: {FLOODGATE_BUILD!r}")
    return geyser_api("floodgate", "Floodgate-Spigot", FLOODGATE_VERSION, FLOODGATE_BUILD)


def github_asset(repository: str, pattern: str, excluded: tuple[str, ...] = ()) -> Candidate:
    data = get_json(f"https://api.github.com/repos/{repository}/releases/latest")
    if not isinstance(data, dict):
        raise RuntimeError(f"GitHub returned an unexpected release for {repository}")
    assets = [asset for asset in data.get("assets", []) if asset.get("name", "").lower().endswith(".jar")]
    assets = [asset for asset in assets if re.search(pattern, asset["name"], re.IGNORECASE)]
    assets = [asset for asset in assets if not any(term in asset["name"].lower() for term in excluded)]
    if not assets:
        raise RuntimeError(f"No matching JAR in latest release for {repository}")
    asset = max(assets, key=lambda item: item.get("size", 0))
    return Candidate(asset["browser_download_url"], f"GitHub Releases API ({repository})")


class ReleaseLinkParser(HTMLParser):
    def __init__(self, repository: str) -> None:
        super().__init__()
        self.prefix = f"/{repository}/releases/download/"
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href and href.startswith(self.prefix) and href.lower().endswith(".jar"):
            self.urls.append(urllib.parse.urljoin("https://github.com", href))


def github_release_page(repository: str, pattern: str, excluded: tuple[str, ...] = ()) -> Candidate:
    url = f"https://github.com/{repository}/releases/latest"
    with request(url, "text/html") as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"HTTP {response.status} loading {url}")
        page = response.read().decode("utf-8", errors="replace")
    parser = ReleaseLinkParser(repository)
    parser.feed(page)
    assets = [link for link in parser.urls if re.search(pattern, link, re.IGNORECASE)]
    assets = [link for link in assets if not any(term in link.lower() for term in excluded)]
    if not assets:
        raise RuntimeError(f"No matching JAR found on official release page for {repository}")
    return Candidate(assets[0], f"official GitHub release mirror ({repository})")


def modrinth(
    project: str,
    preferred_filename: str | None = None,
    version_number: str | None = None,
) -> Candidate:
    url = "https://api.modrinth.com/v2/project/" + urllib.parse.quote(project) + "/version?" + urllib.parse.urlencode(
        {"game_versions": json.dumps(["1.21.1"])}
    )
    versions = get_json(url)
    if not isinstance(versions, list) or not versions:
        raise RuntimeError(f"Modrinth has no compatible 1.21.1 versions for {project}")
    if version_number:
        versions = [version for version in versions if version.get("version_number") == version_number]
        if not versions:
            raise RuntimeError(f"Modrinth has no compatible {version_number} version for {project}")
    for version in versions:
        files = [file for file in version.get("files", []) if file.get("filename", "").lower().endswith(".jar")]
        if preferred_filename:
            preferred = [file for file in files if preferred_filename.lower() in file["filename"].lower()]
            files = preferred or files
        if files:
            file = next((item for item in files if item.get("primary")), files[0])
            return Candidate(file["url"], f"Modrinth API v2 ({project})")
    raise RuntimeError(f"Modrinth returned no JAR for {project}")


def spiget(resource_id: int, name: str) -> Candidate:
    return Candidate(f"https://api.spiget.org/v2/resources/{resource_id}/download", f"Spiget API redirect to Spigot resource ({name})")


def validate_jar(
    path: Path,
    minimum_bytes: int,
    required_member: str | None = None,
) -> tuple[bool, str]:
    size = path.stat().st_size
    if size < minimum_bytes:
        return False, f"only {size:,} bytes; minimum is {minimum_bytes:,} bytes"
    try:
        with zipfile.ZipFile(path) as archive:
            if required_member and required_member not in archive.namelist():
                return False, f"missing required JAR entry: {required_member}"
            bad_member = archive.testzip()
            if bad_member:
                return False, f"corrupt ZIP member: {bad_member}"
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        return False, f"not a valid JAR archive: {exc}"
    return True, f"valid JAR, {size:,} bytes"


def detect_server_type() -> str:
    server_markers = (
        ("paper.jar", "Paper"),
        ("purpur.jar", "Purpur"),
        ("spigot.jar", "Spigot"),
        ("fabric-server-launch.jar", "Fabric"),
    )
    for filename, server_type in server_markers:
        if (SERVER_DIR / filename).is_file():
            return server_type
    return "Unknown"


def download_candidate(candidate: Candidate, destination: Path, minimum_bytes: int) -> bool:
    for attempt in range(1, RETRIES + 1):
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix=f".{destination.name}.", suffix=".part", dir=destination.parent, delete=False) as temp:
                temp_path = Path(temp.name)
                with request(candidate.url) as response:
                    if not 200 <= response.status < 300:
                        raise RuntimeError(f"HTTP {response.status}")
                    while chunk := response.read(1024 * 1024):
                        temp.write(chunk)
            valid, detail = validate_jar(temp_path, minimum_bytes, candidate.required_member)
            if not valid:
                raise RuntimeError(detail)
            temp_path.replace(destination)
            print(f"  OK {destination.name}: {detail} ({candidate.source})")
            return True
        except (OSError, urllib.error.URLError, TimeoutError, RuntimeError, zipfile.BadZipFile) as exc:
            print(f"  Download attempt {attempt}/{RETRIES} failed from {candidate.source}: {exc}")
            if attempt < RETRIES:
                time.sleep(attempt)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()
    return False


def download(artifact: Artifact) -> bool:
    destination = SERVER_DIR / artifact.filename if artifact.filename == "paper.jar" else PLUGINS_DIR / artifact.filename
    print(f"\nDownloading {artifact.filename}")
    for source in artifact.sources:
        try:
            candidate = source()
        except Exception as exc:
            print(f"  Source unavailable ({source.__name__}): {exc}")
            continue
        print(f"  Source: {candidate.source}")
        if download_candidate(candidate, destination, artifact.minimum_bytes):
            for pattern in artifact.cleanup_patterns:
                for old_path in PLUGINS_DIR.glob(pattern):
                    if old_path != destination:
                        old_path.unlink()
                        print(f"  Removed superseded plugin JAR: {old_path.name}")
            return True
    print(f"  ERROR: all approved sources failed for {artifact.filename}")
    return False


def main() -> int:
    SERVER_DIR.mkdir(parents=True, exist_ok=True)
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

    github = lambda repo, pattern, excluded=(): (
        lambda: github_asset(repo, pattern, excluded),
        lambda: github_release_page(repo, pattern, excluded),
    )
    modrinth_with_github = lambda slug, repo, pattern: (
        lambda: modrinth(slug),
        lambda: github_asset(repo, pattern),
        lambda: github_release_page(repo, pattern),
    )
    github_with_modrinth = lambda repo, pattern, slug, excluded=(): (
        lambda: github_asset(repo, pattern, excluded),
        lambda: modrinth(slug),
        lambda: github_release_page(repo, pattern, excluded),
    )

    artifacts = [
        Artifact("paper.jar", MIN_PAPER_BYTES, (paper_fill_api,)),
        Artifact("Geyser-Spigot.jar", MIN_PLUGIN_BYTES, (pinned_geyser,), ("Geyser-Spigot*.jar",)),
        Artifact("Floodgate-Spigot.jar", MIN_PLUGIN_BYTES, (pinned_floodgate,), ("Floodgate-Spigot*.jar",)),
        Artifact("ViaVersion.jar", MIN_PLUGIN_BYTES, github_with_modrinth("ViaVersion/ViaVersion", r"ViaVersion", "viaversion"), ("ViaVersion-*.jar",)),
        Artifact("ViaBackwards.jar", MIN_PLUGIN_BYTES, github_with_modrinth("ViaVersion/ViaBackwards", r"ViaBackwards", "viabackwards"), ("ViaBackwards-*.jar",)),
        Artifact("ViaRewind.jar", MIN_PLUGIN_BYTES, github_with_modrinth("ViaVersion/ViaRewind", r"ViaRewind", "viarewind"), ("ViaRewind-*.jar",)),
        Artifact("LuckPerms.jar", MIN_PLUGIN_BYTES, (lambda: modrinth("luckperms", "LuckPerms-Bukkit", "v5.5.71-bukkit"),)),
        Artifact("EssentialsX.jar", MIN_PLUGIN_BYTES, github("EssentialsX/Essentials", r"EssentialsX-[^/]+\.jar", ("chat", "spawn", "discord", "geoip", "antibuild"))),
        Artifact("GSit.jar", MIN_PLUGIN_BYTES, modrinth_with_github("gsit", "Gecolay/GSit", r"GSit")),
        Artifact("Minepacks.jar", MIN_COMPACT_PLUGIN_BYTES, (lambda: modrinth("minepacks"), lambda: spiget(121240, "Minepacks Stable (1.21+)"))),
        Artifact("TAB.jar", MIN_PLUGIN_BYTES, (lambda: modrinth("tab-was-taken", "TAB"), lambda: github_release_page("NEZNAMY/TAB", r"TAB"))),
        Artifact("voicechat-bukkit-2.6.24.jar", MIN_PLUGIN_BYTES, (lambda: modrinth("simple-voice-chat", "voicechat-bukkit", "bukkit-2.6.24"),), ("voicechat*.jar",)),
        Artifact("FastAsyncWorldEdit.jar", MIN_PLUGIN_BYTES, github_with_modrinth("IntellectualSites/FastAsyncWorldEdit", r"FastAsyncWorldEdit.*Bukkit", "fastasyncworldedit")),
        Artifact("MineResetLite.jar", MIN_COMPACT_PLUGIN_BYTES, (lambda: modrinth("mineresetlite"), lambda: spiget(88536, "MineResetLite updated fork"))),
    ]

    failures = [artifact.filename for artifact in artifacts if not download(artifact)]
    if failures:
        print("\nDependency download failed; the server must not be started:")
        for filename in failures:
            print(f"  - {filename}")
        return 1
    server_type = detect_server_type()
    if server_type not in {"Paper", "Purpur", "Spigot"}:
        print(f"\nUnsupported or undetected server type: {server_type}. Geyser-Spigot requires a Bukkit-compatible server.")
        return 1
    print(f"\nDetected {server_type} server; Geyser-Spigot and Floodgate-Spigot are installed for Bukkit compatibility.")
    print("\nAll server and plugin JARs downloaded and validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())