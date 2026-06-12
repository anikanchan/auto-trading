"""
Day orders — BUY/SELL commands that watch the price for one trading day.

A day order (`BUY AAPL 10 DAY 190`) doesn't execute immediately. The
watcher polls prices during market hours and moves each order through
three stages:

  1. Waiting — until the price touches the target (<= target for BUY,
     >= target for SELL).
  2. Armed — keep tracking the best price seen (lowest for BUY, highest
     for SELL). If the price moves back through the target before
     executing, return to waiting; it may touch again later in the day.
  3. Execute — once the price retraces off the best level by
     `day_orders.rebound_pct`, submit through the OrderManager with a
     limit at the target price. This buys near the local low / sells near
     the local high where possible, and the limit guarantees the fill is
     never worse than the target.

Unfilled orders expire at market close.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable

from config.loader import get as get_config
from monitoring import ledger


@dataclass
class DayOrder:
    symbol: str
    side: str  # "buy" | "sell"
    quantity: float
    target_price: float
    armed: bool = False
    best_price: float | None = None
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    def describe(self) -> str:
        relation = "<=" if self.side == "buy" else ">="
        return (
            f"{self.side.upper()} {self.quantity:g} {self.symbol} today "
            f"when price {relation} ${self.target_price:.2f}"
        )


class DayOrderWatcher:
    """Tracks active day orders and executes them at a favorable price."""

    def __init__(
        self,
        order_manager,
        market_data=None,
        rebound_pct: float | None = None,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        self.order_manager = order_manager
        self._market_data = market_data
        self.rebound_pct = (
            rebound_pct
            if rebound_pct is not None
            else float(get_config("day_orders.rebound_pct", 0.2))
        )
        self.notify = notify
        self.active: list[DayOrder] = []

    @property
    def market_data(self):
        if self._market_data is None:
            from data.market_data import MarketData

            self._market_data = MarketData()
        return self._market_data

    def add(self, symbol: str, side: str, quantity: float, target_price: float) -> DayOrder:
        order = DayOrder(
            symbol=symbol.upper(), side=side, quantity=quantity, target_price=target_price
        )
        self.active.append(order)
        ledger.log_event(ledger.CATEGORY_ORDER, f"Day order active: {order.describe()}")
        return order

    def poll(self) -> list[dict]:
        """Check every active day order against the latest price. Returns
        execution results for any orders that triggered."""
        results = []
        for order in list(self.active):
            try:
                price = self.market_data.get_latest_price(order.symbol)
            except Exception as exc:  # noqa: BLE001 - keep watching other orders
                ledger.log_event(
                    ledger.CATEGORY_ERROR,
                    f"Day order price check failed for {order.symbol}",
                    {"error": str(exc)},
                )
                continue
            result = self._check(order, price)
            if result is not None:
                results.append(result)
        return results

    def _check(self, order: DayOrder, price: float) -> dict | None:
        hit = price <= order.target_price if order.side == "buy" else price >= order.target_price

        if not order.armed:
            if hit:
                order.armed = True
                order.best_price = price
                ledger.log_event(
                    ledger.CATEGORY_ORDER,
                    f"Day order target hit at ${price:.2f}: {order.describe()}",
                )
            return None

        if not hit:
            # Price slipped back through the target before we executed —
            # disarm and wait for another touch.
            order.armed = False
            order.best_price = None
            ledger.log_event(
                ledger.CATEGORY_ORDER,
                f"Day order disarmed at ${price:.2f} (back through target): {order.describe()}",
            )
            return None

        if order.side == "buy":
            if price < order.best_price:
                order.best_price = price
                return None
            should_execute = price >= order.best_price * (1 + self.rebound_pct / 100)
        else:
            if price > order.best_price:
                order.best_price = price
                return None
            should_execute = price <= order.best_price * (1 - self.rebound_pct / 100)

        if not should_execute:
            return None
        return self._execute(order, price)

    def _execute(self, order: DayOrder, price: float) -> dict:
        self.active.remove(order)
        result = self.order_manager.process_manual_order(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            limit_price=order.target_price,
            strategy="day_order",
        )

        if result["status"] == "submitted":
            self._notify(
                f"Day order executed: {order.side.upper()} {order.quantity:g} {order.symbol} "
                f"@ limit ${order.target_price:.2f} "
                f"(triggered at ${price:.2f}, best seen ${order.best_price:.2f})"
            )
        else:
            self._notify(
                f"Day order {result['status']}: {order.describe()}"
                f" — {result.get('reason', 'no reason given')}"
            )
        return result

    def expire_all(self) -> None:
        """Cancel all remaining day orders (called at market close)."""
        for order in self.active:
            ledger.log_event(
                ledger.CATEGORY_ORDER, f"Day order expired unfilled: {order.describe()}"
            )
            self._notify(f"Day order expired unfilled: {order.describe()}")
        self.active = []

    def _notify(self, text: str) -> None:
        if self.notify is not None:
            self.notify(text)
