"""
Risk Manager — gates every order before it's submitted.

Implements the rules from the specs:
  - Max single position: % of portfolio
  - Daily drawdown kill-switch
  - Max concurrent open positions
  - Max portfolio deployed
  - Per-trade stop-loss (informational here; actual stop orders placed by execution layer)

This module is intentionally broker-agnostic and side-effect free (pure
functions / simple state) so it's easy to unit test and reuse in both the
backtester and the live bot.
"""

from __future__ import annotations

from dataclasses import dataclass

from config.loader import get as get_config


@dataclass
class PortfolioState:
    """Snapshot of the portfolio needed to evaluate risk rules."""

    portfolio_value: float
    cash: float
    open_positions: int
    daily_starting_equity: float
    daily_current_equity: float
    kill_switch_active: bool = False


@dataclass
class OrderRequest:
    symbol: str
    side: str  # "buy" | "sell"
    quantity: float
    price: float  # estimated execution price


@dataclass
class RiskDecision:
    approved: bool
    reason: str


class RiskManager:
    """Evaluates order requests against configured risk limits."""

    def __init__(self, params: dict | None = None) -> None:
        cfg = params or get_config("risk", {})
        self.max_portfolio_deployed_pct = float(cfg.get("max_portfolio_deployed_pct", 50))
        self.max_position_pct = float(cfg.get("max_position_pct", 5))
        self.daily_loss_kill_switch_pct = float(cfg.get("daily_loss_kill_switch_pct", -2))
        self.stop_loss_pct = float(cfg.get("stop_loss_pct", -1.5))
        self.max_concurrent_positions = int(cfg.get("max_concurrent_positions", 10))

    def check_daily_kill_switch(self, state: PortfolioState) -> RiskDecision:
        """Check whether the daily drawdown kill-switch should be triggered.

        Returns approved=False (meaning: halt all trading) if the portfolio
        has dropped more than `daily_loss_kill_switch_pct` since the start
        of the day.
        """
        if state.daily_starting_equity <= 0:
            return RiskDecision(approved=True, reason="No starting equity recorded yet")

        pnl_pct = (
            (state.daily_current_equity - state.daily_starting_equity)
            / state.daily_starting_equity
            * 100
        )

        if pnl_pct <= self.daily_loss_kill_switch_pct:
            return RiskDecision(
                approved=False,
                reason=(
                    f"Daily kill-switch triggered: portfolio down {pnl_pct:.2f}% "
                    f"(limit {self.daily_loss_kill_switch_pct}%)"
                ),
            )

        return RiskDecision(approved=True, reason=f"Daily P&L {pnl_pct:.2f}% within limits")

    def evaluate_order(self, order: OrderRequest, state: PortfolioState) -> RiskDecision:
        """Evaluate a proposed order against all risk rules.

        Order is rejected if any rule is violated. SELL orders that reduce
        exposure are always allowed through the position-size/deployment
        checks (you can always close a position), but are still blocked by
        the kill switch and FLATTEN logic upstream.
        """
        # 1. Kill switch — blocks new BUY orders entirely
        if state.kill_switch_active and order.side == "buy":
            return RiskDecision(
                approved=False,
                reason="Daily loss kill-switch is active — no new buy orders allowed",
            )

        kill_switch_check = self.check_daily_kill_switch(state)
        if not kill_switch_check.approved and order.side == "buy":
            return kill_switch_check

        order_value = order.quantity * order.price

        if order.side == "sell":
            # Selling reduces risk — always approve (subject to kill switch above,
            # which only blocks new buys).
            return RiskDecision(approved=True, reason="Sell order reduces exposure")

        # 2. Max single position size
        if state.portfolio_value <= 0:
            return RiskDecision(approved=False, reason="Portfolio value is zero or unknown")

        position_pct = order_value / state.portfolio_value * 100
        if position_pct > self.max_position_pct:
            return RiskDecision(
                approved=False,
                reason=(
                    f"Order size {position_pct:.2f}% of portfolio exceeds "
                    f"max position size {self.max_position_pct}%"
                ),
            )

        # 3. Max concurrent positions
        if state.open_positions >= self.max_concurrent_positions:
            return RiskDecision(
                approved=False,
                reason=(
                    f"Already at max concurrent positions "
                    f"({state.open_positions}/{self.max_concurrent_positions})"
                ),
            )

        # 4. Sufficient cash
        if order_value > state.cash:
            return RiskDecision(
                approved=False,
                reason=(
                    f"Insufficient cash: order requires ${order_value:,.2f}, "
                    f"available ${state.cash:,.2f}"
                ),
            )

        # 5. Max portfolio deployed
        deployed_value = state.portfolio_value - state.cash
        deployed_pct_after = (deployed_value + order_value) / state.portfolio_value * 100
        if deployed_pct_after > self.max_portfolio_deployed_pct:
            return RiskDecision(
                approved=False,
                reason=(
                    f"Order would bring deployed capital to {deployed_pct_after:.2f}%, "
                    f"exceeding max {self.max_portfolio_deployed_pct}%"
                ),
            )

        return RiskDecision(approved=True, reason="Order within all risk limits")

    def calculate_stop_loss_price(self, entry_price: float, side: str) -> float:
        """Calculate the stop-loss price for a new position."""
        if side == "buy":
            return entry_price * (1 + self.stop_loss_pct / 100)
        else:  # short position
            return entry_price * (1 - self.stop_loss_pct / 100)
