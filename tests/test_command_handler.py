import pytest

from commands.handler import CommandHandler
from db.models import Trade, get_session, init_db
from execution.order_manager import OrderManager
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


@pytest.fixture
def handler(isolated_db, fake_market_data):
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
    return CommandHandler(scheduler)


def test_help(handler):
    response = handler.handle("HELP")
    assert "STATUS" in response
    assert "BUY" in response


def test_unknown_message_returns_empty(handler):
    response = handler.handle("hello there")
    assert response == ""


def test_status_reports_state(handler):
    response = handler.handle("STATUS")
    assert "RUNNING" in response
    assert "Equity: $100,000.00" in response


def test_pause_and_resume(handler):
    response = handler.handle("PAUSE")
    assert "paused" in response.lower()
    assert handler.scheduler.paused is True

    status = handler.handle("STATUS")
    assert "PAUSED" in status

    response = handler.handle("RESUME")
    assert "resumed" in response.lower()
    assert handler.scheduler.paused is False


def test_flatten_calls_broker(handler):
    response = handler.handle("FLATTEN")
    assert "Closing all open positions" in response


def test_stop_adds_symbol(handler):
    response = handler.handle("STOP AAPL")
    assert "AAPL" in response
    assert "AAPL" in handler.scheduler.stopped_symbols


def test_risk_command_updates_param(handler):
    response = handler.handle("RISK MAXPOS 3%")
    assert "3.0" in response
    assert handler.order_manager.risk_manager.max_position_pct == 3.0


def test_risk_command_unknown_param(handler):
    response = handler.handle("RISK FOOBAR 3")
    assert "Unknown risk parameter" in response


def test_buy_then_yes_submits_order(handler):
    response = handler.handle("BUY AAPL 10")
    assert "reply YES to confirm" in response
    assert handler.pending_order is not None

    response = handler.handle("YES")
    assert "Order submitted" in response
    assert handler.pending_order is None
    assert handler.order_manager.broker.submitted_orders[0]["qty"] == 10


def test_buy_then_no_cancels_order(handler):
    handler.handle("BUY AAPL 10")
    response = handler.handle("NO")
    assert response == "Order cancelled."
    assert handler.pending_order is None
    assert handler.order_manager.broker.submitted_orders == []


def test_yes_with_no_pending_order(handler):
    response = handler.handle("YES")
    assert "No pending order" in response


def test_buy_with_max_below_current_price_rejected(handler, fake_market_data):
    fake_market_data.price = 100.0
    response = handler.handle("BUY AAPL 10 MAX 90.00")
    assert response.startswith("Rejected:")
    assert handler.pending_order is None


def test_history_report_includes_summary(handler):
    with get_session() as session:
        session.add(
            Trade(
                symbol="AAPL",
                side="buy",
                quantity=10,
                entry_price=100.0,
                exit_price=110.0,
                strategy="sma_crossover",
                status="closed",
                pnl=100.0,
            )
        )
        session.commit()

    response = handler.handle("HISTORY")
    assert "Total trades: 1" in response
    assert "Total realized P&L: $100.00" in response


def test_report_calls_scheduler_eod(handler):
    response = handler.handle("REPORT")
    assert "EOD Report" in response
