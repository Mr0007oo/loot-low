#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
SERVER_DIR="$ROOT_DIR/server"
WORLD_PERSIST_SCRIPT="${WORLD_PERSIST_SCRIPT:-$ROOT_DIR/scripts/persist_world.py}"
FRPC_BIN="${FRPC_BIN:-$ROOT_DIR/frpc}"
FRPC_CONFIG="${FRPC_CONFIG:-$ROOT_DIR/frpc.toml}"
SERVER_LAUNCHER="${SERVER_LAUNCHER:-$SERVER_DIR/start.sh}"
FRPC_LOG="${FRPC_LOG:-$ROOT_DIR/frpc.log}"
SERVER_LOG="${SERVER_LOG:-$SERVER_DIR/logs/server-session.log}"
WATCHDOG_LOG="${WATCHDOG_LOG:-$SERVER_DIR/logs/watchdog-health.log}"
POLL_INTERVAL_SECONDS="${WATCHDOG_INTERVAL_SECONDS:-30}"
WORLD_SYNC_INTERVAL_SECONDS="${WORLD_SYNC_INTERVAL_SECONDS:-3600}"
SERVER_PID=""
FRPC_PID="${FRPC_PID:-}"

log() {
    printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$WATCHDOG_LOG"
}

stop_process() {
    local process_id="$1"
    if [[ -n "$process_id" ]] && kill -0 "$process_id" 2>/dev/null; then
        kill -TERM "$process_id" 2>/dev/null || true
        wait "$process_id" 2>/dev/null || true
    fi
}

sync_world() {
    log "Persisting world data to main."
    python3 "$WORLD_PERSIST_SCRIPT"
}

cleanup() {
    local exit_status=$?
    trap - EXIT INT TERM
    if [[ -n "$SERVER_PID" ]]; then
        log "Stopping native Bedrock server gracefully."
        stop_process "$SERVER_PID"
    fi
    stop_process "$FRPC_PID"
    if ! sync_world; then
        log "ERROR: World persistence failed during shutdown."
        if [[ "$exit_status" -eq 0 ]]; then
            exit_status=1
        fi
    fi
    exit "$exit_status"
}

trap cleanup EXIT
trap 'exit 143' INT TERM

if [[ -z "${FRP_SERVER_IP:-}" || -z "${FRP_TOKEN:-}" ]]; then
    echo "ERROR: FRP_SERVER_IP and FRP_TOKEN are required for FRP startup." >&2
    exit 1
fi
if [[ ! -x "$FRPC_BIN" ]]; then
    echo "ERROR: frpc binary is missing or not executable: $FRPC_BIN" >&2
    exit 1
fi
if [[ ! -s "$FRPC_CONFIG" ]]; then
    echo "ERROR: FRP config is missing: $FRPC_CONFIG" >&2
    exit 1
fi
if [[ ! -x "$SERVER_LAUNCHER" ]]; then
    echo "ERROR: Endstone launcher is missing or not executable: $SERVER_LAUNCHER" >&2
    exit 1
fi
if [[ ! "$POLL_INTERVAL_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: WATCHDOG_INTERVAL_SECONDS must be a positive integer." >&2
    exit 1
fi
if [[ ! "$WORLD_SYNC_INTERVAL_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: WORLD_SYNC_INTERVAL_SECONDS must be a positive integer." >&2
    exit 1
fi

mkdir -p "$SERVER_DIR/logs"

start_frpc() {
    : >"$FRPC_LOG"
    "$FRPC_BIN" -c "$FRPC_CONFIG" >>"$FRPC_LOG" 2>&1 &
    FRPC_PID=$!
    log "Started frpc with the Bedrock UDP proxy (pid=$FRPC_PID)."
    sleep 5
    if ! kill -0 "$FRPC_PID" 2>/dev/null; then
        cat "$FRPC_LOG" || true
        log "ERROR: frpc exited during startup."
        return 1
    fi
}

start_server() {
    "$SERVER_LAUNCHER" >>"$SERVER_LOG" 2>&1 &
    SERVER_PID=$!
    log "Started Endstone supervisor (pid=$SERVER_PID)."
}

if [[ -z "$FRPC_PID" ]]; then
    start_frpc || exit 1
fi
if ! kill -0 "$FRPC_PID" 2>/dev/null; then
    cat "$FRPC_LOG" || true
    log "ERROR: frpc is not running."
    exit 1
fi
log "FRP Bedrock UDP proxy is active at ${FRP_SERVER_IP}:19132."
start_server

last_world_sync=$SECONDS
while true; do
    sleep "$POLL_INTERVAL_SECONDS" || true

    if ! kill -0 "$FRPC_PID" 2>/dev/null; then
        cat "$FRPC_LOG" || true
        if wait "$FRPC_PID" 2>/dev/null; then
            frpc_status=0
        else
            frpc_status=$?
        fi
        log "frpc exited with status $frpc_status; restoring the UDP proxy."
        if ! start_frpc; then
            log "ERROR: frpc recovery failed."
            exit 1
        fi
    fi

    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        if wait "$SERVER_PID"; then
            server_status=0
        else
            server_status=$?
        fi
        log "Endstone supervisor exited with status $server_status; restarting in 5 seconds."
        sleep 5 || true
        start_server
    fi

    if (( SECONDS - last_world_sync >= WORLD_SYNC_INTERVAL_SECONDS )); then
        if ! sync_world; then
            log "ERROR: Hourly world persistence failed."
            exit 1
        fi
        last_world_sync=$SECONDS
    fi
done
