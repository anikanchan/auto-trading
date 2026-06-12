import datetime as dt

import pytest

from alerts.imessage import IncomingMessage
from alerts.messenger import Messenger
from commands.handler import CommandHandler
from db.models import init_db
from execution.order_manager import OrderManager
from main import process_inbound_messages
from risk.risk_manager import RiskManager
from scheduler.jobs import TradingScheduler
from tests.test_order_manager import FakeBroker


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.models.get_db_path", lambda: tmp_path / "test_trading.db")
    init_db()


@pytest.fixture
def fake_market_data(monkeypatch):
    class FakeMarketData:
        price = 100.0

        def get_latest_price(self, symbol):
            return FakeMarketData.price

    monkeypatch.setattr("data.market_data.MarketData", FakeMarketData)
    return FakeMarketData


def test_process_inbound_messages_runs_command_and_replies(isolated_db, fake_market_data):
    risk_manager = RiskManager(
        params={
            "max_portfolio_deployed_pct": 50,
            "max_position_pct": 5,
            "daily_loss_kill_switch_pct": -2,
            "stop_loss_pct": -1.5,
            "max_concurrent_positions": 10,
        }
    )
    broker = FakeBroker(cash=100_000.0, portfolio_value=100_000.0, equity=100_000.0)
    order_manager = OrderManager(broker=broker, risk_manager=risk_manager)
    scheduler = TradingScheduler(order_manager=order_manager, market_data=fake_market_data(), strategies=[])
    command_handler = CommandHandler(scheduler)

    base = dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc)
    incoming = [IncomingMessage(text="STATUS", sender="+15555550123", timestamp=base + dt.timedelta(seconds=1), is_from_me=False)]

    sent = []
    messenger = Messenger(
        allowed_number="+15555550123",
        send_fn=lambda to, msg: sent.append((to, msg)),
        poll_fn=lambda since, sender: incoming,
        sleep_fn=lambda s: None,
        now_fn=lambda: base,
    )

    new_since = process_inbound_messages(messenger, command_handler, base)

    assert new_since == base + dt.timedelta(seconds=1)
    assert len(sent) == 1
    assert "RUNNING" in sent[0][1]


def test_process_inbound_messages_ignores_unknown_with_no_reply(isolated_db, fake_market_data):
    risk_manager = RiskManager()
    broker = FakeBroker()
    order_manager = OrderManager(broker=broker, risk_manager=risk_manager)
    scheduler = TradingScheduler(order_manager=order_manager, market_data=fake_market_data(), strategies=[])
    command_handler = CommandHandler(scheduler)

    base = dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc)
    incoming = [IncomingMessage(text="hello there", sender="+15555550123", timestamp=base + dt.timedelta(seconds=1), is_from_me=False)]

    sent = []
    messenger = Messenger(
        allowed_number="+15555550123",
        send_fn=lambda to, msg: sent.append((to, msg)),
        poll_fn=lambda since, sender: incoming,
        sleep_fn=lambda s: None,
        now_fn=lambda: base,
    )

    process_inbound_messages(messenger, command_handler, base)

    assert sent == []


def test_process_inbound_messages_no_new_messages_keeps_since(isolated_db, fake_market_data):
    risk_manager = RiskManager()
    broker = FakeBroker()
    order_manager = OrderManager(broker=broker, risk_manager=risk_manager)
    scheduler = TradingScheduler(order_manager=order_manager, market_data=fake_market_data(), strategies=[])
    command_handler = CommandHandler(scheduler)

    base = dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc)

    messenger = Messenger(
        allowed_number="+15555550123",
        send_fn=lambda to, msg: None,
        poll_fn=lambda since, sender: [],
        sleep_fn=lambda s: None,
        now_fn=lambda: base,
    )

    new_since = process_inbound_messages(messenger, command_handler, base)
    assert new_since == base
