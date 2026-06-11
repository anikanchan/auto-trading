import pytest

from risk.risk_manager import OrderRequest, PortfolioState, RiskManager


@pytest.fixture
def risk_manager():
    return RiskManager(
        params={
            "max_portfolio_deployed_pct": 50,
            "max_position_pct": 5,
            "daily_loss_kill_switch_pct": -2,
            "stop_loss_pct": -1.5,
            "max_concurrent_positions": 10,
        }
    )


@pytest.fixture
def healthy_state():
    return PortfolioState(
        portfolio_value=100_000,
        cash=100_000,
        open_positions=0,
        daily_starting_equity=100_000,
        daily_current_equity=100_000,
    )


def test_order_within_limits_approved(risk_manager, healthy_state):
    # 5% of 100k = $5,000; 100 shares @ $50 = $5,000 -> exactly at the limit
    order = OrderRequest(symbol="AAPL", side="buy", quantity=100, price=50)
    decision = risk_manager.evaluate_order(order, healthy_state)
    assert decision.approved


def test_order_exceeding_position_size_rejected(risk_manager, healthy_state):
    # 6% of portfolio -> exceeds 5% max
    order = OrderRequest(symbol="AAPL", side="buy", quantity=120, price=50)
    decision = risk_manager.evaluate_order(order, healthy_state)
    assert not decision.approved
    assert "max position size" in decision.reason


def test_max_concurrent_positions_rejected(risk_manager, healthy_state):
    healthy_state.open_positions = 10
    order = OrderRequest(symbol="AAPL", side="buy", quantity=10, price=50)
    decision = risk_manager.evaluate_order(order, healthy_state)
    assert not decision.approved
    assert "max concurrent positions" in decision.reason


def test_max_portfolio_deployed_rejected(risk_manager):
    # Already 48% deployed; a new 5% order would push to 53% > 50% limit
    state = PortfolioState(
        portfolio_value=100_000,
        cash=52_000,
        open_positions=1,
        daily_starting_equity=100_000,
        daily_current_equity=100_000,
    )
    order = OrderRequest(symbol="AAPL", side="buy", quantity=100, price=50)  # $5,000 = 5%
    decision = risk_manager.evaluate_order(order, state)
    assert not decision.approved
    assert "deployed capital" in decision.reason


def test_insufficient_cash_rejected(risk_manager):
    state = PortfolioState(
        portfolio_value=100_000,
        cash=1_000,  # not enough for the order, even though % checks pass
        open_positions=0,
        daily_starting_equity=100_000,
        daily_current_equity=100_000,
    )
    order = OrderRequest(symbol="AAPL", side="buy", quantity=100, price=50)  # $5,000
    decision = risk_manager.evaluate_order(order, state)
    assert not decision.approved
    assert "Insufficient cash" in decision.reason


def test_sell_orders_always_approved(risk_manager, healthy_state):
    healthy_state.open_positions = 10  # at max, but selling should still work
    order = OrderRequest(symbol="AAPL", side="sell", quantity=100, price=50)
    decision = risk_manager.evaluate_order(order, healthy_state)
    assert decision.approved


def test_daily_kill_switch_triggers_on_loss(risk_manager):
    state = PortfolioState(
        portfolio_value=98_000,
        cash=98_000,
        open_positions=0,
        daily_starting_equity=100_000,
        daily_current_equity=97_900,  # down 2.1%
    )
    decision = risk_manager.check_daily_kill_switch(state)
    assert not decision.approved
    assert "kill-switch triggered" in decision.reason


def test_daily_kill_switch_blocks_new_buys(risk_manager):
    state = PortfolioState(
        portfolio_value=98_000,
        cash=98_000,
        open_positions=0,
        daily_starting_equity=100_000,
        daily_current_equity=97_900,  # down 2.1% -> kill switch should trip
    )
    order = OrderRequest(symbol="AAPL", side="buy", quantity=10, price=50)
    decision = risk_manager.evaluate_order(order, state)
    assert not decision.approved


def test_kill_switch_active_flag_blocks_buys(risk_manager, healthy_state):
    healthy_state.kill_switch_active = True
    order = OrderRequest(symbol="AAPL", side="buy", quantity=10, price=50)
    decision = risk_manager.evaluate_order(order, healthy_state)
    assert not decision.approved
    assert "kill-switch is active" in decision.reason


def test_calculate_stop_loss_price_for_long(risk_manager):
    stop = risk_manager.calculate_stop_loss_price(100, "buy")
    assert stop == pytest.approx(98.5)
