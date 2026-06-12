import pandas as pd
import pytest

from strategies.base import SignalAction
from strategies.orb import OrbStrategy


def make_intraday_bars(values: list[float], minutes: int = 5) -> pd.DataFrame:
    """Build a 1-day intraday bar series, one bar every `minutes` minutes,
    starting at 9:30 ET (using a naive but consistent timestamp)."""
    start = pd.Timestamp("2024-01-02 09:30:00")
    dates = pd.date_range(start, periods=len(values), freq=f"{minutes}min")
    return pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [10_000] * len(values),
        },
        index=dates,
    )


def test_invalid_range_minutes_raises():
    with pytest.raises(ValueError):
        OrbStrategy({"range_minutes": 0})


def test_range_still_forming_returns_hold():
    strategy = OrbStrategy({"range_minutes": 30})  # 30 min / 5 min bars = 6 bars
    bars = make_intraday_bars([100, 101, 102])  # only 3 bars so far
    signal = strategy.generate_signal("TEST", bars)
    assert signal.action == SignalAction.HOLD
    assert "still forming" in signal.reason


def test_breakout_above_range_generates_buy():
    strategy = OrbStrategy({"range_minutes": 10})  # 10 min / 5 min bars = 2 bars
    # Opening range: 100, 101 (high=101). Breakout bar: 105 > 101
    bars = make_intraday_bars([100, 101, 105])
    signal = strategy.generate_signal("TEST", bars)
    assert signal.action == SignalAction.BUY
    assert "broke above" in signal.reason


def test_breakout_below_range_generates_sell():
    strategy = OrbStrategy({"range_minutes": 10})
    # Opening range: 100, 99 (low=99). Breakout bar: 90 < 99
    bars = make_intraday_bars([100, 99, 90])
    signal = strategy.generate_signal("TEST", bars)
    assert signal.action == SignalAction.SELL
    assert "broke below" in signal.reason


def test_price_within_range_returns_hold():
    strategy = OrbStrategy({"range_minutes": 10})
    # Opening range: 100, 102 -> [100, 102]. Bar at 101 stays inside.
    bars = make_intraday_bars([100, 102, 101])
    signal = strategy.generate_signal("TEST", bars)
    assert signal.action == SignalAction.HOLD
    assert "within opening range" in signal.reason
