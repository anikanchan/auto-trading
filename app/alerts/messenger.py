"""
Messenger — high-level alerting and confirmation flow on top of iMessage.

Provides:
  - `send_alert(category, message)`: fire-and-forget notification (trade
    executed, risk limit triggered, system error, EOD report, etc.)
  - `wait_for_confirmation(prompt)`: send a message and poll for a YES/NO
    reply within the configured timeout (default 5 minutes); used as the
    `confirm_callback` for OrderManager.process_signal().

Both `send_fn` and `poll_fn` are injectable so this can be unit tested
without Messages.app, and so the AWS build can swap in a Twilio
WhatsApp-based Messenger with the same interface.
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Callable

from alerts import IncomingMessage
from config.loader import get as get_config
from config.secrets import get_secret
from monitoring import ledger
from risk.risk_manager import OrderRequest
from strategies.base import Signal

SendFn = Callable[[str, str], None]
PollFn = Callable[[dt.datetime, str], list[IncomingMessage]]


def _default_send_fn() -> SendFn:
    channel = get_config("messaging.channel", "imessage")
    if channel == "whatsapp":
        from alerts.whatsapp import send_whatsapp
        return send_whatsapp
    from alerts.imessage import send_imessage
    return send_imessage


def _default_poll_fn() -> PollFn:
    channel = get_config("messaging.channel", "imessage")
    if channel == "whatsapp":
        from alerts.whatsapp import get_new_whatsapp_messages
        return get_new_whatsapp_messages
    from alerts.imessage import get_new_messages
    return get_new_messages


class Messenger:
    def __init__(
        self,
        allowed_number: str | None = None,
        send_fn: SendFn | None = None,
        poll_fn: PollFn | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.timezone.utc),
    ) -> None:
        self.allowed_number = allowed_number or get_secret("allowed-phone-number")
        self._send_fn = send_fn or _default_send_fn()
        self._poll_fn = poll_fn or _default_poll_fn()
        self._sleep_fn = sleep_fn
        self._now_fn = now_fn

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send(self, message: str) -> None:
        self._send_fn(self.allowed_number, message)

    def poll_new_messages(self, since: dt.datetime) -> list[IncomingMessage]:
        """Return inbound messages from the allowed sender received after `since`."""
        return self._poll_fn(since, self.allowed_number)

    def send_alert(self, category: str, message: str, details: dict | None = None) -> None:
        """Send a notification and log it to the transaction ledger."""
        self.send(message)
        ledger.log_event(category, message, details)

    def send_trade_executed(self, side: str, quantity: float, symbol: str, price: float, strategy: str) -> None:
        self.send_alert(
            ledger.CATEGORY_ORDER,
            f"Executed: {side.upper()} {quantity:g} {symbol} @ ${price:.2f} ({strategy})",
            {"side": side, "quantity": quantity, "symbol": symbol, "price": price, "strategy": strategy},
        )

    def send_risk_alert(self, message: str, details: dict | None = None) -> None:
        self.send_alert(ledger.CATEGORY_RISK, f"Risk alert: {message}", details)

    def send_error_alert(self, message: str, details: dict | None = None) -> None:
        self.send_alert(ledger.CATEGORY_ERROR, f"Error: {message}", details)

    def send_eod_report(self, report_text: str) -> None:
        self.send_alert(ledger.CATEGORY_SYSTEM, report_text)

    # ------------------------------------------------------------------
    # Confirmation flow
    # ------------------------------------------------------------------

    def wait_for_confirmation(self, prompt: str, timeout_minutes: float | None = None, poll_seconds: float = 5.0) -> bool:
        """Send `prompt` and poll for a YES/NO reply.

        Returns True if the reply (case-insensitive) is "YES", False if
        "NO" or if the timeout elapses with no (recognized) reply. Any
        other replies are ignored and polling continues.
        """
        if timeout_minutes is None:
            timeout_minutes = float(get_config("messaging.confirmation_timeout_minutes", 5))

        self.send(prompt)
        ledger.log_event(ledger.CATEGORY_COMMAND, f"Confirmation requested: {prompt}")

        start = self._now_fn()
        deadline = start + dt.timedelta(minutes=timeout_minutes)
        since = start

        while self._now_fn() < deadline:
            messages = self._poll_fn(since, self.allowed_number)
            for msg in messages:
                since = max(since, msg.timestamp)
                reply = msg.text.strip().upper()
                if reply == "YES":
                    ledger.log_event(ledger.CATEGORY_COMMAND, "Confirmation received: YES")
                    return True
                if reply == "NO":
                    ledger.log_event(ledger.CATEGORY_COMMAND, "Confirmation received: NO")
                    return False
            self._sleep_fn(poll_seconds)

        ledger.log_event(ledger.CATEGORY_COMMAND, f"Confirmation timed out after {timeout_minutes} minutes")
        return False

    def confirm_order_callback(self, signal: Signal, order: OrderRequest) -> bool:
        """Build a confirm_callback compatible with
        OrderManager.process_signal()."""
        prompt = (
            f"{order.side.upper()} {order.quantity:g} {order.symbol} @ ~${order.price:.2f} "
            f"({signal.strategy}: {signal.reason}) — reply YES to confirm, NO to skip"
        )
        return self.wait_for_confirmation(prompt)
