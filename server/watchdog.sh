#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
SERVER_DIR="$ROOT_DIR/server"
FRPC_BIN="${FRPC_BIN:-$ROOT_DIR/frpc}"
FRPC_CONFIG="${FRPC_CONFIG:-$ROOT_DIR/frpc.toml}"
SERVER_LAUNCHER="${SERVER_LAUNCHER:-$SERVER_DIR/start.sh}"
FRPC_LOG="${FRPC_LOG:-$ROOT_DIR/frpc.log}"
SERVER_LOG="${SERVER_LOG:-$SERVER_DIR/logs/server-session.log}"
WATCHDOG_LOG="${WATCHDOG_LOG:-$SERVER_DIR/logs/watchdog-health.log}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3)"
fi
POLL_INTERVAL_SECONDS="${WATCHDOG_INTERVAL_SECONDS:-30}"
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

cleanup() {
    local exit_status=$?
    trap - EXIT INT TERM
    if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
        log "Final RCON save and world push before server shutdown."
        "$PYTHON_BIN" "$ROOT_DIR/scripts/persist_world.py" || log "ERROR: pre-shutdown world save/push failed."
        stop_process "$SERVER_PID"
    fi
    if [[ -n "$SERVER_PID" ]]; then
        log "Pushing final world files after Paper shutdown."
        "$PYTHON_BIN" "$ROOT_DIR/scripts/persist_world.py" --skip-rcon || log "ERROR: final world push failed."
    fi
    stop_process "$FRPC_PID"
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
    echo "ERROR: Server launcher is missing or not executable: $SERVER_LAUNCHER" >&2
    exit 1
fi
if [[ ! "$POLL_INTERVAL_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: WATCHDOG_INTERVAL_SECONDS must be a positive integer." >&2
    exit 1
fi

mkdir -p "$SERVER_DIR/logs"

notify_frp() {
    local address="$1"
    if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
        curl --silent --show-error --fail --max-time 15 --request POST \
            "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
            --data-urlencode "text=FRP Minecraft tunnels restored. Java TCP: ${address}:25565; Bedrock UDP: ${address}:19132" \
            >/dev/null || log "WARNING: Telegram endpoint update failed."
    fi
}

start_frpc() {
    : >"$FRPC_LOG"
    "$FRPC_BIN" -c "$FRPC_CONFIG" >>"$FRPC_LOG" 2>&1 &
    FRPC_PID=$!
    log "Started frpc using $FRPC_CONFIG (pid=$FRPC_PID)."
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
    log "Started Paper supervisor (pid=$SERVER_PID)."
}

log_usage() {
    local java_pid java_usage server_children frpc_usage host_memory
    java_pid=$(pgrep -f '[j]ava.*-jar paper[.]jar' | head -n 1 || true)
    java_usage=$(ps --no-headers -o %cpu=,rss= -p "${java_pid:-}" 2>/dev/null | tr -d '\n' || true)
    server_children=$(ps --no-headers -o pid=,comm=,%cpu=,rss= --ppid "$SERVER_PID" 2>/dev/null | tr '\n' ';' || true)
    frpc_usage=$(ps --no-headers -o %cpu=,rss= -p "$FRPC_PID" 2>/dev/null | tr -d '\n' || true)
    host_memory=$(free -m 2>/dev/null | awk '/^Mem:/ { printf "used=%sMiB available=%sMiB", $3, $7 }' || true)
    log "Health sample: paper_pid=\"${java_pid:-not-running}\" paper_cpu_rss=\"${java_usage:-unavailable}\" server_children=\"${server_children:-none}\" frpc_cpu_rss=\"${frpc_usage:-unavailable}\" memory=\"${host_memory:-unavailable}\""
}

if [[ -z "$FRPC_PID" ]]; then
    start_frpc || exit 1
fi
if ! kill -0 "$FRPC_PID" 2>/dev/null; then
    cat "$FRPC_LOG" || true
    log "ERROR: frpc is not running."
    exit 1
fi
log "FRP TCP/UDP proxies are active for ${FRP_SERVER_IP}:25565 and ${FRP_SERVER_IP}:19132."
start_server

while true; do
    sleep "$POLL_INTERVAL_SECONDS" || true
    log_usage

    if ! kill -0 "$FRPC_PID" 2>/dev/null; then
        cat "$FRPC_LOG" || true
        if wait "$FRPC_PID" 2>/dev/null; then
            frpc_status=0
        else
            frpc_status=$?
        fi
        log "frpc exited with status $frpc_status; restarting from config."
        if ! start_frpc; then
            log "ERROR: frpc recovery failed."
            exit 1
        fi
        log "FRP proxies restored from config."
        notify_frp "$FRP_SERVER_IP"
    fi

    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        if wait "$SERVER_PID"; then
            server_status=0
        else
            server_status=$?
        fi
        if [[ "$server_status" -eq 0 ]]; then
            log "Paper stopped cleanly; watchdog exiting."
            exit 0
        fi
        log "Paper supervisor exited with status $server_status (possible crash/OOM); restarting it."
        start_server
    fi
done