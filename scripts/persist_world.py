#!/usr/bin/env python3
"""Commit native Bedrock world and server access data to Git."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
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
WORLD_PATHS = ("server/world", "server/worlds", "server/bedrock_server/worlds")
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


def restore_world_paths(commit_ref: str) -> list[str]:
    resolved = run_git(["rev-parse", "--verify", f"{commit_ref}^{{commit}}"], check=False)
    if resolved.returncode:
        fetch = run_git(["fetch", "origin", commit_ref], check=False)
        if fetch.returncode:
            detail = fetch.stderr.strip() or fetch.stdout.strip()
            raise RuntimeError(
                f"Cannot find recovery commit {commit_ref} locally or fetch it from origin: {detail}"
            )
        resolved = run_git(["rev-parse", "--verify", f"{commit_ref}^{{commit}}"], check=False)
        if resolved.returncode:
            raise RuntimeError(f"Fetched recovery ref {commit_ref} is not a commit")

    commit = resolved.stdout.strip()
    archive = subprocess.run(
        ["git", "archive", "--format=tar", commit, "--", "server/world", "server/worlds"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if archive.returncode:
        detail = archive.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"Cannot read world data from {commit}: {detail}")

    restored: list[str] = []
    with tempfile.TemporaryDirectory(prefix="loot-low-world-recovery-") as temp_dir:
        extracted_root = Path(temp_dir)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as bundle:
            members = bundle.getmembers()
            allowed_roots = {"server/world", "server/worlds"}
            for member in members:
                member_path = Path(member.name)
                if (
                    member_path.is_absolute()
                    or ".." in member_path.parts
                    or not (
                        member.name == "server"
                        or any(
                            member.name == root or member.name.startswith(f"{root}/")
                            for root in allowed_roots
                        )
                    )
                ):
                    raise RuntimeError(
                        f"Recovery commit {commit} contains an unexpected path: {member.name}"
                    )
            bundle.extractall(extracted_root, filter="data")

        for relative_path in ("server/world", "server/worlds"):
            source = extracted_root / relative_path
            destination = ROOT / relative_path
            if not source.exists():
                continue
            if destination.exists():
                print(f"Preserving existing {relative_path}; recovery will not overwrite it.")
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination)
            restored.append(relative_path)

    if restored:
        print(f"Restored missing world directories from {commit}: {', '.join(restored)}")
    else:
        print(f"No world directories needed restoring from {commit}.")
    return restored


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
                f"Persist world progress [skip ci] {timestamp}",
                "--",
                *available_paths,
            ]
        )
        print("Committed changed world and player data.")
    elif staged.returncode == 0:
        print("No world or player-data changes to commit.")
    else:
        raise RuntimeError(f"git diff failed with status {staged.returncode}")

    for attempt in range(1, 6):
        fetch = run_git(
            ["fetch", "origin", "+refs/heads/main:refs/remotes/origin/main"],
            check=False,
        )
        if fetch.returncode:
            detail = fetch.stderr.strip() or fetch.stdout.strip()
            raise RuntimeError(f"Cannot fetch origin/main before world push: {detail}")

        remote_is_ancestor = run_git(
            ["merge-base", "--is-ancestor", "origin/main", "HEAD"],
            check=False,
        )
        if remote_is_ancestor.returncode == 1:
            local_is_ancestor = run_git(
                ["merge-base", "--is-ancestor", "HEAD", "origin/main"],
                check=False,
            )
            if local_is_ancestor.returncode == 0:
                run_git(["merge", "--ff-only", "origin/main"])
                continue
            if local_is_ancestor.returncode != 1:
                raise RuntimeError(
                    "Cannot determine whether HEAD is already included in origin/main"
                )

            merge = run_git(
                ["merge", "--no-edit", "--no-commit", "--no-ff", "-X", "ours", "origin/main"],
                check=False,
            )
            merge_head = run_git(["rev-parse", "--verify", "-q", "MERGE_HEAD"], check=False)
            if merge_head.returncode:
                detail = merge.stderr.strip() or merge.stdout.strip()
                raise RuntimeError(f"Cannot merge origin/main: {detail}")

            local_world_files = set(
                run_git(
                    ["ls-tree", "-r", "--name-only", "-z", "HEAD", "--", *WORLD_PATHS]
                ).stdout.split("\0")
            )
            remote_world_files = run_git(
                ["ls-tree", "-r", "--name-only", "-z", "origin/main", "--", *WORLD_PATHS]
            ).stdout.split("\0")
            remote_only_world_files = [
                path
                for path in remote_world_files
                if path and path not in local_world_files
            ]
            if remote_only_world_files:
                run_git(["rm", "-f", "--", *remote_only_world_files])

            world_paths = [
                path
                for path in WORLD_PATHS
                if run_git(["cat-file", "-e", f"HEAD:{path}"], check=False).returncode == 0
            ]
            if world_paths:
                run_git(
                    [
                        "restore",
                        "--source=HEAD",
                        "--staged",
                        "--worktree",
                        "--",
                        *world_paths,
                    ]
                )

            unresolved = run_git(["diff", "--name-only", "--diff-filter=U"], check=False)
            if unresolved.returncode:
                run_git(["merge", "--abort"], check=False)
                detail = unresolved.stderr.strip() or unresolved.stdout.strip()
                raise RuntimeError(
                    f"Cannot inspect conflicts while merging origin/main: {detail}"
                )
            if unresolved.stdout.strip():
                run_git(["merge", "--abort"], check=False)
                detail = merge.stderr.strip() or merge.stdout.strip()
                conflicts = unresolved.stdout.strip()
                raise RuntimeError(
                    "Cannot merge origin/main while preserving local world data: "
                    f"{detail}\nUnresolved paths:\n{conflicts}"
                )
            run_git(["commit", "--no-edit"])
        elif remote_is_ancestor.returncode != 0:
            raise RuntimeError(
                "Cannot determine whether origin/main is already included in the local commit"
            )

        push = run_git(["push", "origin", "HEAD:refs/heads/main"], check=False)
        if push.returncode == 0:
            print("Committed and pushed world data to main.")
            return True

        if attempt == 5:
            detail = push.stderr.strip() or push.stdout.strip()
            raise RuntimeError(f"Git push failed after {attempt} attempts: {detail}")
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--restore-only",
        metavar="COMMIT",
        help="restore server/world and server/worlds only when missing, from this commit",
    )
    args = parser.parse_args()
    root_key = hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
    lock_path = Path("/tmp") / f"loot-low-world-persist-{root_key}.lock"
    try:
        with lock_path.open("w") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            if args.restore_only:
                restore_world_paths(args.restore_only)
                return 0
            sync_runtime_access_files()
            recovery_commit = os.environ.get("WORLD_RECOVERY_COMMIT")
            if recovery_commit:
                try:
                    restore_world_paths(recovery_commit)
                except RuntimeError as exc:
                    print(
                        f"WARNING: {exc}. Existing workspace world data was left untouched.",
                        file=sys.stderr,
                    )
            commit_and_push()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: world persistence failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
