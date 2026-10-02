#!/usr/bin/env bash
set -uo pipefail

cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

if ! command -v java >/dev/null 2>&1; then
    echo "ERROR: Java is not installed or is not on PATH." >&2
    exit 1
fi

java_version=$(java -version 2>&1)
java_major=$(printf '%s\n' "$java_version" | sed -nE 's/.*version "([0-9]+).*/\1/p' | head -n 1)
if [[ "$java_major" != "21" ]]; then
    echo "ERROR: Java 21 is required; found: ${java_version%%$'\n'*}" >&2
    exit 1
fi

if [[ ! -s paper.jar ]]; then
    echo "ERROR: server/paper.jar is missing or empty. Run scripts/download_deps.py first." >&2
    exit 1
fi

if [[ -z "${RCON_PASSWORD:-}" ]]; then
    echo "ERROR: RCON_PASSWORD is required; refusing to start without RCON authentication." >&2
    exit 1
fi
if [[ "$RCON_PASSWORD" == *$'\n'* ]]; then
    echo "ERROR: RCON_PASSWORD must not contain newlines." >&2
    exit 1
fi

escaped_rcon_password=${RCON_PASSWORD//\\/\\\\}
escaped_rcon_password=${escaped_rcon_password//&/\\&}
escaped_rcon_password=${escaped_rcon_password//|/\\|}
sed -i "s|^rcon.password=.*|rcon.password=${escaped_rcon_password}|" server.properties

printf 'eula=true\n' > eula.txt

server_pid=""
stop_server() {
    if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
        echo "[$(date -Is)] Shutdown requested; forwarding SIGTERM to Paper."
        kill -TERM "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    exit 143
}
trap stop_server INT TERM

restart_count=0
max_restarts=3
while true; do
    echo "[$(date -Is)] Starting Paper 1.21.1 (restart ${restart_count}/${max_restarts})."
    java -Xms4000M -Xmx5120M \
        -XX:+UseG1GC \
        -XX:+ParallelRefProcEnabled \
        -XX:MaxGCPauseMillis=200 \
        -XX:+UnlockExperimentalVMOptions \
        -XX:+DisableExplicitGC \
        -XX:+AlwaysPreTouch \
        -XX:G1NewSizePercent=30 \
        -XX:G1MaxNewSizePercent=40 \
        -XX:G1HeapRegionSize=8M \
        -XX:G1ReservePercent=15 \
        -XX:G1HeapWastePercent=5 \
        -XX:G1MixedGCCountTarget=4 \
        -XX:InitiatingHeapOccupancyPercent=15 \
        -XX:G1MixedGCLiveThresholdPercent=90 \
        -XX:G1RSetUpdatingPauseTimePercent=5 \
        -XX:SurvivorRatio=8 \
        -XX:+UseStringDeduplication \
        -jar paper.jar --nogui &
    server_pid=$!

    if wait "$server_pid"; then
        exit_code=0
    else
        exit_code=$?
    fi
    server_pid=""

    if [[ "$exit_code" -eq 0 ]]; then
        echo "[$(date -Is)] Paper stopped cleanly."
        exit 0
    fi

    echo "[$(date -Is)] Paper crashed with exit code ${exit_code}." >&2
    if [[ "$restart_count" -ge "$max_restarts" ]]; then
        echo "[$(date -Is)] Restart limit (${max_restarts}) reached; exiting." >&2
        exit "$exit_code"
    fi

    restart_count=$((restart_count + 1))
    echo "[$(date -Is)] Restarting in 5 seconds (${restart_count}/${max_restarts})." >&2
    sleep 5
done