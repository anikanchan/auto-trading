import pandas as pd
import pytest

from db.models import init_db
from monitoring import ledger
from risk.risk_manager import PortfolioState, RiskDecision
from scheduler.jobs import TradingScheduler, load_strategies_from_config
from strategies.base import Signal, SignalAction, Strategy


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.models.get_db_path", lambda: tmp_path / "test_trading.db")
    init_db()


class StubStrategy(Strategy):
    name = "stub"

    def __init__(self, action: SignalAction, params=None):
        super().__init__(params)
        self.action = action

    def min_bars_required(self) -> int:
        return 1

    def generate_signal(self, symbol, bars):
        return Signal(symbol=symbol, action=self.action, reason="stub", strategy=self.name, price=100.0)


class StubOrderManager:
    def __init__(self, kill_switch_decision=None):
        self.processed = []
        self.kill_switch_decision = kill_switch_decision or RiskDecision(approved=True, reason="ok")
        self.daily_pnl_updates = []

        class StubRiskManager:
            def __init__(self, decision):
                self.decision = decision

            def check_daily_kill_switch(self, state):
                return self.decision

        self.risk_manager = StubRiskManager(self.kill_switch_decision)

    def process_signal(self, signal, confirm_callback=None):
        self.processed.append(signal)
        return {"status": "submitted" if signal.action != SignalAction.HOLD else "hold", "signal": signal}

    def build_portfolio_state(self):
        return PortfolioState(
            portfolio_value=100_000,
            cash=100_000,
            open_positions=0,
            daily_starting_equity=100_000,
            daily_current_equity=99_000,
        )

    def update_daily_pnl(self, current_equity, kill_switch_triggered=None):
        self.daily_pnl_updates.append((current_equity, kill_switch_triggered))


class StubMarketData:
    def __init__(self, bars: pd.DataFrame):
        self.bars = bars

    def get_daily_bars(self, symbol, start, end=None):
        return self.bars

    def get_intraday_bars(self, symbol, start, end=None, minutes=5):
        return self.bars


def make_bars(n=10):
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"open": [100] * n, "high": [101] * n, "low": [99] * n, "close": [100] * n, "volume": [1000] * n},
        index=dates,
    )


def test_run_strategy_scan_routes_signals(isolated_db):
    bars = make_bars()
    order_manager = StubOrderManager()
    strategy = StubStrategy(SignalAction.BUY)

    scheduler = TradingScheduler(
        order_manager=order_manager,
        market_data=StubMarketData(bars),
        strategies=[(strategy, ["AAPL", "MSFT"])],
    )

    results = scheduler.run_strategy_scan()

    assert len(results) == 2
    assert all(r["status"] == "submitted" for r in results)
    assert {sig.symbol for sig in order_manager.processed} == {"AAPL", "MSFT"}


def test_run_strategy_scan_skips_when_paused(isolated_db):
    bars = make_bars()
    order_manager = StubOrderManager()
    strategy = StubStrategy(SignalAction.BUY)

    scheduler = TradingScheduler(
        order_manager=order_manager,
        market_data=StubMarketData(bars),
        strategies=[(strategy, ["AAPL"])],
    )
    scheduler.pause()

    results = scheduler.run_strategy_scan()

    assert results == []
    assert order_manager.processed == []


def test_run_strategy_scan_skips_insufficient_bars(isolated_db):
    bars = make_bars(n=2)

    class NeedsManyBarsStrategy(StubStrategy):
        def min_bars_required(self):
            return 50

    order_manager = StubOrderManager()
    strategy = NeedsManyBarsStrategy(SignalAction.BUY)

    scheduler = TradingScheduler(
        order_manager=order_manager,
        market_data=StubMarketData(bars),
        strategies=[(strategy, ["AAPL"])],
    )

    results = scheduler.run_strategy_scan()
    assert results == []


def test_run_kill_switch_check_triggers(isolated_db):
    order_manager = StubOrderManager(kill_switch_decision=RiskDecision(approved=False, reason="kill-switch triggered"))

    scheduler = TradingScheduler(
        order_manager=order_manager,
        market_data=StubMarketData(make_bars()),
        strategies=[],
    )

    triggered = scheduler.run_kill_switch_check()

    assert triggered is True
    assert order_manager.daily_pnl_updates == [(99_000, True)]


def test_run_kill_switch_check_not_triggered(isolated_db):
    order_manager = StubOrderManager(kill_switch_decision=RiskDecision(approved=True, reason="ok"))

    scheduler = TradingScheduler(
        order_manager=order_manager,
        market_data=StubMarketData(make_bars()),
        strategies=[],
    )

    triggered = scheduler.run_kill_switch_check()

    assert triggered is False
    assert order_manager.daily_pnl_updates == [(99_000, False)]


def test_run_eod_report_includes_pnl_and_orders(isolated_db):
    order_manager = StubOrderManager()
    scheduler = TradingScheduler(
        order_manager=order_manager,
        market_data=StubMarketData(make_bars()),
        strategies=[],
    )

    ledger.log_event(ledger.CATEGORY_ORDER, "Submitted BUY 10 AAPL @ ~$150.00")

    report = scheduler.run_eod_report()

    assert "EOD Report" in report
    assert "P&L:" in report
    assert "Submitted BUY 10 AAPL" in report


def test_pause_and_resume_toggle_state(isolated_db):
    scheduler = TradingScheduler(
        order_manager=StubOrderManager(),
        market_data=StubMarketData(make_bars()),
        strategies=[],
    )

    assert scheduler.paused is False
    scheduler.pause()
    assert scheduler.paused is True
    scheduler.resume()
    assert scheduler.paused is False


def test_load_strategies_from_config_returns_enabled_strategies():
    strategies = load_strategies_from_config()
    names = {s.name for s, _ in strategies}
    # All three Tier 1 strategies are enabled in config/settings.yaml
    assert names == {"sma_crossover", "orb", "rsi_mean_reversion"}

    sma = next(s for s, _ in strategies if s.name == "sma_crossover")
    universe = next(u for s, u in strategies if s is sma)
    assert universe == ["SPY", "QQQ"]
