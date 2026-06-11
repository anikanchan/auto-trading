"""
RSI Mean Reversion strategy (Tier 1, swing).

Buy when RSI drops below the oversold threshold (expecting a bounce);
exit when RSI recovers back above the exit threshold. Designed for daily
bars on liquid ETFs/large-caps.
"""

from __future__ import annotations

import pandas as pd

from strategies.base import Signal, SignalAction, Strategy


class RsiMeanReversionStrategy(Strategy):
    name = "rsi_mean_reversion"

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self.rsi_period = int(self.params.get("rsi_period", 14))
        self.oversold = float(self.params.get("rsi_oversold", 30))
        self.exit_level = float(self.params.get("rsi_exit", 50))

        if self.rsi_period < 1:
            raise ValueError("rsi_period must be >= 1")
        if not (0 < self.oversold < self.exit_level < 100):
            raise ValueError("require 0 < rsi_oversold < rsi_exit < 100")

    def min_bars_required(self) -> int:
        # Need rsi_period bars to seed the average gain/loss, plus 1 extra
        # bar to compute the first RSI value, plus 1 more to detect a
        # threshold crossover.
        return self.rsi_period + 2

    def _rsi(self, close: pd.Series) -> pd.Series:
        """Wilder's RSI."""
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(alpha=1 / self.rsi_period, min_periods=self.rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / self.rsi_period, min_periods=self.rsi_period, adjust=False).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        # Where avg_loss is 0 (no losses), RSI is 100
        rsi = rsi.where(avg_loss != 0, 100.0)
        return rsi

    def generate_signal(self, symbol: str, bars: pd.DataFrame) -> Signal:
        if len(bars) < self.min_bars_required():
            return Signal(
                symbol=symbol,
                action=SignalAction.HOLD,
                reason=f"Insufficient history ({len(bars)} < {self.min_bars_required()} bars)",
                strategy=self.name,
            )

        close = bars["close"]
        rsi = self._rsi(close)

        rsi_now, rsi_prev = rsi.iloc[-1], rsi.iloc[-2]
        price = float(close.iloc[-1])

        if pd.isna(rsi_now) or pd.isna(rsi_prev):
            return Signal(
                symbol=symbol,
                action=SignalAction.HOLD,
                reason="RSI not yet available",
                strategy=self.name,
            )

        crossed_into_oversold = rsi_prev >= self.oversold and rsi_now < self.oversold
        crossed_above_exit = rsi_prev <= self.exit_level and rsi_now > self.exit_level

        if crossed_into_oversold:
            return Signal(
                symbol=symbol,
                action=SignalAction.BUY,
                reason=(
                    f"RSI({self.rsi_period}) dropped into oversold: "
                    f"{rsi_now:.2f} < {self.oversold}"
                ),
                strategy=self.name,
                price=price,
            )

        if crossed_above_exit:
            return Signal(
                symbol=symbol,
                action=SignalAction.SELL,
                reason=(
                    f"RSI({self.rsi_period}) recovered above exit level: "
                    f"{rsi_now:.2f} > {self.exit_level}"
                ),
                strategy=self.name,
                price=price,
            )

        return Signal(
            symbol=symbol,
            action=SignalAction.HOLD,
            reason=f"RSI({self.rsi_period})={rsi_now:.2f}, no signal",
            strategy=self.name,
            price=price,
        )
