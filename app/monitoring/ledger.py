"""
Transaction Ledger — append-only audit trail.

Per the specs, EVERY action the bot takes (signals, orders, fills,
cancellations, rejections, risk events, commands, config changes) must be
recorded. This module provides a single `log_event()` entry point backed
by the `audit_log` table, plus helpers to query recent history (used by the
HISTORY command and EOD reports).

All entries are immutable once written — there is no update/delete API.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from db.models import AuditLog, get_session

# Standard categories used across the app. Other values are allowed but
# these are the ones the reporting/HISTORY commands know how to group.
CATEGORY_SIGNAL = "signal"
CATEGORY_ORDER = "order"
CATEGORY_FILL = "fill"
CATEGORY_RISK = "risk"
CATEGORY_COMMAND = "command"
CATEGORY_CONFIG = "config"
CATEGORY_SYSTEM = "system"
CATEGORY_ERROR = "error"


def log_event(category: str, message: str, details: dict[str, Any] | None = None) -> AuditLog:
    """Append a single immutable entry to the transaction ledger.

    Args:
        category: one of the CATEGORY_* constants (or any short label).
        message: human-readable summary, e.g. "BUY 10 AAPL @ $150.00".
        details: optional JSON-serializable dict with extra context
            (symbol, quantity, price, strategy, reason, order id, etc.).

    Returns:
        The persisted AuditLog row (with `id` and `timestamp` populated).
    """
    entry = AuditLog(
        category=category,
        message=message,
        details=json.dumps(details, default=str) if details is not None else None,
    )
    with get_session() as session:
        session.add(entry)
        session.commit()
        session.refresh(entry)
        # Detach so it can be used after the session closes
        session.expunge(entry)
    return entry


def get_events(
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
    category: str | None = None,
    limit: int | None = None,
) -> list[AuditLog]:
    """Query the ledger, oldest-first, optionally filtered by date range/category."""
    with get_session() as session:
        query = session.query(AuditLog)
        if start is not None:
            query = query.filter(AuditLog.timestamp >= start)
        if end is not None:
            query = query.filter(AuditLog.timestamp <= end)
        if category is not None:
            query = query.filter(AuditLog.category == category)
        query = query.order_by(AuditLog.timestamp.asc())
        if limit is not None:
            query = query.limit(limit)
        results = query.all()
        for row in results:
            session.expunge(row)
        return results


def get_recent_events(days: int = 7, category: str | None = None) -> list[AuditLog]:
    """Convenience wrapper for the default HISTORY window (last N days)."""
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    return get_events(start=start, category=category)


def format_event(entry: AuditLog) -> str:
    """Render a single ledger entry as a one-line human-readable string."""
    ts = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {entry.category.upper():8s} {entry.message}"
    if entry.details:
        try:
            details = json.loads(entry.details)
            extras = ", ".join(f"{k}={v}" for k, v in details.items())
            if extras:
                line += f" ({extras})"
        except (ValueError, TypeError):
            pass
    return line


if __name__ == "__main__":
    from db.models import init_db

    init_db()
    log_event(CATEGORY_SYSTEM, "Ledger smoke test", {"ok": True})
    for event in get_recent_events(days=1):
        print(format_event(event))
