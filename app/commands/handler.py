"""
Command handler — executes parsed Commands and returns a text reply.

This is the brains of the two-way messaging interface: STATUS, PAUSE,
RESUME, FLATTEN, REPORT, HISTORY, RISK, STOP, KILL, BUY, SELL, HELP, plus
the YES/NO confirmation flow for manual BUY/SELL orders.

The messaging transport (iMessage polling/sending) is wired up separately
and simply calls `CommandHandler.handle(text)` for each inbound message
from the allowed phone number, then sends the returned string back.
"""

from __future__ import annotations

import datetime as dt
import os
import signal
from typing import Callable

from commands.parser import Command, CommandParseError, parse_command
from db.models import Trade, get_session
from monitoring import ledger
from scheduler.jobs import TradingScheduler

HELP_TEXT = (
    "Available commands:\n"
    "STATUS - current positions, P&L, bot state\n"
    "PAUSE - suspend new trade signals\n"
    "RESUME - resume normal trading\n"
    "FLATTEN - close all open positions immediately\n"
    "REPORT - send end-of-day report now\n"
    "HISTORY [7D|<N>D|YYYY-MM-DD..YYYY-MM-DD] - historical report\n"
    "RISK <param> <value> - update a risk parameter (e.g. RISK MAXPOS 3%)\n"
    "STOP <ticker> - stop trading a specific symbol\n"
    "KILL [instance] - shut down all instances, or a specific one (e.g. KILL MBAir)\n"
    "BUY <ticker> <qty> [MAX <price>] - buy (limit if MAX given)\n"
    "SELL <ticker> <qty> [MIN <price>] - sell (limit if MIN given)\n"
    "BUY <ticker> <qty> DAY <price> - watch today, buy when price <= target (seeks lower)\n"
    "SELL <ticker> <qty> DAY <price> - watch today, sell when price >= target (seeks higher)\n"
    "HELP - this message"
)

# Maps RISK command param names to RiskManager attribute names.
RISK_PARAM_MAP = {
    "MAXPOS": "max_position_pct",
    "MAXDEPLOYED": "max_portfolio_deployed_pct",
    "KILLSWITCH": "daily_loss_kill_switch_pct",
    "STOPLOSS": "stop_loss_pct",
    "MAXPOSITIONS": "max_concurrent_positions",
}


