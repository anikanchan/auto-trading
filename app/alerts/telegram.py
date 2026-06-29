"""
Telegram transport via the Bot API.

Sending uses POST /sendMessage. Receiving polls GET /getUpdates with an
offset so each update is processed exactly once. No webhook or Twilio
account needed — just a bot token from @BotFather and your chat ID.

Both send_telegram and get_new_telegram_messages match the same interface
as the iMessage and WhatsApp backends so Messenger can swap between them
transparently.
"""

from __future__ import annotations

import datetime as dt

import requests

from alerts import IncomingMessage
from config.secrets import get_secret

_API_BASE = "https://api.telegram.org"

# Tracks the highest update_id seen so getUpdates only returns new messages.
# Resets on process restart, but the `since` timestamp filter handles any
# duplicates that come back before the offset advances.
_last_update_id: int | None = None


def _url(method: str) -> str:
    return f"{_API_BASE}/bot{get_secret('telegram-bot-token')}/{method}"


def send_telegram(to: str, message: str) -> None:
    """Send a Telegram message to `to` (chat_id) via the Bot API.

    Raises requests.HTTPError on API errors.
    """
    response = requests.post(
        _url("sendMessage"),
        json={"chat_id": to, "text": message},
        timeout=10,
    )
    response.raise_for_status()


def get_new_telegram_messages(since: dt.datetime, allowed_sender: str) -> list[IncomingMessage]:
    """Return inbound Telegram messages from `allowed_sender` (chat_id) after `since`.

    Uses getUpdates with offset tracking to avoid re-processing messages.
    Returns messages in chronological order (oldest first).
    """
    global _last_update_id

    if since.tzinfo is None:
        since = since.replace(tzinfo=dt.timezone.utc)

    params: dict = {"timeout": 0, "allowed_updates": ["message"]}
    if _last_update_id is not None:
        params["offset"] = _last_update_id + 1

    response = requests.get(_url("getUpdates"), params=params, timeout=15)
    response.raise_for_status()
    updates = response.json().get("result", [])

    if updates:
        _last_update_id = updates[-1]["update_id"]

    result = []
    for update in updates:
        msg = update.get("message")
        if not msg:
            continue

        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != str(allowed_sender):
            continue

        ts = dt.datetime.fromtimestamp(msg["date"], tz=dt.timezone.utc)
        if ts <= since:
            continue

        result.append(
            IncomingMessage(
                text=msg.get("text") or "",
                sender=allowed_sender,
                timestamp=ts,
                is_from_me=False,
            )
        )

    return result
