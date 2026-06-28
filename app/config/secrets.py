"""
Secrets management for the auto-trading app.

Locally (Mac), secrets are stored in the macOS Keychain via the `keyring`
library. When deployed to AWS, this module can be swapped for a backend
that reads from AWS Secrets Manager (env vars injected by ECS) without
changing any calling code.

Usage:
    from config.secrets import get_secret
    api_key = get_secret("alpaca-api-key-id")

Setting a secret (one-time, from a script or REPL):
    from config.secrets import set_secret
    set_secret("alpaca-api-key-id", "AKFAKE123...")
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the app root (app/.env). override=False means real shell env
# vars take precedence over .env values, preserving the env > keyring order.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

SERVICE_NAME = "auto-trading"

# Names of all secrets the app expects. Centralized here so it's easy to
# see what needs to be provisioned, and so typos are caught early.
SECRET_KEYS = (
    "alpaca-api-key-id",
    "alpaca-api-secret-key",
    "alpaca-account-id",
    # Business (entity) account variants (used when alpaca.account_type == business)
    "alpaca-business-api-key-id",
    "alpaca-business-api-secret-key",
    "alpaca-business-account-id",
    "polygon-api-key",
    "dashboard-basic-auth-user",
    "dashboard-basic-auth-password",
    "allowed-phone-number",
    # AWS / Twilio variants (used when messaging.channel == whatsapp)
    "twilio-account-sid",
    "twilio-auth-token",
    "twilio-whatsapp-number",
)


# Keychain key prefix per Alpaca account type (alpaca.account_type in
# settings.yaml). The trading API is identical for both — only which
# credentials are loaded differs.
ALPACA_KEY_PREFIXES = {
    "personal": "alpaca",
    "business": "alpaca-business",
}


class SecretNotFoundError(Exception):
    """Raised when a required secret isn't available in any backend."""


def get_alpaca_credentials() -> tuple[str, str]:
    """Return (api_key_id, api_secret_key) for the configured Alpaca account type."""
    from config.loader import get as get_config

    account_type = get_config("alpaca.account_type", "personal")
    if account_type not in ALPACA_KEY_PREFIXES:
        raise ValueError(
            f"Invalid alpaca.account_type: {account_type!r} "
            f"(expected one of {', '.join(ALPACA_KEY_PREFIXES)})"
        )
    prefix = ALPACA_KEY_PREFIXES[account_type]
    return get_secret(f"{prefix}-api-key-id"), get_secret(f"{prefix}-api-secret-key")


def _get_from_env(name: str) -> str | None:
    """Allow overriding via environment variables (useful for CI / containers).

    Convention: AUTOTRADING_<NAME_UPPER_WITH_UNDERSCORES>
    e.g. alpaca-api-key-id -> AUTOTRADING_ALPACA_API_KEY_ID
    """
    env_name = "AUTOTRADING_" + name.upper().replace("-", "_")
    return os.environ.get(env_name)


def _get_from_keyring(name: str) -> str | None:
    try:
        import keyring
    except ImportError:
        return None
    return keyring.get_password(SERVICE_NAME, name)


def get_secret(name: str, required: bool = True) -> str | None:
    """Retrieve a secret by name.

    Lookup order:
      1. Environment variable (AUTOTRADING_<NAME>) — useful for containers/CI
      2. macOS Keychain via `keyring`

    Raises SecretNotFoundError if `required` is True and the secret isn't found.
    """
    value = _get_from_env(name)
    if value is not None:
        return value

    value = _get_from_keyring(name)
    if value is not None:
        return value

    if required:
        raise SecretNotFoundError(
            f"Secret '{name}' not found in environment or keychain. "
            f"Set it with: python -m config.secrets set {name}"
        )
    return None


def set_secret(name: str, value: str) -> None:
    """Store a secret in the macOS Keychain."""
    import keyring

    keyring.set_password(SERVICE_NAME, name, value)


def delete_secret(name: str) -> None:
    """Remove a secret from the macOS Keychain."""
    import keyring

    keyring.delete_password(SERVICE_NAME, name)


if __name__ == "__main__":
    import getpass
    import sys

    if len(sys.argv) < 3 or sys.argv[1] not in ("set", "get", "delete"):
        print("Usage:")
        print("  python -m config.secrets set <secret-name>")
        print("  python -m config.secrets get <secret-name>")
        print("  python -m config.secrets delete <secret-name>")
        print(f"\nKnown secret names: {', '.join(SECRET_KEYS)}")
        sys.exit(1)

    action, key = sys.argv[1], sys.argv[2]

    if action == "set":
        val = getpass.getpass(f"Enter value for '{key}': ")
        set_secret(key, val)
        print(f"Stored '{key}' in macOS Keychain.")
    elif action == "get":
        try:
            print(get_secret(key))
        except SecretNotFoundError as e:
            print(str(e))
            sys.exit(1)
    elif action == "delete":
        delete_secret(key)
        print(f"Deleted '{key}' from macOS Keychain.")
