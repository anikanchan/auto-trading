import pytest

import config.loader
import config.secrets
from config.secrets import get_alpaca_credentials


def test_personal_account_uses_default_keys(monkeypatch):
    monkeypatch.setattr(config.secrets, "_get_from_keyring", lambda name: None)
    monkeypatch.setattr(
        config.loader, "get", lambda key, default=None: "personal"
        if key == "alpaca.account_type" else default
    )
    monkeypatch.setenv("AUTOTRADING_ALPACA_API_KEY_ID", "personal-key")
    monkeypatch.setenv("AUTOTRADING_ALPACA_API_SECRET_KEY", "personal-secret")
    assert get_alpaca_credentials() == ("personal-key", "personal-secret")


def test_business_account_uses_business_keys(monkeypatch):
    monkeypatch.setattr(config.secrets, "_get_from_keyring", lambda name: None)
    monkeypatch.setattr(
        config.loader, "get", lambda key, default=None: "business"
        if key == "alpaca.account_type" else default
    )
    monkeypatch.setenv("AUTOTRADING_ALPACA_BUSINESS_API_KEY_ID", "biz-key")
    monkeypatch.setenv("AUTOTRADING_ALPACA_BUSINESS_API_SECRET_KEY", "biz-secret")
    assert get_alpaca_credentials() == ("biz-key", "biz-secret")


def test_invalid_account_type_raises(monkeypatch):
    monkeypatch.setattr(
        config.loader, "get", lambda key, default=None: "hedge-fund"
        if key == "alpaca.account_type" else default
    )
    with pytest.raises(ValueError, match="hedge-fund"):
        get_alpaca_credentials()
