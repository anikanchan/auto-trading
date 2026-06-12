import datetime as dt

import pytest

from commands.parser import CommandParseError, parse_command


def test_simple_commands_case_insensitive():
    for text in ["status", "STATUS", "Status"]:
        cmd = parse_command(text)
        assert cmd.name == "STATUS"


@pytest.mark.parametrize("name", ["PAUSE", "RESUME", "FLATTEN", "REPORT", "HELP", "YES", "NO"])
def test_no_arg_commands(name):
    cmd = parse_command(name.lower())
    assert cmd.name == name
    assert cmd.args == {}


def test_unknown_command():
    cmd = parse_command("WHAT IS UP")
    assert cmd.name == "UNKNOWN"


def test_empty_string_is_unknown():
    cmd = parse_command("   ")
    assert cmd.name == "UNKNOWN"


def test_stop_requires_symbol():
    with pytest.raises(CommandParseError):
        parse_command("STOP")


def test_stop_with_symbol():
    cmd = parse_command("stop aapl")
    assert cmd.name == "STOP"
    assert cmd.args == {"symbol": "AAPL"}


def test_history_default():
    cmd = parse_command("HISTORY")
    assert cmd.args == {"days": 7}


def test_history_n_days():
    cmd = parse_command("HISTORY 30D")
    assert cmd.args == {"days": 30}


def test_history_date_range():
    cmd = parse_command("HISTORY 2026-01-01..2026-01-31")
    assert cmd.args == {"start": dt.date(2026, 1, 1), "end": dt.date(2026, 1, 31)}


def test_history_invalid_range_order():
    with pytest.raises(CommandParseError):
        parse_command("HISTORY 2026-01-31..2026-01-01")


def test_history_invalid_format():
    with pytest.raises(CommandParseError):
        parse_command("HISTORY banana")


def test_risk_command():
    cmd = parse_command("RISK MAXPOS 3%")
    assert cmd.name == "RISK"
    assert cmd.args == {"param": "MAXPOS", "value": "3%"}


def test_risk_requires_value():
    with pytest.raises(CommandParseError):
        parse_command("RISK MAXPOS")


def test_buy_market_order():
    cmd = parse_command("BUY AAPL 10")
    assert cmd.name == "BUY"
    assert cmd.args == {"symbol": "AAPL", "quantity": 10.0, "limit_price": None, "day_price": None}


def test_buy_with_max_price():
    cmd = parse_command("buy aapl 10 max 190.00")
    assert cmd.name == "BUY"
    assert cmd.args == {"symbol": "AAPL", "quantity": 10.0, "limit_price": 190.0, "day_price": None}


def test_sell_with_min_price():
    cmd = parse_command("SELL AAPL 5 MIN 185.00")
    assert cmd.args == {"symbol": "AAPL", "quantity": 5.0, "limit_price": 185.0, "day_price": None}


def test_buy_with_day_price():
    cmd = parse_command("buy aapl 10 day 190.00")
    assert cmd.name == "BUY"
    assert cmd.args == {"symbol": "AAPL", "quantity": 10.0, "limit_price": None, "day_price": 190.0}


def test_sell_with_day_price():
    cmd = parse_command("SELL AAPL 5 DAY 200.50")
    assert cmd.args == {"symbol": "AAPL", "quantity": 5.0, "limit_price": None, "day_price": 200.5}


def test_day_price_must_be_a_number():
    with pytest.raises(CommandParseError):
        parse_command("BUY AAPL 10 DAY CHEAP")


def test_day_price_must_be_positive():
    with pytest.raises(CommandParseError):
        parse_command("BUY AAPL 10 DAY -5")


def test_sell_with_wrong_modifier_raises():
    with pytest.raises(CommandParseError):
        parse_command("SELL AAPL 5 MAX 185.00")


def test_buy_missing_quantity_raises():
    with pytest.raises(CommandParseError):
        parse_command("BUY AAPL")


def test_buy_invalid_quantity_raises():
    with pytest.raises(CommandParseError):
        parse_command("BUY AAPL TEN")


def test_buy_negative_quantity_raises():
    with pytest.raises(CommandParseError):
        parse_command("BUY AAPL -10")


def test_buy_with_price_missing_modifier_raises():
    with pytest.raises(CommandParseError):
        parse_command("BUY AAPL 10 190.00")
