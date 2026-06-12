"""
Trading scheduler.

Wires together strategies + market data + OrderManager into recurring
jobs:
  - `run_strategy_scan()`: for each enabled strategy and symbol in its
    universe, fetch bars, generate a signal, and route it through
    OrderManager.process_signal().
  - `run_eod_report()`: builds the end-of-day summary (sent via messaging,
    wired up separately).
  - `run_kill_switch_check()`: refreshes the daily P&L snapshot and flips
    the kill-switch if the daily loss limit is breached.

The APScheduler wiring (`start()`) registers these as cron jobs per
`config/settings.yaml` schedule. The job logic itself is kept dependency-
light and broker/market-data-injectable so it can be unit tested without a
live scheduler or network calls.
"""

from __future__ import annotations

import datetime as dt
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler

from config.loader import get as get_config
from data.market_data import MarketData
from execution.order_manager import ConfirmCallback, OrderManager
from monitoring import ledger
from strategies.base import Strategy
from strategies.orb import OrbStrategy
from strategies.rsi_mean_reversion import RsiMeanReversionStrategy
from strategies.sma_crossover import SmaCrossoverStrategy

# Maps config keys (config/settings.yaml -> strategies.<key>) to classes.
STRATEGY_CLASSES: dict[str, type[Strategy]] = {
    "sma_crossover": SmaCrossoverStrategy,
    "orb": OrbStrategy,
    "rsi_mean_reversion": RsiMeanReversionStrategy,
}

# Strategies that operate on intraday bars rather than daily bars.
INTRADAY_STRATEGIES = {"orb"}


def load_strategies_from_config() -> list[tuple[Strategy, list[str]]]:
    """Build (strategy_instance, universe) pairs for every enabled
    strategy in config/settings.yaml. Falls back to the global watchlist
    if a strategy doesn't define its own universe."""
    strategies_cfg = get_config("strategies", {}) or {}
    default_universe = get_config("watchlist", []) or []

    result: list[tuple[Strategy, list[str]]] = []
    for key, cfg in strategies_cfg.items():
        if not cfg or not cfg.get("enabled", False):
            continue
        strategy_cls = STRATEGY_CLASSES.get(key)
        if strategy_cls is None:
            continue
        universe = cfg.get("universe") or default_universe
        result.append((strategy_cls(cfg), list(universe)))

    return result


