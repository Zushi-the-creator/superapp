#!/bin/bash
# Health check script - ensures all services are running
# Run: bash health_check.sh
# Or cron: */5 * * * * bash /Users/igalozik/PycharmProjects/superapp/health_check.sh

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="/tmp/superapp_health.log"

check_and_restart() {
    local name="$1"
    local port="$2"
    local start_cmd="$3"
    local log_file="$4"

    if curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://localhost:$port" 2>/dev/null | grep -q "200"; then
        echo "$(date): $name on port $port - OK" >> "$LOG"
    else
        echo "$(date): $name on port $port - DOWN, restarting..." >> "$LOG"
        # Kill any zombie process on the port
        lsof -ti :"$port" | xargs kill -9 2>/dev/null
        sleep 1
        eval "$start_cmd" > "$log_file" 2>&1 &
        sleep 5
        if curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://localhost:$port" 2>/dev/null | grep -q "200"; then
            echo "$(date): $name restarted successfully" >> "$LOG"
        else
            echo "$(date): $name FAILED to restart!" >> "$LOG"
        fi
    fi
}

# Backend (FastAPI on port 8000)
check_and_restart "Backend" 8000 \
    "cd $DIR/backend && python3 main.py" \
    "/tmp/backend.log"

# Frontend main (Next.js on port 3000)
check_and_restart "Frontend" 3000 \
    "cd $DIR/frontend && npm exec next dev -- --port 3000" \
    "/tmp/frontend_3000.log"

# Frontend staging (Next.js on port 3001)
check_and_restart "Staging" 3001 \
    "cd $DIR/frontend && npm exec next dev -- --port 3001" \
    "/tmp/frontend_3001.log"
