import pandas as pd

from backtest.engine import BacktestEngine
from strategies.sma_crossover import SmaCrossoverStrategy


def make_bars(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=dates,
    )


def test_empty_bars_returns_flat_result():
    strategy = SmaCrossoverStrategy({"fast_period": 2, "slow_period": 4})
    engine = BacktestEngine(strategy, starting_equity=100_000)
    result = engine.run("TEST", pd.DataFrame())
    assert result.starting_equity == 100_000
    assert result.ending_equity == 100_000
    assert result.trades == []


def test_buy_and_sell_round_trip_profit():
    strategy = SmaCrossoverStrategy({"fast_period": 2, "slow_period": 4})
    engine = BacktestEngine(strategy, starting_equity=100_000, position_pct=5)

    # Pattern: flat (warm-up) -> sharp rise (buy signal) -> sharp drop (sell signal)
    closes = [100, 100, 100, 100, 100, 120, 130, 140, 100, 90]
    bars = make_bars(closes)

    result = engine.run("TEST", bars)

    assert len(result.trades) >= 1
    buy_trades = [t for t in result.trades if t.side == "buy"]
    assert len(buy_trades) >= 1
    # Equity curve should be populated
    assert not result.equity_curve.empty


def test_no_signals_means_no_trades_and_flat_equity():
    strategy = SmaCrossoverStrategy({"fast_period": 2, "slow_period": 4})
    engine = BacktestEngine(strategy, starting_equity=100_000, position_pct=5)

    # Perfectly flat prices -> SMAs equal -> no crossovers ever
    closes = [100] * 10
    bars = make_bars(closes)

    result = engine.run("TEST", bars)

    assert result.trades == []
    assert result.ending_equity == 100_000
    assert result.total_return_pct == 0.0


def test_summary_does_not_raise():
    strategy = SmaCrossoverStrategy({"fast_period": 2, "slow_period": 4})
    engine = BacktestEngine(strategy, starting_equity=100_000, position_pct=5)
    closes = [100, 100, 100, 100, 100, 120, 130, 140, 100, 90]
    bars = make_bars(closes)
    result = engine.run("TEST", bars)
    summary = result.summary()
    assert "Starting equity" in summary
    assert "Sharpe ratio" in summary
