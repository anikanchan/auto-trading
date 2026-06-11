import datetime as dt

import pytest

from dashboard.data import (
    export_trades_csv,
    get_daily_pnl_history,
    get_open_positions,
    get_recent_ledger_events,
    get_recent_trades,
)
from db.models import DailyPnL, Trade, get_session, init_db
from monitoring import ledger


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.models.get_db_path", lambda: tmp_path / "test_trading.db")
    init_db()


def test_get_open_positions(isolated_db):
    with get_session() as session:
        session.add(Trade(symbol="AAPL", side="buy", quantity=10, entry_price=100.0, strategy="sma_crossover", status="open"))
        session.add(Trade(symbol="MSFT", side="buy", quantity=5, entry_price=200.0, strategy="sma_crossover", status="closed", exit_price=210.0, pnl=50.0))
        session.commit()

    open_positions = get_open_positions()
    assert len(open_positions) == 1
    assert open_positions[0].symbol == "AAPL"


def test_get_recent_trades_respects_limit(isolated_db):
    with get_session() as session:
        for i in range(5):
            session.add(Trade(symbol=f"SYM{i}", side="buy", quantity=1, entry_price=10.0, strategy="test"))
        session.commit()

    trades = get_recent_trades(limit=3)
    assert len(trades) == 3


def test_get_daily_pnl_history(isolated_db):
    today = dt.datetime.combine(dt.date.today(), dt.time.min)
    with get_session() as session:
        session.add(DailyPnL(date=today, starting_equity=100_000, ending_equity=101_000, pnl=1000, pnl_pct=1.0))
        session.commit()

    history = get_daily_pnl_history(days=7)
    assert len(history) == 1
    assert history[0].pnl == 1000


def test_get_recent_ledger_events_newest_first(isolated_db):
    ledger.log_event(ledger.CATEGORY_SYSTEM, "First event")
    ledger.log_event(ledger.CATEGORY_SYSTEM, "Second event")

    events = get_recent_ledger_events()
    assert events[0].message == "Second event"
    assert events[1].message == "First event"


def test_get_recent_ledger_events_filters_category(isolated_db):
    ledger.log_event(ledger.CATEGORY_SYSTEM, "System event")
    ledger.log_event(ledger.CATEGORY_ORDER, "Order event")

    events = get_recent_ledger_events(category=ledger.CATEGORY_ORDER)
    assert len(events) == 1
    assert events[0].message == "Order event"


def test_export_trades_csv(isolated_db):
    with get_session() as session:
        session.add(Trade(symbol="AAPL", side="buy", quantity=10, entry_price=100.0, strategy="sma_crossover", status="open"))
        session.commit()

    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    end = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)

    csv_text = export_trades_csv(start, end)
    assert "AAPL" in csv_text
    assert "symbol" in csv_text.splitlines()[0]
