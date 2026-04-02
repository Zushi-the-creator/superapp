#!/bin/bash
# Frontend watchdog — restarts dev server if it crashes
# Usage: nohup ./keep-alive.sh &

PORT=3000
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/keep-alive.log"

echo "[$(date)] Watchdog started for frontend on port $PORT" >> "$LOG"

while true; do
    # Check if anything is listening on port 3000
    if ! lsof -ti:$PORT >/dev/null 2>&1; then
        echo "[$(date)] Port $PORT is DOWN — restarting frontend..." >> "$LOG"

        # Clean stale .next cache (the usual cause of 500 errors)
        rm -rf "$DIR/.next"

        # Start dev server
        cd "$DIR" && npm run dev -- -p $PORT >> "$LOG" 2>&1 &
        DEV_PID=$!
        echo "[$(date)] Started dev server (PID $DEV_PID)" >> "$LOG"

        # Wait for it to come up (max 30s)
        for i in $(seq 1 30); do
            sleep 1
            if lsof -ti:$PORT >/dev/null 2>&1; then
                echo "[$(date)] Frontend is UP on port $PORT" >> "$LOG"
                break
            fi
        done
    fi

    # Check every 30 seconds
    sleep 30
done
