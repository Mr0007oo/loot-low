#!/usr/bin/env python3
"""Save Minecraft state and commit configured world/player data to Git."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PERSIST_PATHS = (
    "server/world",
    "server/world_nether",
    "server/world_the_end",
    "server/ops.json",
    "server/banned-players.json",
    "server/usercache.json",
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


def save_all() -> str:
    password = os.environ.get("RCON_PASSWORD", "")
    if not password:
        raise RuntimeError("RCON_PASSWORD is required to save the Minecraft world")
    try:
        from mcrcon import MCRcon
    except ImportError as exc:
        raise RuntimeError("mcrcon is not installed; install workflow Python dependencies") from exc

    port = int(os.environ.get("RCON_PORT", "25575"))
    with MCRcon("127.0.0.1", password, port=port) as connection:
        response = connection.command("save-all")
    print(f"RCON save-all: {response or 'command sent'}", flush=True)
    time.sleep(5)
    return response


def commit_and_push() -> bool:
    available_paths = [path for path in PERSIST_PATHS if (ROOT / path).exists()]
    if not available_paths:
        print("No world or player-data files exist yet.")
        return False

    run_git(["add", "-f", "--", *available_paths])
    staged = run_git(["diff", "--cached", "--quiet", "--", *available_paths], check=False)
    if staged.returncode == 1:
        run_git(["config", "user.name", "github-actions[bot]"])
        run_git(["config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
        run_git(["commit", "--only", "-m", "Persist Minecraft world [skip ci]", "--", *available_paths])
        print("Committed changed world and player data.")
    elif staged.returncode == 0:
        print("No world or player-data changes to commit.")
    else:
        raise RuntimeError(f"git diff failed with status {staged.returncode}")

    branch = os.environ.get("GITHUB_REF_NAME", "")
    if not branch:
        branch_result = run_git(["branch", "--show-current"])
        branch = branch_result.stdout.strip()
    if not branch:
        raise RuntimeError("Cannot determine the branch to push world data to")

    run_git(["push", "origin", f"HEAD:refs/heads/{branch}"])
    print(f"Committed and pushed world data to {branch}.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-rcon", action="store_true", help="commit files without sending save-all")
    arguments = parser.parse_args()

    root_key = hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
    lock_path = Path("/tmp") / f"loot-low-world-persist-{root_key}.lock"
    try:
        with lock_path.open("w") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            if not arguments.skip_rcon:
                save_all()
            commit_and_push()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: world persistence failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
