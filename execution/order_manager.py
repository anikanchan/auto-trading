"""
Order Manager — wires strategy signals through risk checks to the broker.

Flow for every non-HOLD signal:
  1. Log the signal to the transaction ledger.
  2. Build a PortfolioState snapshot from the broker (account + positions),
     tracking each day's starting equity for the kill-switch.
  3. Run the order through RiskManager.evaluate_order(). Rejections are
     logged and returned without touching the broker.
  4. If a confirmation callback is provided (e.g. "send a message and wait
     for YES/NO"), call it. If it returns False, the order is logged as
     skipped and not submitted.
  5. Submit the order (market or limit) via the broker, record the fill in
     the Trade table, and log it to the ledger.

This module is the single place where signals turn into real orders, so
every code path logs to the ledger per the transaction-logging spec.
"""

from __future__ import annotations

import datetime as dt
from typing import Callable

from db.models import DailyPnL, Trade, get_session
from execution.alpaca_broker import AlpacaBroker
from monitoring import ledger
from risk.risk_manager import OrderRequest, PortfolioState, RiskDecision, RiskManager
from strategies.base import Signal, SignalAction

# Callback signature: (signal, order_request) -> True (proceed) / False (skip)
ConfirmCallback = Callable[[Signal, OrderRequest], bool]


