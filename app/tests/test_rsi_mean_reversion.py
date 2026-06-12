import pandas as pd
import pytest

from strategies.base import SignalAction
from strategies.rsi_mean_reversion import RsiMeanReversionStrategy


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


def test_invalid_thresholds_raise():
    with pytest.raises(ValueError):
        RsiMeanReversionStrategy({"rsi_oversold": 60, "rsi_exit": 50})


def test_insufficient_history_returns_hold():
    strategy = RsiMeanReversionStrategy({"rsi_period": 14})
    bars = make_bars([100] * 5)
    signal = strategy.generate_signal("TEST", bars)
    assert signal.action == SignalAction.HOLD
    assert "Insufficient history" in signal.reason


def test_oversold_drop_generates_buy():
    strategy = RsiMeanReversionStrategy({"rsi_period": 2, "rsi_oversold": 30, "rsi_exit": 50})
    # Steady prices, then a sharp drop -> RSI plunges below 30
    closes = [100, 100, 100, 100, 90]
    bars = make_bars(closes)
    signal = strategy.generate_signal("TEST", bars)
    assert signal.action == SignalAction.BUY
    assert "oversold" in signal.reason


def test_recovery_generates_sell():
    strategy = RsiMeanReversionStrategy({"rsi_period": 2, "rsi_oversold": 30, "rsi_exit": 50})
    # Drop into oversold, then sharp recovery -> RSI back above 50
    closes = [100, 100, 100, 100, 90, 80, 95]
    bars = make_bars(closes)
    signal = strategy.generate_signal("TEST", bars)
    assert signal.action == SignalAction.SELL
    assert "exit level" in signal.reason


def test_min_bars_required():
    strategy = RsiMeanReversionStrategy({"rsi_period": 14})
    assert strategy.min_bars_required() == 16
