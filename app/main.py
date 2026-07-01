"""
Main entrypoint — wires together the scheduler, order manager, messaging,
and command interface, then runs the bot until interrupted.

Responsibilities:
  - Initialize the database.
  - Build the Messenger (iMessage) and wire its confirm_order_callback into
    the TradingScheduler so every strategy-driven BUY/SELL waits for a
    YES/NO reply before executing.
  - Start the APScheduler jobs (strategy scans, kill-switch checks, EOD
    report).
  - Poll for inbound commands (STATUS, PAUSE, RESUME, etc.) and reply via
    the Messenger.

Run with: python main.py
"""

from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

from alerts.messenger import Messenger
from commands.handler import CommandHandler
from config.loader import get as get_config
from db.models import init_db
from execution.order_manager import OrderManager
from monitoring import ledger
from scheduler.jobs import TradingScheduler

# How often to poll for inbound iMessage commands.
COMMAND_POLL_SECONDS = 10

PID_FILE = Path(__file__).resolve().parent / "data" / "bot.pid"


def _write_pid_file() -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def _remove_pid_file() -> None:
    PID_FILE.unlink(missing_ok=True)


def process_inbound_messages(
    messenger: Messenger,
    command_handler: CommandHandler,
    since: dt.datetime,
) -> dt.datetime:
    """Check for new inbound messages, handle each as a command, and reply.

    Returns the updated `since` timestamp (the timestamp of the most
    recent message processed, or the original `since` if none arrived).
    """
    messages = messenger.poll_new_messages(since)

    for msg in messages:
        since = max(since, msg.timestamp)
        reply = command_handler.handle(msg.text)
        if reply:
            messenger.send(reply)

    return since


def build_app() -> tuple[TradingScheduler, CommandHandler, Messenger]:
    init_db()

    messenger = Messenger()
    order_manager = OrderManager()
    scheduler = TradingScheduler(
        order_manager=order_manager,
        confirm_callback=messenger.confirm_order_callback,
        day_order_notify=messenger.send,
    )
    command_handler = CommandHandler(scheduler, instance_name=get_config("instance_name", "Bot"))

    return scheduler, command_handler, messenger


def run() -> None:
    scheduler, command_handler, messenger = build_app()

    instance = get_config("instance_name", "Bot")

    _write_pid_file()
    ledger.log_event(ledger.CATEGORY_SYSTEM, "Bot starting")
    messenger.send_alert(ledger.CATEGORY_SYSTEM, f"[{instance}] Auto-trading bot started.")

    scheduler.start()

    since = dt.datetime.now(dt.timezone.utc)
    try:
        while True:
            try:
                since = process_inbound_messages(messenger, command_handler, since)
            except Exception as exc:  # noqa: BLE001 - keep the loop alive
                ledger.log_event(ledger.CATEGORY_ERROR, "Error processing inbound messages", {"error": str(exc)})
            time.sleep(COMMAND_POLL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop()
        ledger.log_event(ledger.CATEGORY_SYSTEM, "Bot stopped")
        messenger.send_alert(ledger.CATEGORY_SYSTEM, f"[{instance}] Auto-trading bot stopped.")
        _remove_pid_file()


if __name__ == "__main__":
    run()