class TradingScheduler:
    def __init__(
        self,
        order_manager: OrderManager | None = None,
        market_data: MarketData | None = None,
        strategies: list[tuple[Strategy, list[str]]] | None = None,
        confirm_callback: ConfirmCallback | None = None,
    ) -> None:
        self.order_manager = order_manager or OrderManager()
        self.market_data = market_data or MarketData()
        self.strategies = strategies if strategies is not None else load_strategies_from_config()
        self.confirm_callback = confirm_callback
        self.scheduler = BackgroundScheduler(timezone="America/New_York")
        self.paused = False
        self.stopped_symbols: set[str] = set()

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    def run_strategy_scan(self) -> list[dict]:
        """Run every enabled strategy across its symbol universe and route
        any non-HOLD signal through the OrderManager. Returns the list of
        process_signal() results (for testing/inspection)."""
        if self.paused:
            ledger.log_event(ledger.CATEGORY_SYSTEM, "Strategy scan skipped: bot is paused")
            return []

        results = []
        for strategy, universe in self.strategies:
            for symbol in universe:
                if symbol in self.stopped_symbols:
                    continue
                try:
                    bars = self._get_bars(strategy, symbol)
                except Exception as exc:  # noqa: BLE001 - log and continue scanning
                    ledger.log_event(
                        ledger.CATEGORY_ERROR,
                        f"Failed to fetch bars for {symbol} ({strategy.name})",
                        {"error": str(exc)},
                    )
                    continue

                if len(bars) < strategy.min_bars_required():
                    continue

                signal = strategy.generate_signal(symbol, bars)
                result = self.order_manager.process_signal(signal, confirm_callback=self.confirm_callback)
                results.append(result)

        return results

    def _get_bars(self, strategy: Strategy, symbol: str):
        end = dt.date.today()
        if strategy.name in INTRADAY_STRATEGIES:
            range_minutes = int(getattr(strategy, "range_minutes", 30))
            start = end  # today only
            return self.market_data.get_intraday_bars(symbol, start, end, minutes=5)

        # Daily bars: fetch enough history for the slowest indicator, plus buffer.
        lookback_days = max(strategy.min_bars_required() * 2, 60)
        start = end - dt.timedelta(days=lookback_days)
        return self.market_data.get_daily_bars(symbol, start, end)

    def run_kill_switch_check(self) -> bool:
        """Refresh today's P&L snapshot and trip the kill-switch if the
        daily loss limit is breached. Returns True if the kill switch is
        (now) active."""
        state = self.order_manager.build_portfolio_state()
        decision = self.order_manager.risk_manager.check_daily_kill_switch(state)
        triggered = not decision.approved

        self.order_manager.update_daily_pnl(state.daily_current_equity, kill_switch_triggered=triggered)

        if triggered:
            ledger.log_event(ledger.CATEGORY_RISK, decision.reason)

        return triggered

    def run_eod_report(self) -> str:
        """Build the end-of-day summary text. Sending it is handled by the
        messaging/alerts layer (wired up separately)."""
        state = self.order_manager.build_portfolio_state()
        pnl = state.daily_current_equity - state.daily_starting_equity
        pnl_pct = (pnl / state.daily_starting_equity * 100) if state.daily_starting_equity else 0.0

        today_start = dt.datetime.combine(dt.date.today(), dt.time.min, tzinfo=dt.timezone.utc)
        today_events = ledger.get_events(start=today_start, category=ledger.CATEGORY_ORDER)

        lines = [
            f"=== EOD Report {dt.date.today().isoformat()} ===",
            f"Equity: ${state.daily_current_equity:,.2f} (start: ${state.daily_starting_equity:,.2f})",
            f"P&L: ${pnl:,.2f} ({pnl_pct:+.2f}%)",
            f"Open positions: {state.open_positions}",
            f"Orders today: {len(today_events)}",
        ]
        for event in today_events:
            lines.append(f"  - {event.message}")

        report = "\n".join(lines)
        ledger.log_event(ledger.CATEGORY_SYSTEM, "EOD report generated", {"pnl": pnl, "pnl_pct": pnl_pct})
        return report

    # ------------------------------------------------------------------
    # Pause / resume (for the PAUSE / RESUME commands)
    # ------------------------------------------------------------------

    def pause(self) -> None:
        self.paused = True
        ledger.log_event(ledger.CATEGORY_COMMAND, "Trading paused")

    def resume(self) -> None:
        self.paused = False
        ledger.log_event(ledger.CATEGORY_COMMAND, "Trading resumed")

    # ------------------------------------------------------------------
    # APScheduler wiring
    # ------------------------------------------------------------------

    def start(self) -> None:
        market_open = get_config("schedule.market_open", "09:30")
        market_close = get_config("schedule.market_close", "16:00")
        eod_time = get_config("schedule.eod_report_time", "16:25")

        open_hour, open_minute = (int(p) for p in market_open.split(":"))
        close_hour, close_minute = (int(p) for p in market_close.split(":"))
        eod_hour, eod_minute = (int(p) for p in eod_time.split(":"))

        self.scheduler.add_job(
            self.run_strategy_scan,
            "cron",
            day_of_week="mon-fri",
            hour=f"{open_hour}-{close_hour}",
            minute="*/15",
            id="strategy_scan",
        )
        self.scheduler.add_job(
            self.run_kill_switch_check,
            "cron",
            day_of_week="mon-fri",
            hour=f"{open_hour}-{close_hour}",
            minute="*/5",
            id="kill_switch_check",
        )
        self.scheduler.add_job(
            self.run_eod_report,
            "cron",
            day_of_week="mon-fri",
            hour=eod_hour,
            minute=eod_minute,
            id="eod_report",
        )

        self.scheduler.start()

    def stop(self) -> None:
        self.scheduler.shutdown()


if __name__ == "__main__":
    scheduler = TradingScheduler()
    print("Loaded strategies:")
    for strategy, universe in scheduler.strategies:
        print(f"  {strategy.name}: {universe}")
