#!/usr/bin/env bash
#
# Shutdown job: gracefully stops the trading bot and powers off the machine.
# Scheduled via cron (see scripts/cron_setup.sh) at the configured
# schedule.shutdown_time (default 4:30 PM ET, after the 4:25 PM EOD report).
#
# Usage: ./scripts/shutdown.sh
#
# Requires passwordless sudo for systemctl poweroff (add via `sudo visudo`):
#   <your-username> ALL=(ALL) NOPASSWD: /usr/bin/systemctl poweroff, /usr/bin/systemctl poweroff -i

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Ask the running bot to stop cleanly (it logs "Bot stopped" and sends a
# shutdown alert via iMessage before exiting).
PID_FILE="${APP_DIR}/data/bot.pid"
if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE")"
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping bot (pid $PID)..."
        kill -INT "$PID"
        # Give it a few seconds to log shutdown / send the iMessage alert.
        for _ in $(seq 1 10); do
            kill -0 "$PID" 2>/dev/null || break
            sleep 1
        done
    fi
    rm -f "$PID_FILE"
fi

echo "Shutting down..."
sudo systemctl poweroff -i
