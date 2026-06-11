"""
Opening Range Breakout (ORB) strategy (Tier 1, intraday).

During the first `range_minutes` of the trading session, the strategy
observes the high/low of that "opening range." Once the range is formed,
a close above the range high is a BUY (breakout long) signal, and a close
below the range low is a SELL (breakout-down / exit) signal.

Designed for intraday bars (e.g. 5-minute) on liquid ETFs. Requires the
`bars` index to be timezone-aware timestamps so the session date and the
opening-range window can be identified.
"""

from __future__ import annotations

import pandas as pd

from strategies.base import Signal, SignalAction, Strategy


class OrbStrategy(Strategy):
    name = "orb"

    def __init__(self, params: dict | None = None) -> None:
        super().__init__(params)
        self.range_minutes = int(self.params.get("range_minutes", 30))

        if self.range_minutes < 1:
            raise ValueError("range_minutes must be >= 1")

    def min_bars_required(self) -> int:
        # We at least need enough bars to potentially form the opening
        # range plus one breakout bar. The actual number depends on the
        # bar interval, which we don't know until we see the data, so
        # this is a conservative lower bound.
        return 2

    def _bar_interval_minutes(self, bars: pd.DataFrame) -> int:
        if len(bars) < 2:
            return 1
        delta = bars.index[1] - bars.index[0]
        minutes = int(delta.total_seconds() // 60)
        return max(minutes, 1)

    def generate_signal(self, symbol: str, bars: pd.DataFrame) -> Signal:
        if len(bars) < self.min_bars_required():
            return Signal(
                symbol=symbol,
                action=SignalAction.HOLD,
                reason=f"Insufficient history ({len(bars)} < {self.min_bars_required()} bars)",
                strategy=self.name,
            )

        interval_minutes = self._bar_interval_minutes(bars)
        range_bars = max(1, self.range_minutes // interval_minutes)

        # Restrict to today's session (the most recent bar's date)
        last_date = bars.index[-1].date()
        today_bars = bars[bars.index.date == last_date]

        if len(today_bars) <= range_bars:
            return Signal(
                symbol=symbol,
                action=SignalAction.HOLD,
                reason=(
                    f"Opening range still forming "
                    f"({len(today_bars)}/{range_bars} bars)"
                ),
                strategy=self.name,
            )

        opening_range = today_bars.iloc[:range_bars]
        range_high = float(opening_range["high"].max())
        range_low = float(opening_range["low"].min())

        current_bar = today_bars.iloc[-1]
        price = float(current_bar["close"])

        if price > range_high:
            return Signal(
                symbol=symbol,
                action=SignalAction.BUY,
                reason=(
                    f"Price {price:.2f} broke above opening range high "
                    f"{range_high:.2f} (first {self.range_minutes}m)"
                ),
                strategy=self.name,
                price=price,
            )

        if price < range_low:
            return Signal(
                symbol=symbol,
                action=SignalAction.SELL,
                reason=(
                    f"Price {price:.2f} broke below opening range low "
                    f"{range_low:.2f} (first {self.range_minutes}m)"
                ),
                strategy=self.name,
                price=price,
            )

        return Signal(
            symbol=symbol,
            action=SignalAction.HOLD,
            reason=(
                f"Price {price:.2f} within opening range "
                f"[{range_low:.2f}, {range_high:.2f}]"
            ),
            strategy=self.name,
            price=price,
        )
