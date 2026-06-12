import pytest

from db.models import Trade, get_session, init_db
from execution.alpaca_broker import AccountInfo
from execution.order_manager import OrderManager
from risk.risk_manager import RiskManager
from strategies.base import Signal, SignalAction


class FakeBroker:
    """In-memory stand-in for AlpacaBroker."""

    def __init__(self, cash=100_000.0, portfolio_value=100_000.0, equity=100_000.0, positions=None):
        self.cash = cash
        self.portfolio_value = portfolio_value
        self.equity = equity
        self.positions = positions or []
        self.submitted_orders = []
        self._next_order_id = 1
        self.mode = "paper"
        self.flatten_called = False

    def flatten_all_positions(self) -> None:
        self.flatten_called = True
        self.positions = []

    def get_account(self) -> AccountInfo:
        return AccountInfo(
            account_id="test-account",
            status="ACTIVE",
            cash=self.cash,
            portfolio_value=self.portfolio_value,
            buying_power=self.cash,
            equity=self.equity,
        )

    def get_positions(self) -> list[dict]:
        return self.positions

    def submit_market_order(self, symbol, qty, side):
        return self._submit(symbol, qty, side, order_type="market", limit_price=None)

    def submit_limit_order(self, symbol, qty, side, limit_price):
        return self._submit(symbol, qty, side, order_type="limit", limit_price=limit_price)

    def _submit(self, symbol, qty, side, order_type, limit_price):
        order = {
            "id": f"order-{self._next_order_id}",
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "type": order_type,
            "status": "filled",
            "limit_price": limit_price,
        }
        self._next_order_id += 1
        self.submitted_orders.append(order)
        return order


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.models.get_db_path", lambda: tmp_path / "test_trading.db")
    init_db()


@pytest.fixture
def risk_manager():
    return RiskManager(
        params={
            "max_portfolio_deployed_pct": 50,
            "max_position_pct": 5,
            "daily_loss_kill_switch_pct": -2,
            "stop_loss_pct": -1.5,
            "max_concurrent_positions": 10,
        }
    )


def test_hold_signal_logged_and_no_order(isolated_db, risk_manager):
    broker = FakeBroker()
    manager = OrderManager(broker=broker, risk_manager=risk_manager)

    signal = Signal(symbol="AAPL", action=SignalAction.HOLD, reason="no signal", strategy="test")
    result = manager.process_signal(signal)

    assert result["status"] == "hold"
    assert broker.submitted_orders == []


def test_buy_signal_submits_order(isolated_db, risk_manager):
    broker = FakeBroker(cash=100_000.0, portfolio_value=100_000.0, equity=100_000.0)
    manager = OrderManager(broker=broker, risk_manager=risk_manager)

    signal = Signal(symbol="AAPL", action=SignalAction.BUY, reason="crossover", strategy="sma_crossover", price=50.0)
    result = manager.process_signal(signal)

    assert result["status"] == "submitted"
    assert len(broker.submitted_orders) == 1
    order = broker.submitted_orders[0]
    assert order["symbol"] == "AAPL"
    assert order["side"] == "buy"
    # 5% of 100,000 / $50 = 100 shares
    assert order["qty"] == 100

    with get_session() as session:
        trades = session.query(Trade).all()
        assert len(trades) == 1
        assert trades[0].status == "open"
        assert trades[0].symbol == "AAPL"


def test_sell_signal_with_no_position_is_skipped(isolated_db, risk_manager):
    broker = FakeBroker()
    manager = OrderManager(broker=broker, risk_manager=risk_manager)

    signal = Signal(symbol="AAPL", action=SignalAction.SELL, reason="crossover", strategy="sma_crossover", price=50.0)
    result = manager.process_signal(signal)

    assert result["status"] == "skipped"
    assert broker.submitted_orders == []


def test_sell_signal_closes_position_and_records_pnl(isolated_db, risk_manager):
    broker = FakeBroker(
        cash=95_000.0,
        portfolio_value=100_000.0,
        equity=100_000.0,
        positions=[{"symbol": "AAPL", "qty": 100, "side": "long", "avg_entry_price": 50.0,
                     "current_price": 55.0, "market_value": 5500.0, "unrealized_pl": 500.0,
                     "unrealized_plpc": 0.1}],
    )
    manager = OrderManager(broker=broker, risk_manager=risk_manager)

    # Pre-create the open trade as if the BUY happened earlier
    with get_session() as session:
        session.add(Trade(symbol="AAPL", side="buy", quantity=100, entry_price=50.0, strategy="sma_crossover"))
        session.commit()

    signal = Signal(symbol="AAPL", action=SignalAction.SELL, reason="crossover down", strategy="sma_crossover", price=55.0)
    result = manager.process_signal(signal)

    assert result["status"] == "submitted"
    order = broker.submitted_orders[0]
    assert order["side"] == "sell"
    assert order["qty"] == 100

    with get_session() as session:
        trade = session.query(Trade).first()
        assert trade.status == "closed"
        assert trade.exit_price == 55.0
        assert trade.pnl == pytest.approx(500.0)


def test_order_rejected_by_risk_manager(isolated_db, risk_manager):
    # Cash too small to buy even one share within position limits doesn't
    # reject -- instead force rejection via max concurrent positions.
    broker = FakeBroker(
        cash=100_000.0,
        portfolio_value=100_000.0,
        equity=100_000.0,
        positions=[{"symbol": f"SYM{i}", "qty": 1, "side": "long", "avg_entry_price": 1.0,
                     "current_price": 1.0, "market_value": 1.0, "unrealized_pl": 0.0,
                     "unrealized_plpc": 0.0} for i in range(10)],
    )
    manager = OrderManager(broker=broker, risk_manager=risk_manager)

    signal = Signal(symbol="AAPL", action=SignalAction.BUY, reason="crossover", strategy="sma_crossover", price=50.0)
    result = manager.process_signal(signal)

    assert result["status"] == "rejected"
    assert "max concurrent positions" in result["reason"]
    assert broker.submitted_orders == []


def test_confirm_callback_can_skip_order(isolated_db, risk_manager):
    broker = FakeBroker()
    manager = OrderManager(broker=broker, risk_manager=risk_manager)

    signal = Signal(symbol="AAPL", action=SignalAction.BUY, reason="crossover", strategy="sma_crossover", price=50.0)
    result = manager.process_signal(signal, confirm_callback=lambda sig, order: False)

    assert result["status"] == "skipped"
    assert broker.submitted_orders == []


def test_limit_price_rejected_upfront(isolated_db, risk_manager):
    broker = FakeBroker()
    manager = OrderManager(broker=broker, risk_manager=risk_manager)

    # Current price (50) already exceeds the BUY limit (40)
    signal = Signal(symbol="AAPL", action=SignalAction.BUY, reason="manual", strategy="manual", price=50.0)
    result = manager.process_signal(signal, limit_price=40.0)

    assert result["status"] == "rejected"
    assert "exceeds BUY limit" in result["reason"]
    assert broker.submitted_orders == []
