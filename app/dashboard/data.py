"""
Data access helpers for the Streamlit dashboard.

Kept separate from `dashboard/app.py` (which imports `streamlit`) so these
functions can be unit tested without a Streamlit runtime.
"""

from __future__ import annotations

import csv
import datetime as dt
import io

from db.models import DailyPnL, Trade, get_session
from monitoring import ledger


def get_open_positions() -> list[Trade]:
    """Open trades the bot currently holds, per the local Trade table."""
    with get_session() as session:
        rows = session.query(Trade).filter_by(status="open").order_by(Trade.opened_at.desc()).all()
        for row in rows:
            session.expunge(row)
        return rows


def get_recent_trades(limit: int = 20) -> list[Trade]:
    """Most recently opened trades (open or closed), newest first."""
    with get_session() as session:
        rows = session.query(Trade).order_by(Trade.opened_at.desc()).limit(limit).all()
        for row in rows:
            session.expunge(row)
        return rows


def get_daily_pnl_history(days: int = 30) -> list[DailyPnL]:
    """Daily P&L snapshots for the last `days` days, oldest first."""
    cutoff = dt.datetime.combine(dt.date.today() - dt.timedelta(days=days), dt.time.min)
    with get_session() as session:
        rows = (
            session.query(DailyPnL)
            .filter(DailyPnL.date >= cutoff)
            .order_by(DailyPnL.date.asc())
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def get_recent_ledger_events(limit: int = 50, category: str | None = None) -> list:
    """Most recent ledger entries, newest first."""
    events = ledger.get_events(category=category)
    return list(reversed(events))[:limit]


def export_trades_csv(start: dt.datetime, end: dt.datetime) -> str:
    """Export trades opened within [start, end] as a CSV string, for the
    HISTORY command's "detailed CSV export" on longer date ranges."""
    with get_session() as session:
        rows = (
            session.query(Trade)
            .filter(Trade.opened_at >= start, Trade.opened_at <= end)
            .order_by(Trade.opened_at.asc())
            .all()
        )
        for row in rows:
            session.expunge(row)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["id", "symbol", "side", "quantity", "entry_price", "exit_price", "strategy", "status", "pnl", "opened_at", "closed_at"]
    )
    for t in rows:
        writer.writerow(
            [t.id, t.symbol, t.side, t.quantity, t.entry_price, t.exit_price, t.strategy, t.status, t.pnl, t.opened_at, t.closed_at]
        )
    return buffer.getvalue()
