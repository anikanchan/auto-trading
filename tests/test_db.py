import datetime as dt

from db.models import AuditLog, Trade, get_engine, init_db
from sqlalchemy.orm import Session


def test_init_db_and_insert(tmp_path, monkeypatch):
    # Use an isolated temp DB for this test
    monkeypatch.setattr(
        "db.models.get_db_path", lambda: tmp_path / "test_trading.db"
    )
    init_db()

    with Session(get_engine()) as session:
        trade = Trade(
            symbol="AAPL",
            side="buy",
            quantity=10,
            entry_price=189.50,
            strategy="manual",
        )
        session.add(trade)

        log = AuditLog(category="signal", message="Test signal generated")
        session.add(log)

        session.commit()

        assert session.query(Trade).count() == 1
        assert session.query(AuditLog).count() == 1

        saved_trade = session.query(Trade).first()
        assert saved_trade.symbol == "AAPL"
        assert saved_trade.status == "open"
        assert isinstance(saved_trade.opened_at, dt.datetime)
