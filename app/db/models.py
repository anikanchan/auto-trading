"""
SQLAlchemy models for the auto-trading app.

Backed by SQLite locally (data/trading.db). On AWS, the same models run
against SQLite stored on EFS.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from config.loader import get as get_config


class Base(DeclarativeBase):
    pass


class Trade(Base):
    """A completed or open trade executed by the bot."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)  # "buy" | "sell"
    quantity: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    strategy: Mapped[str] = mapped_column(String)  # which strategy/manual triggered this
    status: Mapped[str] = mapped_column(String, default="open")  # open | closed | cancelled
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.timezone.utc)
    )
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    """Audit trail of every signal, decision, command, and order."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.timezone.utc), index=True
    )
    category: Mapped[str] = mapped_column(String, index=True)
    # e.g. "signal", "order", "risk", "command", "error", "system"
    message: Mapped[str] = mapped_column(String)
    details: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON-encoded extra data


class DailyPnL(Base):
    """Daily portfolio snapshot for reporting and the kill-switch."""

    __tablename__ = "daily_pnl"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[dt.date] = mapped_column(DateTime, unique=True, index=True)
    starting_equity: Mapped[float] = mapped_column(Float)
    ending_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    kill_switch_triggered: Mapped[bool] = mapped_column(default=False)


def get_db_path() -> Path:
    db_rel_path = get_config("database.path", "data/trading.db")
    # Resolve relative to the app/ directory (parent of db/)
    app_root = Path(__file__).resolve().parent.parent
    db_path = (app_root / db_rel_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def get_engine():
    db_path = get_db_path()
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_db() -> None:
    """Create all tables if they don't exist."""
    engine = get_engine()
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return Session(get_engine())


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at: {get_db_path()}")