class CommandHandler:
    def __init__(self, scheduler: TradingScheduler, instance_name: str = "Bot") -> None:
        self.scheduler = scheduler
        self.order_manager = scheduler.order_manager
        self.broker = self.order_manager.broker
        self.pending_order: dict | None = None
        self.instance_name = instance_name

    def handle(self, text: str) -> str:
        try:
            command = parse_command(text)
        except CommandParseError as exc:
            ledger.log_event(ledger.CATEGORY_COMMAND, f"Rejected command: {text}", {"error": str(exc)})
            return f"Error: {exc}"

        if command.name == "UNKNOWN":
            ledger.log_event(ledger.CATEGORY_COMMAND, f"Ignored unrecognized message: {text}")
            return ""

        ledger.log_event(ledger.CATEGORY_COMMAND, f"Received command: {command.raw}")

        handler = getattr(self, f"_handle_{command.name.lower()}", None)
        if handler is None:
            return f"Command {command.name} not yet implemented."

        return handler(command)

    # ------------------------------------------------------------------
    # Simple commands
    # ------------------------------------------------------------------

    def _handle_help(self, command: Command) -> str:
        return HELP_TEXT

    def _handle_status(self, command: Command) -> str:
        account = self.broker.get_account()
        positions = self.broker.get_positions()
        state = self.order_manager.build_portfolio_state()

        lines = [
            f"Mode: {self.order_manager.broker.mode}",
            f"Status: {'PAUSED' if self.scheduler.paused else 'RUNNING'}",
            f"Equity: ${account.equity:,.2f}",
            f"Cash: ${account.cash:,.2f}",
            f"Daily P&L: ${state.daily_current_equity - state.daily_starting_equity:,.2f}",
            f"Open positions: {len(positions)}",
        ]
        for p in positions:
            lines.append(f"  {p['symbol']}: {p['qty']} @ ${p['avg_entry_price']:.2f}")
        if self.scheduler.stopped_symbols:
            lines.append(f"Stopped symbols: {', '.join(sorted(self.scheduler.stopped_symbols))}")
        day_orders = self.scheduler.day_order_watcher.active
        if day_orders:
            lines.append("Day orders:")
            for order in day_orders:
                lines.append(f"  {order.describe()}")

        return "\n".join(lines)

    def _handle_pause(self, command: Command) -> str:
        self.scheduler.pause()
        return "Trading paused. Open positions are still held."

    def _handle_resume(self, command: Command) -> str:
        self.scheduler.resume()
        return "Trading resumed."

    def _handle_flatten(self, command: Command) -> str:
        self.broker.flatten_all_positions()
        ledger.log_event(ledger.CATEGORY_COMMAND, "FLATTEN executed: closing all positions")
        return "Closing all open positions now."

    def _handle_report(self, command: Command) -> str:
        return self.scheduler.run_eod_report()

    def _handle_kill(self, command: Command) -> str:
        target = command.args.get("target")
        if target and target.upper() != self.instance_name.upper():
            return ""
        ledger.log_event(ledger.CATEGORY_SYSTEM, "KILL command received — shutting down")
        os.kill(os.getpid(), signal.SIGINT)
        return f"[{self.instance_name}] Shutting down..."

    def _handle_stop(self, command: Command) -> str:
        symbol = command.args["symbol"]
        self.scheduler.stopped_symbols.add(symbol)
        ledger.log_event(ledger.CATEGORY_COMMAND, f"Stopped trading {symbol}")
        return f"{symbol} will no longer be traded by strategies."

    def _handle_risk(self, command: Command) -> str:
        param = command.args["param"]
        raw_value = command.args["value"]

        attr = RISK_PARAM_MAP.get(param)
        if attr is None:
            return f"Unknown risk parameter '{param}'. Valid: {', '.join(RISK_PARAM_MAP)}"

        value_str = raw_value.rstrip("%")
        try:
            value: float | int
            if attr == "max_concurrent_positions":
                value = int(value_str)
            else:
                value = float(value_str)
        except ValueError:
            return f"Invalid value '{raw_value}' for {param}"

        old_value = getattr(self.order_manager.risk_manager, attr)
        setattr(self.order_manager.risk_manager, attr, value)
        ledger.log_event(
            ledger.CATEGORY_CONFIG,
            f"Risk parameter {param} changed: {old_value} -> {value}",
            {"param": attr, "old": old_value, "new": value},
        )
        return f"{param} updated: {old_value} -> {value}"

    # ------------------------------------------------------------------
    # HISTORY
    # ------------------------------------------------------------------

    def _handle_history(self, command: Command) -> str:
        if "start" in command.args:
            start = dt.datetime.combine(command.args["start"], dt.time.min, tzinfo=dt.timezone.utc)
            end = dt.datetime.combine(command.args["end"], dt.time.max, tzinfo=dt.timezone.utc)
            label = f"{command.args['start']} to {command.args['end']}"
        else:
            days = command.args["days"]
            start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
            end = dt.datetime.now(dt.timezone.utc)
            label = f"last {days} day(s)"

        return build_history_report(start, end, label)

    # ------------------------------------------------------------------
    # BUY / SELL with YES/NO confirmation
    # ------------------------------------------------------------------

    def _handle_buy(self, command: Command) -> str:
        return self._handle_order(command, side="buy")

    def _handle_sell(self, command: Command) -> str:
        return self._handle_order(command, side="sell")

    def _handle_order(self, command: Command, side: str) -> str:
        symbol = command.args["symbol"]
        quantity = command.args["quantity"]
        limit_price = command.args["limit_price"]
        day_price = command.args.get("day_price")

        from data.market_data import MarketData

        current_price = MarketData().get_latest_price(symbol)

        if day_price is not None:
            # Day orders have no upfront price check — any relation between
            # the current price and the target is a valid starting point.
            self.pending_order = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "limit_price": None,
                "day_price": day_price,
            }
            relation = "<=" if side == "buy" else ">="
            seeking = "lower" if side == "buy" else "higher"
            return (
                f"{side.upper()} {quantity:g} {symbol} today when price {relation} "
                f"${day_price:.2f} (current ${current_price:.2f}), seeking a {seeking} "
                f"fill — reply YES to confirm"
            )

        decision = self.order_manager.check_limit_price(side, limit_price, current_price)
        if not decision.approved:
            ledger.log_event(
                ledger.CATEGORY_ORDER,
                f"Rejected manual {side.upper()} {symbol}: {decision.reason}",
                {"quantity": quantity, "current_price": current_price, "limit_price": limit_price},
            )
            return f"Rejected: {decision.reason}"

        self.pending_order = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "limit_price": limit_price,
            "day_price": None,
        }

        if limit_price is not None:
            return (
                f"{side.upper()} {quantity:g} {symbol} @ limit ${limit_price:.2f} "
                f"(current ${current_price:.2f}) — reply YES to confirm"
            )
        return (
            f"{side.upper()} {quantity:g} {symbol} @ market "
            f"(current ${current_price:.2f}) — reply YES to confirm"
        )

    def _handle_yes(self, command: Command) -> str:
        if self.pending_order is None:
            return "No pending order to confirm."

        order = self.pending_order
        self.pending_order = None

        if order.get("day_price") is not None:
            day_order = self.scheduler.day_order_watcher.add(
                symbol=order["symbol"],
                side=order["side"],
                quantity=order["quantity"],
                target_price=order["day_price"],
            )
            return f"Day order active: {day_order.describe()}"

        result = self.order_manager.process_manual_order(
            symbol=order["symbol"],
            side=order["side"],
            quantity=order["quantity"],
            limit_price=order["limit_price"],
        )

        if result["status"] == "submitted":
            return f"Order submitted: {order['side'].upper()} {order['quantity']:g} {order['symbol']}"
        if result["status"] == "rejected":
            return f"Order rejected: {result['reason']}"
        return f"Order skipped: {result.get('reason', 'unknown')}"

    def _handle_no(self, command: Command) -> str:
        if self.pending_order is None:
            return "No pending order to cancel."

        order = self.pending_order
        self.pending_order = None
        ledger.log_event(
            ledger.CATEGORY_ORDER,
            f"Manual order cancelled by user: {order['side'].upper()} {order['symbol']}",
            order,
        )
        return "Order cancelled."


