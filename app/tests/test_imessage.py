import datetime as dt
import sqlite3

import pytest

from alerts.imessage import (
    apple_time_to_datetime,
    datetime_to_apple_time,
    get_new_messages,
    send_imessage,
)


def test_apple_time_roundtrip():
    now = dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc)
    apple_time = datetime_to_apple_time(now)
    back = apple_time_to_datetime(apple_time)
    assert abs((back - now).total_seconds()) < 1e-3


def test_apple_epoch_is_zero():
    epoch = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)
    assert datetime_to_apple_time(epoch) == 0


def test_send_imessage_invokes_osascript():
    calls = []

    def fake_runner(args, **kwargs):
        calls.append((args, kwargs))

        class Result:
            returncode = 0

        return Result()

    send_imessage("+15555550123", "Hello", runner=fake_runner)

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == "osascript"
    assert "+15555550123" in args[2]
    assert "Hello" in args[2]
    assert kwargs["check"] is True


def test_send_imessage_escapes_quotes():
    calls = []

    def fake_runner(args, **kwargs):
        calls.append(args)

        class Result:
            returncode = 0

        return Result()

    send_imessage("+15555550123", 'Say "hi"', runner=fake_runner)
    script = calls[0][2]
    assert '\\"hi\\"' in script


def make_chat_db(tmp_path, messages):
    """Create a minimal chat.db with the given (text, handle, apple_time, is_from_me) rows."""
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT)")
    conn.execute(
        "CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, handle_id INTEGER, date INTEGER, is_from_me INTEGER)"
    )

    handles = {}
    for text, handle_id, apple_time, is_from_me in messages:
        if handle_id not in handles:
            handles[handle_id] = len(handles) + 1
            conn.execute("INSERT INTO handle (ROWID, id) VALUES (?, ?)", (handles[handle_id], handle_id))
        conn.execute(
            "INSERT INTO message (text, handle_id, date, is_from_me) VALUES (?, ?, ?, ?)",
            (text, handles[handle_id], apple_time, is_from_me),
        )
    conn.commit()
    conn.close()
    return db_path


def test_get_new_messages_filters_by_sender_and_time(tmp_path):
    base = dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc)
    base_apple = datetime_to_apple_time(base)

    db_path = make_chat_db(
        tmp_path,
        [
            ("YES", "+15555550123", base_apple + 10_000_000_000, 0),  # allowed sender, after `since`
            ("from someone else", "+15555559999", base_apple + 10_000_000_000, 0),
            ("old message", "+15555550123", base_apple - 10_000_000_000, 0),  # before `since`
            ("outgoing", "+15555550123", base_apple + 10_000_000_000, 1),  # is_from_me
        ],
    )

    messages = get_new_messages(since=base, allowed_sender="+15555550123", chat_db_path=db_path)

    assert len(messages) == 1
    assert messages[0].text == "YES"
    assert messages[0].sender == "+15555550123"
    assert messages[0].is_from_me is False


def test_get_new_messages_returns_empty_when_none(tmp_path):
    base = dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc)
    db_path = make_chat_db(tmp_path, [])
    messages = get_new_messages(since=base, allowed_sender="+15555550123", chat_db_path=db_path)
    assert messages == []
