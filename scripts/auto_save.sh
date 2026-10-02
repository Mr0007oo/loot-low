#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3)"
fi
SAVE_INTERVAL_SECONDS="${SAVE_INTERVAL_SECONDS:-1800}"
LOG_FILE="$ROOT_DIR/server/logs/auto-save.log"

log() {
    printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG_FILE"
}

persist_world() {
    "$PYTHON_BIN" "$ROOT_DIR/scripts/persist_world.py"
}

final_save() {
    local exit_status=$?
    trap - EXIT INT TERM
    log "Auto-save loop stopping; performing final world save and push."
    persist_world || log "ERROR: final world save/push failed."
    exit "$exit_status"
}

if [[ ! "$SAVE_INTERVAL_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: SAVE_INTERVAL_SECONDS must be a positive integer." >&2
    exit 1
fi
mkdir -p "$ROOT_DIR/server/logs"
trap final_save EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

log "World auto-save started; interval=${SAVE_INTERVAL_SECONDS}s."
while true; do
    sleep "$SAVE_INTERVAL_SECONDS" || true
    log "Running scheduled world save and Git push."
    persist_world || log "ERROR: scheduled world save/push failed; will retry next interval."
done
