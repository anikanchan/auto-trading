import datetime as dt

from db.models import init_db
from monitoring import ledger


def test_log_event_and_query(tmp_path, monkeypatch):
    monkeypatch.setattr("db.models.get_db_path", lambda: tmp_path / "test_trading.db")
    init_db()

    ledger.log_event(ledger.CATEGORY_SIGNAL, "BUY signal for AAPL", {"symbol": "AAPL", "price": 150.0})
    ledger.log_event(ledger.CATEGORY_ORDER, "Submitted BUY 10 AAPL", {"symbol": "AAPL", "qty": 10})
    ledger.log_event(ledger.CATEGORY_RISK, "Order rejected: max position size")

    all_events = ledger.get_events()
    assert len(all_events) == 3
    # Oldest first
    assert all_events[0].category == ledger.CATEGORY_SIGNAL
    assert all_events[1].category == ledger.CATEGORY_ORDER
    assert all_events[2].category == ledger.CATEGORY_RISK


def test_get_events_filters_by_category(tmp_path, monkeypatch):
    monkeypatch.setattr("db.models.get_db_path", lambda: tmp_path / "test_trading.db")
    init_db()

    ledger.log_event(ledger.CATEGORY_SIGNAL, "Signal A")
    ledger.log_event(ledger.CATEGORY_ORDER, "Order A")
    ledger.log_event(ledger.CATEGORY_SIGNAL, "Signal B")

    signals = ledger.get_events(category=ledger.CATEGORY_SIGNAL)
    assert len(signals) == 2
    assert all(e.category == ledger.CATEGORY_SIGNAL for e in signals)


def test_get_recent_events_respects_window(tmp_path, monkeypatch):
    monkeypatch.setattr("db.models.get_db_path", lambda: tmp_path / "test_trading.db")
    init_db()

    ledger.log_event(ledger.CATEGORY_SYSTEM, "Recent event")

    recent = ledger.get_recent_events(days=7)
    assert len(recent) == 1

    # Window of 0 days, with start = now, should exclude the just-logged event
    none_found = ledger.get_events(start=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=5))
    assert none_found == []


def test_format_event_includes_details(tmp_path, monkeypatch):
    monkeypatch.setattr("db.models.get_db_path", lambda: tmp_path / "test_trading.db")
    init_db()

    entry = ledger.log_event(ledger.CATEGORY_ORDER, "Submitted BUY 10 AAPL", {"symbol": "AAPL", "qty": 10})
    formatted = ledger.format_event(entry)
    assert "ORDER" in formatted
    assert "Submitted BUY 10 AAPL" in formatted
    assert "symbol=AAPL" in formatted
    assert "qty=10" in formatted
