#!/usr/bin/env bash
set -euo pipefail

SERVER_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$SERVER_DIR"

if ! command -v python3.13 >/dev/null 2>&1; then
    echo "ERROR: Python 3.13 is required by the Endstone Linux release." >&2
    exit 1
fi

wheel=""
while IFS= read -r candidate; do
    wheel="$candidate"
    break
done < <(find "$SERVER_DIR" -maxdepth 1 -type f -name 'endstone-*-cp313-cp313-manylinux*_x86_64.whl' -print)
if [[ -z "$wheel" ]]; then
    echo "ERROR: Endstone runtime wheel is missing. Run scripts/download_deps.py first." >&2
    exit 1
fi
if [[ ! -f "$SERVER_DIR/plugins/lootlow_bedrock/pyproject.toml" ]]; then
    echo "ERROR: Native Bedrock plugin package is missing." >&2
    exit 1
fi

if [[ ! -x "$SERVER_DIR/.venv/bin/python" ]]; then
    python3.13 -m venv "$SERVER_DIR/.venv"
fi
"$SERVER_DIR/.venv/bin/python" -m pip install --disable-pip-version-check "$wheel"
"$SERVER_DIR/.venv/bin/python" -m pip install --disable-pip-version-check \
    "$SERVER_DIR/plugins/lootlow_bedrock"

server_pid=""
stop_server() {
    if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
        echo "[$(date -Is)] Shutdown requested; forwarding SIGTERM to Endstone."
        kill -TERM "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    exit 143
}
trap stop_server INT TERM

restart_count=0
max_restarts=3
while true; do
    echo "[$(date -Is)] Starting native Bedrock server with Endstone ${wheel##*/} (restart ${restart_count}/${max_restarts})."
    "$SERVER_DIR/.venv/bin/python" -m endstone -i &
    server_pid=$!
    if wait "$server_pid"; then
        exit_code=0
    else
        exit_code=$?
    fi
    server_pid=""

    if [[ "$exit_code" -eq 0 ]]; then
        echo "[$(date -Is)] Endstone stopped cleanly."
        exit 0
    fi

    echo "[$(date -Is)] Endstone exited with code ${exit_code}." >&2
    if [[ "$restart_count" -ge "$max_restarts" ]]; then
        echo "[$(date -Is)] Restart limit (${max_restarts}) reached; exiting." >&2
        exit "$exit_code"
    fi
    restart_count=$((restart_count + 1))
    echo "[$(date -Is)] Restarting in 5 seconds (${restart_count}/${max_restarts})." >&2
    sleep 5
done
