"""
Dual Moving Average Crossover strategy (Tier 1, swing).

Buy when the fast SMA crosses above the slow SMA; sell (exit) when it
crosses back below. Designed for daily bars on ETFs (SPY, QQQ).
"""

from __future__ import annotations

import pandas as pd

from strategies.base import Signal, SignalAction, Strategy


class SmaCrossoverStrategy(Strategy):
    name = "sma_crossover"

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self.fast_period = int(self.params.get("fast_period", 20))
        self.slow_period = int(self.params.get("slow_period", 50))

        if self.fast_period >= self.slow_period:
            raise ValueError("fast_period must be less than slow_period")

    def min_bars_required(self) -> int:
        # Need slow_period bars for the SMA, plus 1 extra to detect a crossover
        return self.slow_period + 1

    def generate_signal(self, symbol: str, bars: pd.DataFrame) -> Signal:
        if len(bars) < self.min_bars_required():
            return Signal(
                symbol=symbol,
                action=SignalAction.HOLD,
                reason=f"Insufficient history ({len(bars)} < {self.min_bars_required()} bars)",
                strategy=self.name,
            )

        close = bars["close"]
        fast_sma = close.rolling(window=self.fast_period).mean()
        slow_sma = close.rolling(window=self.slow_period).mean()

        # Current and previous values to detect a crossover event
        fast_now, fast_prev = fast_sma.iloc[-1], fast_sma.iloc[-2]
        slow_now, slow_prev = slow_sma.iloc[-1], slow_sma.iloc[-2]
        price = float(close.iloc[-1])

        crossed_above = fast_prev <= slow_prev and fast_now > slow_now
        crossed_below = fast_prev >= slow_prev and fast_now < slow_now

        if crossed_above:
            return Signal(
                symbol=symbol,
                action=SignalAction.BUY,
                reason=(
                    f"{self.fast_period}-SMA ({fast_now:.2f}) crossed above "
                    f"{self.slow_period}-SMA ({slow_now:.2f})"
                ),
                strategy=self.name,
                price=price,
            )

        if crossed_below:
            return Signal(
                symbol=symbol,
                action=SignalAction.SELL,
                reason=(
                    f"{self.fast_period}-SMA ({fast_now:.2f}) crossed below "
                    f"{self.slow_period}-SMA ({slow_now:.2f})"
                ),
                strategy=self.name,
                price=price,
            )

        return Signal(
            symbol=symbol,
            action=SignalAction.HOLD,
            reason=f"No crossover (fast={fast_now:.2f}, slow={slow_now:.2f})",
            strategy=self.name,
            price=price,
        )
