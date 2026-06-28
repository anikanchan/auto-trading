"""
WhatsApp transport via Twilio.

Sending uses the Twilio Messages API. Receiving polls the same API for
inbound messages from the allowed sender — no public webhook required for
local/desktop deployment (see webhook/ for the AWS variant that uses a
Twilio webhook instead).

Both send_whatsapp and get_new_whatsapp_messages match the same interface
as the iMessage backend so Messenger can swap between them transparently.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from alerts import IncomingMessage
from config.secrets import get_secret

if TYPE_CHECKING:
    from twilio.rest import Client as TwilioClient


def _whatsapp_addr(number: str) -> str:
    """Ensure number has the whatsapp: URI prefix Twilio expects."""
    return number if number.startswith("whatsapp:") else f"whatsapp:{number}"


def _client() -> TwilioClient:
    from twilio.rest import Client

    return Client(get_secret("twilio-account-sid"), get_secret("twilio-auth-token"))


def send_whatsapp(to: str, message: str) -> None:
    """Send a WhatsApp message to `to` via Twilio.

    Raises twilio.base.exceptions.TwilioRestException on API errors.
    """
    _client().messages.create(
        from_=_whatsapp_addr(get_secret("twilio-whatsapp-number")),
        to=_whatsapp_addr(to),
        body=message,
    )


def get_new_whatsapp_messages(since: dt.datetime, allowed_sender: str) -> list[IncomingMessage]:
    """Return inbound WhatsApp messages from `allowed_sender` received after `since`.

    Polls the Twilio Messages API — no webhook needed. Twilio returns messages
    in reverse-chronological order; we return them oldest-first to match the
    iMessage backend's ordering.
    """
    if since.tzinfo is None:
        since = since.replace(tzinfo=dt.timezone.utc)

    twilio_number = _whatsapp_addr(get_secret("twilio-whatsapp-number"))
    from_number = _whatsapp_addr(allowed_sender)

    messages = _client().messages.list(
        to=twilio_number,
        from_=from_number,
        date_sent_after=since,
    )

    result = []
    for msg in reversed(messages):  # oldest first
        ts = msg.date_sent
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        if ts > since:
            result.append(
                IncomingMessage(
                    text=msg.body or "",
                    sender=allowed_sender,
                    timestamp=ts,
                    is_from_me=False,
                )
            )

    return result
