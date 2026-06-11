"""
Configuration loader for the auto-trading app.

Loads non-sensitive settings from config/settings.yaml. This module
deliberately knows nothing about secrets — see `config/secrets.py` for
API keys, account IDs, and other credentials.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "settings.yaml"


@functools.lru_cache(maxsize=1)
def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load and cache the application config from YAML.

    Cached so repeated calls (e.g. from multiple modules) don't re-read
    and re-parse the file. Use `load_config.cache_clear()` in tests if
    you need to reload with different settings.
    """
    config_path = Path(path) if path else CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError(f"Config file {config_path} did not parse to a dict")

    return config


def get(key_path: str, default: Any = None) -> Any:
    """Fetch a nested config value using dot notation.

    Example: get("risk.max_position_pct") -> 5
    """
    config = load_config()
    node: Any = config
    for part in key_path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node