class OrderManager:
    def __init__(self, broker: AlpacaBroker | None = None, risk_manager: RiskManager | None = None) -> None:
        self.broker = broker or AlpacaBroker()
        self.risk_manager = risk_manager or RiskManager()

    # ------------------------------------------------------------------
    # Portfolio state
    # ------------------------------------------------------------------

    def _get_or_create_daily_pnl(self, current_equity: float) -> DailyPnL:
        """Fetch today's DailyPnL row, creating it (with today's starting
        equity) if this is the first call of the day."""
        today = dt.datetime.combine(dt.date.today(), dt.time.min)

        with get_session() as session:
            row = session.query(DailyPnL).filter_by(date=today).first()
            if row is None:
                row = DailyPnL(
                    date=today,
                    starting_equity=current_equity,
                    ending_equity=current_equity,
                    kill_switch_triggered=False,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
            session.expunge(row)
            return row

    def update_daily_pnl(self, current_equity: float, kill_switch_triggered: bool | None = None) -> None:
        """Update today's running equity (and optionally kill-switch flag)."""
        today = dt.datetime.combine(dt.date.today(), dt.time.min)
        with get_session() as session:
            row = session.query(DailyPnL).filter_by(date=today).first()
            if row is None:
                row = DailyPnL(date=today, starting_equity=current_equity)
                session.add(row)
            row.ending_equity = current_equity
            row.pnl = current_equity - row.starting_equity
            row.pnl_pct = (
                (current_equity - row.starting_equity) / row.starting_equity * 100
                if row.starting_equity
                else 0.0
            )
            if kill_switch_triggered is not None:
                row.kill_switch_triggered = kill_switch_triggered
            session.commit()

    def build_portfolio_state(self) -> PortfolioState:
        account = self.broker.get_account()
        positions = self.broker.get_positions()
        daily = self._get_or_create_daily_pnl(account.equity)

        return PortfolioState(
            portfolio_value=account.portfolio_value,
            cash=account.cash,
            open_positions=len(positions),
            daily_starting_equity=daily.starting_equity,
            daily_current_equity=account.equity,
            kill_switch_active=daily.kill_switch_triggered,
        )

    def get_position_qty(self, symbol: str) -> float:
        for position in self.broker.get_positions():
            if position["symbol"] == symbol:
                return float(position["qty"])
        return 0.0

    # ------------------------------------------------------------------
    # Sizing
    # ------------------------------------------------------------------

    def calculate_buy_quantity(self, state: PortfolioState, price: float) -> float:
        """Whole shares sized at the configured max position percentage of
        portfolio value."""
        if price <= 0:
            return 0.0
        order_value = state.portfolio_value * (self.risk_manager.max_position_pct / 100)
        return float(order_value // price)

    @staticmethod
    def check_limit_price(side: str, limit_price: float | None, current_price: float) -> RiskDecision:
        """Pre-flight check for BUY/SELL commands with an explicit price
        limit: reject upfront if the current price already breaches it.

        BUY <= limit_price (don't pay more than the limit).
        SELL >= limit_price (don't sell for less than the limit).
        """
        if limit_price is None:
            return RiskDecision(approved=True, reason="No price limit specified")

        if side == "buy" and current_price > limit_price:
            return RiskDecision(
                approved=False,
                reason=(
                    f"Current price ${current_price:.2f} already exceeds "
                    f"BUY limit ${limit_price:.2f}"
                ),
            )

        if side == "sell" and current_price < limit_price:
            return RiskDecision(
                approved=False,
                reason=(
                    f"Current price ${current_price:.2f} already below "
                    f"SELL limit ${limit_price:.2f}"
                ),
            )

        return RiskDecision(approved=True, reason="Current price within limit")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process_signal(
        self,
        signal: Signal,
        confirm_callback: ConfirmCallback | None = None,
        limit_price: float | None = None,
    ) -> dict:
        """Process a strategy signal end-to-end. Returns a dict describing
        the outcome: {"status": "hold" | "rejected" | "skipped" | "submitted",
        ...}."""

        ledger.log_event(
            ledger.CATEGORY_SIGNAL,
            f"{signal.strategy}: {signal.action.value.upper()} {signal.symbol}",
            {"reason": signal.reason, "price": signal.price},
        )

        if signal.action == SignalAction.HOLD:
            return {"status": "hold", "signal": signal}

        # Daily kill-switch check
        state = self.build_portfolio_state()
        kill_switch_check = self.risk_manager.check_daily_kill_switch(state)
        if not kill_switch_check.approved:
            self.update_daily_pnl(state.daily_current_equity, kill_switch_triggered=True)
            state.kill_switch_active = True
            ledger.log_event(ledger.CATEGORY_RISK, kill_switch_check.reason, {"symbol": signal.symbol})

        price = signal.price
        if price is None:
            from data.market_data import MarketData

            price = MarketData().get_latest_price(signal.symbol)

        # Determine order quantity
        if signal.action == SignalAction.BUY:
            quantity = self.calculate_buy_quantity(state, price)
        else:  # SELL -> close existing position
            quantity = self.get_position_qty(signal.symbol)

        if quantity <= 0:
            reason = "Calculated order quantity is zero (insufficient funds or no position to sell)"
            ledger.log_event(
                ledger.CATEGORY_ORDER,
                f"Skipped {signal.action.value.upper()} {signal.symbol}: {reason}",
                {"price": price},
            )
            return {"status": "skipped", "reason": reason, "signal": signal}

        order = OrderRequest(symbol=signal.symbol, side=signal.action.value, quantity=quantity, price=price)

        # Limit-price pre-flight check (for manual BUY/SELL commands with a price)
        limit_decision = self.check_limit_price(order.side, limit_price, price)
        if not limit_decision.approved:
            ledger.log_event(
                ledger.CATEGORY_ORDER,
                f"Rejected {order.side.upper()} {order.symbol}: {limit_decision.reason}",
                {"quantity": order.quantity, "price": price, "limit_price": limit_price},
            )
            return {"status": "rejected", "reason": limit_decision.reason, "signal": signal}

        decision = self.risk_manager.evaluate_order(order, state)
        if not decision.approved:
            ledger.log_event(
                ledger.CATEGORY_RISK,
                f"Rejected {order.side.upper()} {order.symbol}: {decision.reason}",
                {"quantity": order.quantity, "price": price},
            )
            return {"status": "rejected", "reason": decision.reason, "signal": signal}

        if confirm_callback is not None:
            confirmed = confirm_callback(signal, order)
            if not confirmed:
                ledger.log_event(
                    ledger.CATEGORY_ORDER,
                    f"Skipped {order.side.upper()} {order.symbol} (not confirmed)",
                    {"quantity": order.quantity, "price": price},
                )
                return {"status": "skipped", "reason": "Not confirmed by user", "signal": signal}

        # Submit the order
        if limit_price is not None:
            result = self.broker.submit_limit_order(order.symbol, order.quantity, order.side, limit_price)
        else:
            result = self.broker.submit_market_order(order.symbol, order.quantity, order.side)

        ledger.log_event(
            ledger.CATEGORY_ORDER,
            f"Submitted {order.side.upper()} {order.quantity:g} {order.symbol} @ ~${price:.2f}",
            {"order": result, "strategy": signal.strategy, "reason": signal.reason},
        )

        self._record_trade(signal, order, price, result)

        return {"status": "submitted", "order": result, "signal": signal}

    def _record_trade(self, signal: Signal, order: OrderRequest, price: float, order_result: dict) -> None:
        """Create/close a Trade row to track open positions opened by the bot."""
        with get_session() as session:
            if order.side == "buy":
                trade = Trade(
                    symbol=order.symbol,
                    side="buy",
                    quantity=order.quantity,
                    entry_price=price,
                    strategy=signal.strategy,
                    status="open",
                )
                session.add(trade)
            else:
                open_trade = (
                    session.query(Trade)
                    .filter_by(symbol=order.symbol, status="open")
                    .order_by(Trade.opened_at.asc())
                    .first()
                )
                if open_trade is not None:
                    open_trade.exit_price = price
                    open_trade.status = "closed"
                    open_trade.closed_at = dt.datetime.now(dt.timezone.utc)
                    open_trade.pnl = (price - open_trade.entry_price) * open_trade.quantity
            session.commit()


if __name__ == "__main__":
    # Smoke test: process a HOLD signal (no orders placed).
    manager = OrderManager()
    state = manager.build_portfolio_state()
    print("Portfolio state:", state)
    test_signal = Signal(symbol="SPY", action=SignalAction.HOLD, reason="smoke test", strategy="manual")
    print(manager.process_signal(test_signal))
