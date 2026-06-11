import numpy as np
import pandas as pd
import pytest

from strategies.base import SignalAction
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


def test_invalid_periods_raise():
    with pytest.raises(ValueError):
        SmaCrossoverStrategy({"fast_period": 50, "slow_period": 20})


def test_insufficient_history_returns_hold():
    strategy = SmaCrossoverStrategy({"fast_period": 3, "slow_period": 5})
    bars = make_bars([100, 101, 102])
    signal = strategy.generate_signal("TEST", bars)
    assert signal.action == SignalAction.HOLD
    assert "Insufficient history" in signal.reason


def test_crossover_above_generates_buy():
    strategy = SmaCrossoverStrategy({"fast_period": 2, "slow_period": 4})
    # Flat, then a sharp rise on the last bar -> fast SMA crosses above slow SMA
    closes = [100, 100, 100, 100, 100, 130]
    bars = make_bars(closes)
    signal = strategy.generate_signal("TEST", bars)
    assert signal.action == SignalAction.BUY
    assert "crossed above" in signal.reason


def test_crossover_below_generates_sell():
    strategy = SmaCrossoverStrategy({"fast_period": 2, "slow_period": 4})
    # Flat, then a sharp drop on the last bar -> fast SMA crosses below slow SMA
    closes = [100, 100, 100, 100, 100, 70]
    bars = make_bars(closes)
    signal = strategy.generate_signal("TEST", bars)
    assert signal.action == SignalAction.SELL
    assert "crossed below" in signal.reason


def test_no_crossover_returns_hold():
    strategy = SmaCrossoverStrategy({"fast_period": 2, "slow_period": 4})
    closes = [100, 100, 100, 100, 100, 100]
    bars = make_bars(closes)
    signal = strategy.generate_signal("TEST", bars)
    assert signal.action == SignalAction.HOLD


def test_min_bars_required():
    strategy = SmaCrossoverStrategy({"fast_period": 20, "slow_period": 50})
    assert strategy.min_bars_required() == 51
