#!/usr/bin/env python3
"""Commit native Bedrock world and server access data to Git."""

from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PERSIST_PATHS = (
    "server/world",
    "server/worlds",
    "server/bedrock_server/worlds",
    "server/permissions.json",
    "server/allowlist.json",
)
TRANSIENT_EXCLUDES = (
    ":(exclude,glob)**/session.lock",
    ":(exclude,glob)**/*.lock",
    ":(exclude,glob)**/*.tmp",
    ":(exclude,glob)**/*.part",
)


def run_git(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return result


def commit_and_push() -> bool:
    available_paths = [path for path in PERSIST_PATHS if (ROOT / path).exists()]
    if not available_paths:
        print("No world or player-data files exist yet.")
        return False

    run_git(["add", "-f", "--", *available_paths, *TRANSIENT_EXCLUDES])
    staged = run_git(["diff", "--cached", "--quiet", "--", *available_paths], check=False)
    if staged.returncode == 1:
        run_git(["config", "user.name", "github-actions[bot]"])
        run_git(["config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        run_git(
            [
                "commit",
                "--only",
                "-m",
                f"Auto-commit world progress {timestamp}",
                "--",
                *available_paths,
            ]
        )
        print("Committed changed world and player data.")
    elif staged.returncode == 0:
        print("No world or player-data changes to commit.")
    else:
        raise RuntimeError(f"git diff failed with status {staged.returncode}")

    for attempt in range(1, 4):
        push = run_git(["push", "origin", "HEAD:refs/heads/main"], check=False)
        if push.returncode == 0:
            print("Committed and pushed world data to main.")
            return True

        if attempt == 3:
            detail = push.stderr.strip() or push.stdout.strip()
            raise RuntimeError(f"Git push failed after {attempt} attempts: {detail}")

        run_git(["fetch", "origin", "main"])
        rebase = run_git(
            ["rebase", "--autostash", "origin/main"],
            check=False,
        )
        if rebase.returncode:
            run_git(["rebase", "--abort"], check=False)
            detail = rebase.stderr.strip() or rebase.stdout.strip()
            raise RuntimeError(f"Cannot rebase world commit onto origin/main: {detail}")
        time.sleep(2**attempt)

    raise RuntimeError("Git push retry limit reached")


def sync_runtime_access_files() -> None:
    runtime_dir = ROOT / "server" / "bedrock_server"
    for name in ("permissions.json", "allowlist.json"):
        source = runtime_dir / name
        destination = ROOT / "server" / name
        if source.is_file():
            shutil.copy2(source, destination)


def main() -> int:
    root_key = hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
    lock_path = Path("/tmp") / f"loot-low-world-persist-{root_key}.lock"
    try:
        with lock_path.open("w") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            sync_runtime_access_files()
            commit_and_push()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: world persistence failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
