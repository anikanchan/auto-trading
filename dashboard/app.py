"""
Streamlit dashboard — live P&L, open positions, recent trades, strategy
status, and a ledger/audit log viewer with CSV export.

Run with: streamlit run dashboard/app.py

Per the spec, this dashboard should be protected with basic auth
(`dashboard-basic-auth-user` / `dashboard-basic-auth-password` from the
Keychain) when exposed beyond localhost — that's handled at the reverse
proxy / hosting layer, not in this script.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from dashboard.data import (
    export_trades_csv,
    get_daily_pnl_history,
    get_open_positions,
    get_recent_ledger_events,
    get_recent_trades,
)
from db.models import init_db
from monitoring import ledger

st.set_page_config(page_title="Auto-Trading Dashboard", layout="wide")

init_db()

st.title("Auto-Trading Dashboard")


def _account_section() -> None:
    st.header("Account")
    try:
        from execution.alpaca_broker import AlpacaBroker

        broker = AlpacaBroker()
        account = broker.get_account()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Equity", f"${account.equity:,.2f}")
        col2.metric("Cash", f"${account.cash:,.2f}")
        col3.metric("Portfolio value", f"${account.portfolio_value:,.2f}")
        col4.metric("Mode", broker.mode.upper())
    except Exception as exc:  # noqa: BLE001 - dashboard should still render
        st.warning(f"Could not connect to broker: {exc}")


def _pnl_section() -> None:
    st.header("Daily P&L")
    history = get_daily_pnl_history(days=30)
    if not history:
        st.info("No daily P&L history yet.")
        return

    df = pd.DataFrame(
        {
            "date": [h.date for h in history],
            "equity": [h.ending_equity for h in history],
            "pnl": [h.pnl for h in history],
            "pnl_pct": [h.pnl_pct for h in history],
        }
    ).set_index("date")

    st.line_chart(df["equity"])
    st.dataframe(df)


def _positions_section() -> None:
    st.header("Open Positions")
    positions = get_open_positions()
    if not positions:
        st.info("No open positions.")
        return

    df = pd.DataFrame(
        [
            {
                "symbol": p.symbol,
                "side": p.side,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "strategy": p.strategy,
                "opened_at": p.opened_at,
            }
            for p in positions
        ]
    )
    st.dataframe(df, use_container_width=True)


def _recent_trades_section() -> None:
    st.header("Recent Trades")
    trades = get_recent_trades(limit=20)
    if not trades:
        st.info("No trades yet.")
        return

    df = pd.DataFrame(
        [
            {
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "strategy": t.strategy,
                "status": t.status,
                "opened_at": t.opened_at,
                "closed_at": t.closed_at,
            }
            for t in trades
        ]
    )
    st.dataframe(df, use_container_width=True)


def _ledger_section() -> None:
    st.header("Transaction Ledger")

    categories = ["All", ledger.CATEGORY_SIGNAL, ledger.CATEGORY_ORDER, ledger.CATEGORY_FILL,
                   ledger.CATEGORY_RISK, ledger.CATEGORY_COMMAND, ledger.CATEGORY_CONFIG,
                   ledger.CATEGORY_SYSTEM, ledger.CATEGORY_ERROR]
    selected = st.selectbox("Category", categories)
    category = None if selected == "All" else selected

    events = get_recent_ledger_events(limit=100, category=category)
    if not events:
        st.info("No ledger entries yet.")
        return

    df = pd.DataFrame(
        [{"timestamp": e.timestamp, "category": e.category, "message": e.message, "details": e.details} for e in events]
    )
    st.dataframe(df, use_container_width=True)


def _export_section() -> None:
    st.header("Export Trade History")
    col1, col2 = st.columns(2)
    start_date = col1.date_input("Start date", value=dt.date.today() - dt.timedelta(days=30))
    end_date = col2.date_input("End date", value=dt.date.today())

    start = dt.datetime.combine(start_date, dt.time.min)
    end = dt.datetime.combine(end_date, dt.time.max)

    csv_text = export_trades_csv(start, end)
    st.download_button(
        "Download CSV",
        data=csv_text,
        file_name=f"trades_{start_date}_{end_date}.csv",
        mime="text/csv",
    )


_account_section()
_pnl_section()
_positions_section()
_recent_trades_section()
_ledger_section()
_export_section()
