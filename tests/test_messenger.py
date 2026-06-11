import datetime as dt

import pytest

from alerts.imessage import IncomingMessage
from alerts.messenger import Messenger
from db.models import init_db
from monitoring import ledger
from risk.risk_manager import OrderRequest
from strategies.base import Signal, SignalAction


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.models.get_db_path", lambda: tmp_path / "test_trading.db")
    init_db()


class FakeClock:
    def __init__(self, start: dt.datetime):
        self.now = start
        self.sleeps = []

    def now_fn(self):
        return self.now

    def sleep_fn(self, seconds):
        self.sleeps.append(seconds)
        self.now += dt.timedelta(seconds=seconds)


def make_messenger(isolated_db, replies=None, clock=None):
    sent = []

    def send_fn(to, message):
        sent.append((to, message))

    replies = replies or []

    def poll_fn(since, allowed_sender):
        # Return all queued replies on first poll, none afterwards
        result = replies[:]
        replies.clear()
        return result

    clock = clock or FakeClock(dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc))

    messenger = Messenger(
        allowed_number="+15555550123",
        send_fn=send_fn,
        poll_fn=poll_fn,
        sleep_fn=clock.sleep_fn,
        now_fn=clock.now_fn,
    )
    return messenger, sent, clock


def test_send_alert_logs_to_ledger(isolated_db):
    messenger, sent, _ = make_messenger(isolated_db)

    messenger.send_alert(ledger.CATEGORY_SYSTEM, "Test alert")

    assert sent == [("+15555550123", "Test alert")]
    events = ledger.get_events()
    assert any(e.message == "Test alert" for e in events)


def test_wait_for_confirmation_yes(isolated_db):
    clock = FakeClock(dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc))
    reply = IncomingMessage(text="YES", sender="+15555550123", timestamp=clock.now + dt.timedelta(seconds=1), is_from_me=False)
    messenger, sent, clock = make_messenger(isolated_db, replies=[reply], clock=clock)

    result = messenger.wait_for_confirmation("BUY 10 AAPL @ ~$150 - reply YES to confirm", timeout_minutes=5)

    assert result is True
    assert sent[0][1] == "BUY 10 AAPL @ ~$150 - reply YES to confirm"


def test_wait_for_confirmation_no(isolated_db):
    clock = FakeClock(dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc))
    reply = IncomingMessage(text="no", sender="+15555550123", timestamp=clock.now + dt.timedelta(seconds=1), is_from_me=False)
    messenger, sent, clock = make_messenger(isolated_db, replies=[reply], clock=clock)

    result = messenger.wait_for_confirmation("SELL 10 AAPL @ ~$150", timeout_minutes=5)

    assert result is False


def test_wait_for_confirmation_timeout(isolated_db):
    clock = FakeClock(dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc))
    messenger, sent, clock = make_messenger(isolated_db, replies=[], clock=clock)

    result = messenger.wait_for_confirmation("BUY 10 AAPL @ ~$150", timeout_minutes=5, poll_seconds=60)

    assert result is False
    events = ledger.get_events()
    assert any("timed out" in e.message for e in events)


def test_confirm_order_callback_builds_prompt(isolated_db):
    clock = FakeClock(dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc))
    reply = IncomingMessage(text="YES", sender="+15555550123", timestamp=clock.now + dt.timedelta(seconds=1), is_from_me=False)
    messenger, sent, clock = make_messenger(isolated_db, replies=[reply], clock=clock)

    signal = Signal(symbol="AAPL", action=SignalAction.BUY, reason="crossover", strategy="sma_crossover", price=150.0)
    order = OrderRequest(symbol="AAPL", side="buy", quantity=10, price=150.0)

    result = messenger.confirm_order_callback(signal, order)

    assert result is True
    assert "BUY 10 AAPL" in sent[0][1]
    assert "sma_crossover" in sent[0][1]


def test_send_trade_executed(isolated_db):
    messenger, sent, _ = make_messenger(isolated_db)
    messenger.send_trade_executed("buy", 10, "AAPL", 150.0, "sma_crossover")
    assert "Executed: BUY 10 AAPL @ $150.00" in sent[0][1]
