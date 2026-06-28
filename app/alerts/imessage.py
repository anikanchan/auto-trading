"""
Low-level iMessage transport (Mac only).

Sending uses AppleScript via `osascript` (Apple end-to-end encrypted,
automatic for iMessage/blue-bubble contacts). Receiving polls the local
Messages database (`~/Library/Messages/chat.db`) for new inbound messages
from the allowed sender.

Both the subprocess runner and the database path are injectable so this
module can be unit tested without Messages.app or a real chat.db.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import subprocess
from pathlib import Path
from typing import Callable

from alerts import IncomingMessage  # noqa: F401 — re-exported for backward compat

DEFAULT_CHAT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"

# Apple's "Mac absolute time" epoch is 2001-01-01 00:00:00 UTC.
APPLE_EPOCH = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)


def datetime_to_apple_time(timestamp: dt.datetime) -> int:
    """Convert a timezone-aware datetime to Apple's nanosecond epoch."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
    delta = timestamp - APPLE_EPOCH
    return int(delta.total_seconds() * 1_000_000_000)


def apple_time_to_datetime(apple_time: int) -> dt.datetime:
    """Convert Apple's nanosecond epoch to a timezone-aware UTC datetime."""
    return APPLE_EPOCH + dt.timedelta(seconds=apple_time / 1_000_000_000)


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def send_imessage(
    to: str,
    message: str,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Send an iMessage to `to` (phone number or email) via AppleScript.

    Raises subprocess.CalledProcessError if `osascript` fails (e.g. the
    recipient isn't an iMessage contact and Messages.app can't fall back).
    """
    escaped_message = _escape_applescript(message)
    escaped_to = _escape_applescript(to)
    script = (
        'tell application "Messages"\n'
        f'  set targetService to 1st service whose service type = iMessage\n'
        f'  set targetBuddy to buddy "{escaped_to}" of targetService\n'
        f'  send "{escaped_message}" to targetBuddy\n'
        "end tell"
    )
    runner(["osascript", "-e", script], check=True, capture_output=True, text=True)


def get_new_messages(
    since: dt.datetime,
    allowed_sender: str,
    chat_db_path: Path | str = DEFAULT_CHAT_DB_PATH,
) -> list[IncomingMessage]:
    """Return inbound messages from `allowed_sender` received after `since`.

    Opens chat.db read-only (Messages.app keeps it open/locked). Messages
    from other senders are ignored entirely (per the spec, only the
    registered phone number is accepted).
    """
    since_apple_time = datetime_to_apple_time(since)
    uri = f"file:{Path(chat_db_path)}?mode=ro"

    conn = sqlite3.connect(uri, uri=True)
    try:
        cursor = conn.execute(
            """
            SELECT message.text, handle.id, message.date, message.is_from_me
            FROM message
            JOIN handle ON message.handle_id = handle.ROWID
            WHERE message.date > ?
              AND handle.id = ?
              AND message.is_from_me = 0
              AND message.text IS NOT NULL
            ORDER BY message.date ASC
            """,
            (since_apple_time, allowed_sender),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    return [
        IncomingMessage(
            text=text,
            sender=sender,
            timestamp=apple_time_to_datetime(date),
            is_from_me=bool(is_from_me),
        )
        for text, sender, date, is_from_me in rows
    ]
