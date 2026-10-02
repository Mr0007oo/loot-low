#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
SERVER_DIR="$ROOT_DIR/server"
PLAYIT_BIN="${PLAYIT_BIN:-$ROOT_DIR/playit}"
SERVER_LAUNCHER="${SERVER_LAUNCHER:-$SERVER_DIR/start.sh}"
PLAYIT_LOG="${PLAYIT_LOG:-$ROOT_DIR/playit.log}"
SERVER_LOG="${SERVER_LOG:-$SERVER_DIR/logs/server-session.log}"
WATCHDOG_LOG="${WATCHDOG_LOG:-$SERVER_DIR/logs/watchdog-health.log}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3)"
fi
POLL_INTERVAL_SECONDS="${WATCHDOG_INTERVAL_SECONDS:-30}"
SERVER_PID=""
PLAYIT_PID=""

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
    stop_process "$PLAYIT_PID"
    exit "$exit_status"
}

trap cleanup EXIT
trap 'exit 143' INT TERM

if [[ -z "${PLAYIT_SECRET_KEY:-}" ]]; then
    echo "ERROR: PLAYIT_SECRET_KEY is required for headless Playit startup." >&2
    exit 1
fi
if [[ ! -x "$PLAYIT_BIN" ]]; then
    echo "ERROR: Playit binary is missing or not executable: $PLAYIT_BIN" >&2
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

mkdir -p "$HOME/.config/playit_gg" /tmp/playit_runtime "$SERVER_DIR/logs"
printf 'secret = "%s"\n' "$PLAYIT_SECRET_KEY" >"$HOME/.config/playit_gg/playit.toml" || exit 1
chmod 600 "$HOME/.config/playit_gg/playit.toml" || exit 1

start_playit() {
    : >"$PLAYIT_LOG"
    XDG_RUNTIME_DIR=/tmp/playit_runtime "$PLAYIT_BIN" >"$PLAYIT_LOG" 2>&1 &
    PLAYIT_PID=$!
    log "Started Playit (pid=$PLAYIT_PID)."
}

verify_playit() {
    sleep 5
    if ! kill -0 "$PLAYIT_PID" 2>/dev/null; then
        if wait "$PLAYIT_PID"; then
            playit_status=0
        else
            playit_status=$?
        fi
        cat "$PLAYIT_LOG" || true
        log "ERROR: Playit exited during startup (status $playit_status)."
        return 1
    fi
    if grep -Fq 'playitd error: IPC error' "$PLAYIT_LOG"; then
        cat "$PLAYIT_LOG"
        log "ERROR: Playit reported an IPC error."
        return 1
    fi
    if ! grep -Eiq '(^|[^[:alpha:]])connected([^[:alpha:]]|$)|tunnel.*(ready|online)|assigned.*address' "$PLAYIT_LOG"; then
        cat "$PLAYIT_LOG"
        log "ERROR: Playit did not confirm a connection."
        return 1
    fi
    if ! grep -Eiq '(tcp|stream).{0,120}25565|25565.{0,120}(tcp|stream)' "$PLAYIT_LOG"; then
        cat "$PLAYIT_LOG"
        log "ERROR: Playit log does not confirm a TCP mapping to port 25565. Configure the Java tunnel in the Playit dashboard."
        return 1
    fi
    if ! grep -Eiq '(udp|datagram).{0,120}19132|19132.{0,120}(udp|datagram)' "$PLAYIT_LOG"; then
        cat "$PLAYIT_LOG"
        log "ERROR: Playit log does not confirm a UDP mapping to port 19132. Configure the Bedrock tunnel in the Playit dashboard."
        return 1
    fi
    cat "$PLAYIT_LOG"
    log "Verified Playit TCP 25565 and UDP 19132 mappings."
}

start_server() {
    "$SERVER_LAUNCHER" >>"$SERVER_LOG" 2>&1 &
    SERVER_PID=$!
    log "Started Paper supervisor (pid=$SERVER_PID)."
}

log_usage() {
    local java_pid java_usage server_children playit_usage host_memory
    java_pid=$(pgrep -f '[j]ava.*-jar paper[.]jar' | head -n 1 || true)
    java_usage=$(ps --no-headers -o %cpu=,rss= -p "${java_pid:-}" 2>/dev/null | tr -d '\n' || true)
    server_children=$(ps --no-headers -o pid=,comm=,%cpu=,rss= --ppid "$SERVER_PID" 2>/dev/null | tr '\n' ';' || true)
    playit_usage=$(ps --no-headers -o %cpu=,rss= -p "$PLAYIT_PID" 2>/dev/null | tr -d '\n' || true)
    host_memory=$(free -m 2>/dev/null | awk '/^Mem:/ { printf "used=%sMiB available=%sMiB", $3, $7 }' || true)
    log "Health sample: paper_pid=\"${java_pid:-not-running}\" paper_cpu_rss=\"${java_usage:-unavailable}\" server_children=\"${server_children:-none}\" playit_cpu_rss=\"${playit_usage:-unavailable}\" memory=\"${host_memory:-unavailable}\""
}

start_playit
if ! verify_playit; then
    exit 1
fi
start_server

while true; do
    sleep "$POLL_INTERVAL_SECONDS" || true
    log_usage

    if ! kill -0 "$PLAYIT_PID" 2>/dev/null; then
        if wait "$PLAYIT_PID"; then
            playit_status=0
        else
            playit_status=$?
        fi
        log "Playit exited with status $playit_status; restarting tunnel agent."
        start_playit
        if ! verify_playit; then
            exit 1
        fi
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