#!/usr/bin/env bash
#
# Linux setup: install cron jobs to start and stop the trading bot
# on weekday market hours (all times US/Eastern, DST-aware).
#
# Schedule:
#   9:05 AM ET Mon-Fri  — start the bot (market opens 9:30 AM ET)
#   4:30 PM ET Mon-Fri  — graceful bot stop
#
# Run once from the repo root or app/ directory:
#   chmod +x scripts/cron_setup.sh
#   ./scripts/cron_setup.sh
#
# To remove the jobs later:
#   crontab -e  (delete the auto-trading block)
#
# Requirements:
#   - venv must exist at app/venv (run: python3 -m venv venv && pip install -r requirements.txt)

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${APP_DIR}/venv/bin/python"
SHUTDOWN="${APP_DIR}/scripts/shutdown.sh"

if [ ! -f "$PYTHON" ]; then
    echo "Error: venv not found at ${APP_DIR}/venv"
    echo "Run: python3 -m venv venv && pip install -r requirements.txt"
    exit 1
fi

mkdir -p "${APP_DIR}/data"

START_JOB="5 9 * * 1-5 ${PYTHON} ${APP_DIR}/main.py >> ${APP_DIR}/data/bot.log 2>> ${APP_DIR}/data/bot.err"
SHUTDOWN_JOB="30 16 * * 1-5 ${SHUTDOWN} >> ${APP_DIR}/data/shutdown.log 2>&1"

# Rebuild crontab: strip any existing auto-trading block, append the new one.
(
    crontab -l 2>/dev/null | grep -vF "${APP_DIR}" | grep -vF "auto-trading bot" || true
    echo ""
    echo "# --- auto-trading bot (managed by scripts/cron_setup.sh) ---"
    echo "TZ=America/New_York"
    echo "${START_JOB}"
    echo "${SHUTDOWN_JOB}"
    echo "# --- end auto-trading bot ---"
) | crontab -

echo "Installed cron jobs (all times US/Eastern):"
echo "  Start:    ${START_JOB}"
echo "  Stop:     ${SHUTDOWN_JOB}"
echo ""
echo "Current crontab:"
crontab -l
