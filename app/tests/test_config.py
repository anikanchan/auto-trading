from config.loader import get, load_config


def test_load_config_returns_dict():
    config = load_config()
    assert isinstance(config, dict)
    assert "risk" in config


def test_get_top_level():
    assert get("mode") == "paper"


def test_get_nested():
    assert get("risk.max_position_pct") == 5


def test_get_missing_returns_default():
    assert get("does.not.exist", "fallback") == "fallback"


def test_get_missing_returns_none_by_default():
    assert get("does.not.exist") is None