def build_history_report(start: dt.datetime, end: dt.datetime, label: str) -> str:
    """Build the HISTORY report text for the given window."""
    with get_session() as session:
        trades = (
            session.query(Trade)
            .filter(Trade.opened_at >= start, Trade.opened_at <= end)
            .all()
        )

    closed = [t for t in trades if t.status == "closed" and t.pnl is not None]
    total_pnl = sum(t.pnl for t in closed)
    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]
    win_rate = (len(wins) / len(closed) * 100) if closed else 0.0

    by_strategy: dict[str, int] = {}
    for t in trades:
        by_strategy[t.strategy] = by_strategy.get(t.strategy, 0) + 1

    skipped = ledger.get_events(start=start, end=end, category=ledger.CATEGORY_ORDER)
    skipped = [e for e in skipped if "Skipped" in e.message or "Rejected" in e.message]
    risk_events = ledger.get_events(start=start, end=end, category=ledger.CATEGORY_RISK)

    lines = [f"=== History: {label} ==="]
    lines.append(f"Total trades: {len(trades)}")
    for strategy, count in by_strategy.items():
        lines.append(f"  {strategy}: {count}")
    lines.append(f"Closed trades: {len(closed)}, Win rate: {win_rate:.1f}%")
    lines.append(f"Total realized P&L: ${total_pnl:,.2f}")

    if wins:
        largest_win = max(wins, key=lambda t: t.pnl)
        lines.append(f"Largest win: {largest_win.symbol} ${largest_win.pnl:,.2f}")
    if losses:
        largest_loss = min(losses, key=lambda t: t.pnl)
        lines.append(f"Largest loss: {largest_loss.symbol} ${largest_loss.pnl:,.2f}")

    lines.append(f"Skipped/rejected orders: {len(skipped)}")
    for e in skipped[:10]:
        lines.append(f"  - {e.message}")

    lines.append(f"Risk events: {len(risk_events)}")
    for e in risk_events[:10]:
        lines.append(f"  - {e.message}")

    return "\n".join(lines)
