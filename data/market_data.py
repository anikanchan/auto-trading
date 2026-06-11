"""
Market data fetching.

Wraps Alpaca's historical data API (free with any Alpaca account, including
paper) to fetch OHLCV bars for backtesting and live signal generation.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from config.secrets import get_secret


class MarketData:
    """Fetches historical and latest price data via Alpaca."""

    def __init__(self) -> None:
        api_key = get_secret("alpaca-api-key-id")
        secret_key = get_secret("alpaca-api-secret-key")
        self.client = StockHistoricalDataClient(api_key=api_key, secret_key=secret_key)

    def get_daily_bars(
        self, symbol: str, start: dt.date, end: dt.date | None = None
    ) -> pd.DataFrame:
        """Fetch daily OHLCV bars for a symbol between start and end (inclusive)."""
        return self.get_bars(symbol, TimeFrame.Day, start, end)

    def get_bars(
        self,
        symbol: str,
        timeframe: TimeFrame,
        start: dt.date | dt.datetime,
        end: dt.date | dt.datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV bars for a symbol at the given timeframe.

        Returns a DataFrame indexed by timestamp with columns:
        open, high, low, close, volume, trade_count, vwap
        """
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
        )
        bars = self.client.get_stock_bars(request)
        df = bars.df

        if df.empty:
            return df

        # df has a MultiIndex (symbol, timestamp) when fetching a single symbol too
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level="symbol")

        return df

    def get_intraday_bars(
        self,
        symbol: str,
        start: dt.date | dt.datetime,
        end: dt.date | dt.datetime | None = None,
        minutes: int = 5,
    ) -> pd.DataFrame:
        """Fetch intraday bars at the given minute resolution."""
        timeframe = TimeFrame(minutes, TimeFrameUnit.Minute)
        return self.get_bars(symbol, timeframe, start, end)

    def get_latest_price(self, symbol: str) -> float:
        """Fetch the latest quote midpoint price for a symbol."""
        request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quotes = self.client.get_stock_latest_quote(request)
        quote = quotes[symbol]
        bid, ask = quote.bid_price, quote.ask_price
        if bid and ask:
            return (bid + ask) / 2
        return bid or ask


if __name__ == "__main__":
    import sys

    symbol = sys.argv[1] if len(sys.argv) > 1 else "SPY"
    md = MarketData()

    end = dt.date.today()
    start = end - dt.timedelta(days=10)

    print(f"Fetching daily bars for {symbol} from {start} to {end}...")
    bars = md.get_daily_bars(symbol, start, end)
    print(bars.tail())

    print(f"\nLatest price for {symbol}: {md.get_latest_price(symbol)}")
