"""
Command parser for the two-way messaging command interface.

Parses inbound text messages (from iMessage/WhatsApp) into structured
`Command` objects. Pure logic, no I/O — keeps it easy to unit test
independently of the messaging transport.

Commands are case-insensitive. Unrecognized text becomes a Command with
name="UNKNOWN".
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

KNOWN_COMMANDS = {
    "STATUS",
    "PAUSE",
    "RESUME",
    "FLATTEN",
    "REPORT",
    "HISTORY",
    "RISK",
    "STOP",
    "BUY",
    "SELL",
    "HELP",
    "YES",
    "NO",
}


class CommandParseError(ValueError):
    """Raised when a recognized command has invalid arguments."""


@dataclass
class Command:
    name: str
    raw: str
    args: dict = field(default_factory=dict)


def parse_command(text: str) -> Command:
    """Parse a raw inbound message into a Command.

    Raises CommandParseError if the command is recognized but malformed
    (e.g. `BUY AAPL` with no quantity). Unrecognized commands return
    Command(name="UNKNOWN").
    """
    raw = text.strip()
    if not raw:
        return Command(name="UNKNOWN", raw=raw)

    tokens = raw.split()
    name = tokens[0].upper()

    if name not in KNOWN_COMMANDS:
        return Command(name="UNKNOWN", raw=raw)

    if name in ("STATUS", "PAUSE", "RESUME", "FLATTEN", "REPORT", "HELP", "YES", "NO"):
        return Command(name=name, raw=raw)

    if name == "STOP":
        if len(tokens) < 2:
            raise CommandParseError("STOP requires a ticker symbol, e.g. STOP AAPL")
        return Command(name=name, raw=raw, args={"symbol": tokens[1].upper()})

    if name == "HISTORY":
        return Command(name=name, raw=raw, args=_parse_history_args(tokens[1:]))

    if name == "RISK":
        if len(tokens) < 3:
            raise CommandParseError("RISK requires a parameter and value, e.g. RISK MAXPOS 3%")
        return Command(name=name, raw=raw, args={"param": tokens[1].upper(), "value": tokens[2]})

    if name in ("BUY", "SELL"):
        return Command(name=name, raw=raw, args=_parse_order_args(name, tokens[1:]))

    return Command(name="UNKNOWN", raw=raw)


def _parse_history_args(tokens: list[str]) -> dict:
    if not tokens:
        return {"days": 7}

    arg = tokens[0].upper()

    if ".." in arg:
        start_str, end_str = arg.split("..", 1)
        try:
            start = dt.datetime.strptime(start_str, "%Y-%m-%d").date()
            end = dt.datetime.strptime(end_str, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandParseError(
                "HISTORY date range must be YYYY-MM-DD..YYYY-MM-DD"
            ) from exc
        if end < start:
            raise CommandParseError("HISTORY end date must not be before start date")
        return {"start": start, "end": end}

    if arg.endswith("D") and arg[:-1].isdigit():
        return {"days": int(arg[:-1])}

    raise CommandParseError("HISTORY argument must be <N>D or <start>..<end>")


def _parse_order_args(name: str, tokens: list[str]) -> dict:
    if len(tokens) < 2:
        raise CommandParseError(f"{name} requires a ticker and quantity, e.g. {name} AAPL 10")

    symbol = tokens[0].upper()
    try:
        quantity = float(tokens[1])
    except ValueError as exc:
        raise CommandParseError(f"{name} quantity must be a number") from exc

    if quantity <= 0:
        raise CommandParseError(f"{name} quantity must be positive")

    args = {"symbol": symbol, "quantity": quantity, "limit_price": None}

    if len(tokens) >= 4:
        modifier = tokens[2].upper()
        expected = "MAX" if name == "BUY" else "MIN"
        if modifier != expected:
            raise CommandParseError(f"{name} price modifier must be {expected}, e.g. {name} AAPL 10 {expected} 100.00")
        try:
            args["limit_price"] = float(tokens[3])
        except ValueError as exc:
            raise CommandParseError(f"{name} {expected} price must be a number") from exc
    elif len(tokens) == 3:
        raise CommandParseError(
            f"{name} with a price needs a modifier, e.g. {name} {symbol} {tokens[1]} "
            f"{'MAX' if name == 'BUY' else 'MIN'} <price>"
        )

    return args
