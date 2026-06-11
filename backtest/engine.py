"""
Backtesting engine.

Replays historical daily bars through a strategy + risk manager, simulating
trades to evaluate performance before any live/paper deployment.

This is a simple, single-symbol, long-only daily-bar simulator suitable for
validating Tier 1 swing strategies (SMA crossover, RSI mean reversion).
Intraday strategies (ORB) need a separate intraday backtester (future work).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from risk.risk_manager import OrderRequest, PortfolioState, RiskManager
from strategies.base import SignalAction, Strategy


@dataclass
class BacktestTrade:
    symbol: str
    side: str
    quantity: float
    price: float
    date: pd.Timestamp
    reason: str


@dataclass
class BacktestResult:
    starting_equity: float
    ending_equity: float
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)

    @property
    def total_return_pct(self) -> float:
        if self.starting_equity == 0:
            return 0.0
        return (self.ending_equity - self.starting_equity) / self.starting_equity * 100

    @property
    def num_trades(self) -> int:
        return len([t for t in self.trades if t.side == "buy"])

    @property
    def win_rate(self) -> float:
        round_trips = self._round_trips()
        if not round_trips:
            return 0.0
        wins = sum(1 for pnl in round_trips if pnl > 0)
        return wins / len(round_trips) * 100

    @property
    def max_drawdown_pct(self) -> float:
        if self.equity_curve.empty:
            return 0.0
        running_max = self.equity_curve.cummax()
        drawdown = (self.equity_curve - running_max) / running_max * 100
        return float(drawdown.min())

    @property
    def sharpe_ratio(self) -> float:
        if self.equity_curve.empty or len(self.equity_curve) < 2:
            return 0.0
        daily_returns = self.equity_curve.pct_change().dropna()
        if daily_returns.std() == 0:
            return 0.0
        # Annualized Sharpe (assuming ~252 trading days, 0% risk-free rate)
        return float(daily_returns.mean() / daily_returns.std() * (252 ** 0.5))

    def _round_trips(self) -> list[float]:
        """Pair up buy/sell trades and compute P&L per round trip."""
        pnls = []
        open_trade: BacktestTrade | None = None
        for trade in self.trades:
            if trade.side == "buy":
                open_trade = trade
            elif trade.side == "sell" and open_trade is not None:
                pnl = (trade.price - open_trade.price) * trade.quantity
                pnls.append(pnl)
                open_trade = None
        return pnls

    def summary(self) -> str:
        return (
            f"Starting equity: ${self.starting_equity:,.2f}\n"
            f"Ending equity:   ${self.ending_equity:,.2f}\n"
            f"Total return:    {self.total_return_pct:.2f}%\n"
            f"Trades:          {self.num_trades}\n"
            f"Win rate:        {self.win_rate:.1f}%\n"
            f"Max drawdown:    {self.max_drawdown_pct:.2f}%\n"
            f"Sharpe ratio:    {self.sharpe_ratio:.2f}"
        )


class BacktestEngine:
    """Single-symbol, long-only backtester for daily-bar swing strategies."""

    def __init__(
        self,
        strategy: Strategy,
        starting_equity: float = 100_000.0,
        position_pct: float | None = None,
    ) -> None:
        self.strategy = strategy
        self.starting_equity = starting_equity
        self.risk_manager = RiskManager()
        # Fraction of portfolio to allocate per trade; defaults to the
        # configured max position size.
        self.position_pct = position_pct or self.risk_manager.max_position_pct

    def run(self, symbol: str, bars: pd.DataFrame) -> BacktestResult:
        """Run the backtest over the given historical bars (oldest first)."""
        if bars.empty:
            return BacktestResult(starting_equity=self.starting_equity, ending_equity=self.starting_equity)

        min_bars = self.strategy.min_bars_required()

        cash = self.starting_equity
        shares_held = 0.0
        entry_price = 0.0
        trades: list[BacktestTrade] = []
        equity_curve = []
        equity_dates = []

        for i in range(min_bars, len(bars) + 1):
            window = bars.iloc[:i]
            current_bar = window.iloc[-1]
            date = window.index[-1]
            price = float(current_bar["close"])

            signal = self.strategy.generate_signal(symbol, window)

            if signal.action == SignalAction.BUY and shares_held == 0:
                portfolio_value = cash  # all cash, no position
                order_value = portfolio_value * (self.position_pct / 100)
                quantity = order_value // price  # whole shares

                if quantity > 0:
                    state = PortfolioState(
                        portfolio_value=portfolio_value,
                        cash=cash,
                        open_positions=0,
                        daily_starting_equity=portfolio_value,
                        daily_current_equity=portfolio_value,
                    )
                    order = OrderRequest(symbol=symbol, side="buy", quantity=quantity, price=price)
                    decision = self.risk_manager.evaluate_order(order, state)

                    if decision.approved:
                        cost = quantity * price
                        cash -= cost
                        shares_held = quantity
                        entry_price = price
                        trades.append(
                            BacktestTrade(
                                symbol=symbol, side="buy", quantity=quantity,
                                price=price, date=date, reason=signal.reason,
                            )
                        )

            elif signal.action == SignalAction.SELL and shares_held > 0:
                proceeds = shares_held * price
                cash += proceeds
                trades.append(
                    BacktestTrade(
                        symbol=symbol, side="sell", quantity=shares_held,
                        price=price, date=date, reason=signal.reason,
                    )
                )
                shares_held = 0.0
                entry_price = 0.0

            # Mark-to-market equity for this bar
            equity = cash + shares_held * price
            equity_curve.append(equity)
            equity_dates.append(date)

        # Liquidate any open position at the final price for ending equity
        final_price = float(bars.iloc[-1]["close"])
        ending_equity = cash + shares_held * final_price

        return BacktestResult(
            starting_equity=self.starting_equity,
            ending_equity=ending_equity,
            trades=trades,
            equity_curve=pd.Series(equity_curve, index=pd.Index(equity_dates)),
        )


if __name__ == "__main__":
    import datetime as dt
    import sys

    from data.market_data import MarketData
    from strategies.sma_crossover import SmaCrossoverStrategy

    symbol = sys.argv[1] if len(sys.argv) > 1 else "SPY"
    years = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    end = dt.date.today()
    start = end - dt.timedelta(days=365 * years)

    print(f"Fetching {years} years of daily bars for {symbol}...")
    md = MarketData()
    bars = md.get_daily_bars(symbol, start, end)
    print(f"Got {len(bars)} bars from {bars.index[0]} to {bars.index[-1]}\n")

    strategy = SmaCrossoverStrategy({"fast_period": 20, "slow_period": 50})
    engine = BacktestEngine(strategy, starting_equity=100_000.0)
    result = engine.run(symbol, bars)

    print(f"Strategy: {strategy.name} (fast={strategy.fast_period}, slow={strategy.slow_period})")
    print(f"Symbol: {symbol}")
    print("-" * 40)
    print(result.summary())
    print("-" * 40)
    print(f"\nLast 5 trades:")
    for t in result.trades[-5:]:
        print(f"  {t.date.date()} {t.side.upper():4s} {t.quantity:6.0f} @ ${t.price:.2f}  ({t.reason})")
