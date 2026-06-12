"""
Alpaca broker client wrapper.

Wraps alpaca-py's TradingClient to provide a small, app-specific surface
for account info, positions, and order placement. Always defaults to the
paper trading endpoint unless config.mode == "live".
"""

from __future__ import annotations

from dataclasses import dataclass

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
)

from config.loader import get as get_config
from config.secrets import get_alpaca_credentials


@dataclass
class AccountInfo:
    account_id: str
    status: str
    cash: float
    portfolio_value: float
    buying_power: float
    equity: float


class AlpacaBroker:
    """Thin wrapper around the Alpaca Trading API."""

    def __init__(self) -> None:
        self.mode = get_config("mode", "paper")
        is_paper = self.mode != "live"

        self.account_type = get_config("alpaca.account_type", "personal")
        api_key, secret_key = get_alpaca_credentials()

        self.client = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=is_paper,
        )

    def get_account(self) -> AccountInfo:
        """Fetch current account summary."""
        account = self.client.get_account()
        return AccountInfo(
            account_id=str(account.id),
            status=str(account.status),
            cash=float(account.cash),
            portfolio_value=float(account.portfolio_value),
            buying_power=float(account.buying_power),
            equity=float(account.equity),
        )

    def get_positions(self) -> list[dict]:
        """Fetch all open positions."""
        positions = self.client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": str(p.side),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price) if p.current_price else None,
                "market_value": float(p.market_value) if p.market_value else None,
                "unrealized_pl": float(p.unrealized_pl) if p.unrealized_pl else None,
                "unrealized_plpc": float(p.unrealized_plpc) if p.unrealized_plpc else None,
            }
            for p in positions
        ]

    def is_market_open(self) -> bool:
        """Check whether the market is currently open."""
        clock = self.client.get_clock()
        return bool(clock.is_open)

    def submit_market_order(self, symbol: str, qty: float, side: str) -> dict:
        """Submit a market order. side is 'buy' or 'sell'."""
        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )
        order = self.client.submit_order(request)
        return self._order_to_dict(order)

    def submit_limit_order(
        self, symbol: str, qty: float, side: str, limit_price: float
    ) -> dict:
        """Submit a limit order. side is 'buy' or 'sell'."""
        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY,
            limit_price=limit_price,
        )
        order = self.client.submit_order(request)
        return self._order_to_dict(order)

    def flatten_all_positions(self) -> None:
        """Emergency: close all open positions immediately."""
        self.client.close_all_positions(cancel_orders=True)

    @staticmethod
    def _order_to_dict(order) -> dict:
        return {
            "id": str(order.id),
            "symbol": order.symbol,
            "qty": float(order.qty) if order.qty else None,
            "side": str(order.side),
            "type": str(order.order_type),
            "status": str(order.status),
            "limit_price": float(order.limit_price) if order.limit_price else None,
            "submitted_at": str(order.submitted_at),
        }


if __name__ == "__main__":
    # Quick smoke test: verify connectivity and print account info.
    broker = AlpacaBroker()
    account = broker.get_account()
    print(f"Mode: {broker.mode}")
    print(f"Account type: {broker.account_type}")
    print(f"Account ID: {account.account_id}")
    print(f"Status: {account.status}")
    print(f"Cash: ${account.cash:,.2f}")
    print(f"Portfolio value: ${account.portfolio_value:,.2f}")
    print(f"Buying power: ${account.buying_power:,.2f}")
    print(f"Market open: {broker.is_market_open()}")
    print(f"Positions: {broker.get_positions()}")
