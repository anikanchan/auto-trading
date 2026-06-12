"""
Abstract base class for trading strategies.

A strategy consumes a price history DataFrame and produces Signal objects.
Strategies are pure decision logic — they don't place orders or know
about the broker. The scheduler/backtester feeds them data and routes
their signals through the Risk Manager.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

import pandas as pd


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Signal:
    symbol: str
    action: SignalAction
    reason: str
    strategy: str
    price: float | None = None  # price at time of signal (for logging/backtest)


class Strategy(ABC):
    """Base class all trading strategies must implement."""

    #: Unique strategy identifier, used in logs/trades/config.
    name: str = "base"

    def __init__(self, params: dict | None = None) -> None:
        self.params = params or {}

    @abstractmethod
    def generate_signal(self, symbol: str, bars: pd.DataFrame) -> Signal:
        """Given historical bars (oldest first) for a symbol, return a Signal.

        `bars` must have at least the columns: open, high, low, close, volume.
        The last row represents the most recent completed bar.
        """
        raise NotImplementedError

    def min_bars_required(self) -> int:
        """Minimum number of bars needed before this strategy can produce
        a meaningful signal. Used by backtester/scheduler to know how much
        history to fetch."""
        return 1
