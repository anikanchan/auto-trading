import pytest

from db.models import init_db
from execution.day_orders import DayOrderWatcher


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.models.get_db_path", lambda: tmp_path / "test_trading.db")
    init_db()


class FakeOrderManager:
    def __init__(self, status="submitted"):
        self.calls = []
        self.status = status

    def process_manual_order(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": self.status, "reason": "position limit breached"}


class FakeMarketData:
    def __init__(self):
        self.price = 0.0

    def get_latest_price(self, symbol):
        return self.price


def make_watcher(status="submitted", notify=None):
    om = FakeOrderManager(status=status)
    md = FakeMarketData()
    watcher = DayOrderWatcher(om, market_data=md, rebound_pct=0.2, notify=notify)
    return watcher, om, md


def test_buy_waits_until_target_hit():
    watcher, om, md = make_watcher()
    watcher.add("AAPL", "buy", 10, 190.0)

    md.price = 195.0
    watcher.poll()

    assert om.calls == []
    assert watcher.active[0].armed is False


def test_buy_arms_tracks_low_and_executes_on_rebound():
    watcher, om, md = make_watcher()
    watcher.add("AAPL", "buy", 10, 190.0)

    for price in (190.0, 189.0, 188.0):  # touch target, then keep falling
        md.price = price
        watcher.poll()
    assert om.calls == []  # still falling — keep waiting for a better price
    assert watcher.active[0].best_price == 188.0

    md.price = 188.6  # rebound > 0.2% off the 188.00 low, still under target
    watcher.poll()

    assert len(om.calls) == 1
    assert om.calls[0]["symbol"] == "AAPL"
    assert om.calls[0]["side"] == "buy"
    assert om.calls[0]["limit_price"] == 190.0
    assert om.calls[0]["strategy"] == "day_order"
    assert watcher.active == []


def test_buy_disarms_if_price_recovers_above_target():
    watcher, om, md = make_watcher()
    watcher.add("AAPL", "buy", 10, 190.0)

    md.price = 189.5
    watcher.poll()  # armed
    assert watcher.active[0].armed is True

    md.price = 191.0
    watcher.poll()  # back above target before rebound triggered

    assert om.calls == []
    assert watcher.active[0].armed is False
    assert watcher.active[0].best_price is None


def test_sell_arms_tracks_high_and_executes_on_pullback():
    watcher, om, md = make_watcher()
    watcher.add("AAPL", "sell", 5, 200.0)

    md.price = 199.0
    watcher.poll()
    assert om.calls == []

    for price in (200.0, 202.0, 203.0):  # touch target, then keep rising
        md.price = price
        watcher.poll()
    assert om.calls == []
    assert watcher.active[0].best_price == 203.0

    md.price = 202.4  # pullback > 0.2% off the 203.00 high, still above target
    watcher.poll()

    assert len(om.calls) == 1
    assert om.calls[0]["side"] == "sell"
    assert om.calls[0]["limit_price"] == 200.0
    assert watcher.active == []


def test_executed_order_notifies():
    sent = []
    watcher, om, md = make_watcher(notify=sent.append)
    watcher.add("AAPL", "buy", 10, 190.0)

    md.price = 188.0
    watcher.poll()
    md.price = 189.0
    watcher.poll()

    assert len(sent) == 1
    assert "Day order executed" in sent[0]


def test_rejected_execution_removes_order_and_notifies():
    sent = []
    watcher, om, md = make_watcher(status="rejected", notify=sent.append)
    watcher.add("AAPL", "buy", 10, 190.0)

    md.price = 188.0
    watcher.poll()
    md.price = 189.0
    watcher.poll()

    assert watcher.active == []
    assert "rejected" in sent[0]
    assert "position limit breached" in sent[0]


def test_expire_all_clears_and_notifies():
    sent = []
    watcher, om, md = make_watcher(notify=sent.append)
    watcher.add("AAPL", "buy", 10, 190.0)
    watcher.add("SPY", "sell", 5, 500.0)

    watcher.expire_all()

    assert watcher.active == []
    assert len(sent) == 2
    assert all("expired" in text for text in sent)
