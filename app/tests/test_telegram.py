import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

import alerts.telegram as tg
from alerts import IncomingMessage
from alerts.telegram import get_new_telegram_messages, send_telegram

SECRETS = {
    "telegram-bot-token": "test-token-123",
    "telegram-chat-id": "987654321",
}

SINCE = dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc)
ALLOWED = "987654321"


@pytest.fixture(autouse=True)
def patch_secrets(monkeypatch):
    monkeypatch.setattr("alerts.telegram.get_secret", lambda key: SECRETS[key])


@pytest.fixture(autouse=True)
def reset_offset(monkeypatch):
    monkeypatch.setattr(tg, "_last_update_id", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_update(update_id, chat_id, text, unix_ts):
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": int(chat_id)},
            "text": text,
            "date": unix_ts,
        },
    }


def mock_get_response(updates):
    resp = MagicMock()
    resp.json.return_value = {"result": updates}
    resp.raise_for_status.return_value = None
    return resp


def unix(ts: dt.datetime) -> int:
    return int(ts.timestamp())


# ---------------------------------------------------------------------------
# send_telegram
# ---------------------------------------------------------------------------

def test_send_telegram_posts_to_correct_url(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr("alerts.telegram.requests.post", fake_post)

    send_telegram("987654321", "Hello from bot")

    assert "test-token-123" in captured["url"]
    assert "sendMessage" in captured["url"]
    assert captured["json"] == {"chat_id": "987654321", "text": "Hello from bot"}


def test_send_telegram_raises_on_http_error(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("HTTP 400")
        return resp

    monkeypatch.setattr("alerts.telegram.requests.post", fake_post)

    with pytest.raises(Exception, match="HTTP 400"):
        send_telegram("987654321", "Hello")


# ---------------------------------------------------------------------------
# get_new_telegram_messages
# ---------------------------------------------------------------------------

def test_returns_messages_after_since(monkeypatch):
    after = SINCE + dt.timedelta(seconds=30)
    update = make_update(1, ALLOWED, "YES", unix(after))

    monkeypatch.setattr("alerts.telegram.requests.get",
                        lambda url, params, timeout: mock_get_response([update]))

    result = get_new_telegram_messages(SINCE, ALLOWED)

    assert len(result) == 1
    assert result[0].text == "YES"
    assert result[0].sender == ALLOWED
    assert result[0].is_from_me is False


def test_excludes_messages_at_or_before_since(monkeypatch):
    at_since = make_update(1, ALLOWED, "OLD", unix(SINCE))
    before = make_update(2, ALLOWED, "OLDER", unix(SINCE - dt.timedelta(seconds=1)))

    monkeypatch.setattr("alerts.telegram.requests.get",
                        lambda url, params, timeout: mock_get_response([at_since, before]))

    assert get_new_telegram_messages(SINCE, ALLOWED) == []


def test_filters_by_allowed_sender(monkeypatch):
    after = SINCE + dt.timedelta(seconds=10)
    from_allowed = make_update(1, ALLOWED, "YES", unix(after))
    from_other = make_update(2, "999999", "HACK", unix(after))

    monkeypatch.setattr("alerts.telegram.requests.get",
                        lambda url, params, timeout: mock_get_response([from_allowed, from_other]))

    result = get_new_telegram_messages(SINCE, ALLOWED)

    assert len(result) == 1
    assert result[0].text == "YES"


def test_returns_oldest_first(monkeypatch):
    t1 = SINCE + dt.timedelta(seconds=10)
    t2 = SINCE + dt.timedelta(seconds=20)
    updates = [
        make_update(1, ALLOWED, "first", unix(t1)),
        make_update(2, ALLOWED, "second", unix(t2)),
    ]

    monkeypatch.setattr("alerts.telegram.requests.get",
                        lambda url, params, timeout: mock_get_response(updates))

    result = get_new_telegram_messages(SINCE, ALLOWED)

    assert [m.text for m in result] == ["first", "second"]


def test_advances_offset_after_fetch(monkeypatch):
    after = SINCE + dt.timedelta(seconds=5)
    updates = [make_update(42, ALLOWED, "HI", unix(after))]

    monkeypatch.setattr("alerts.telegram.requests.get",
                        lambda url, params, timeout: mock_get_response(updates))

    get_new_telegram_messages(SINCE, ALLOWED)

    assert tg._last_update_id == 42


def test_sends_offset_on_subsequent_call(monkeypatch):
    captured_params = []

    def fake_get(url, params, timeout):
        captured_params.append(dict(params))
        return mock_get_response([])

    monkeypatch.setattr("alerts.telegram.requests.get", fake_get)
    monkeypatch.setattr(tg, "_last_update_id", 99)

    get_new_telegram_messages(SINCE, ALLOWED)

    assert captured_params[0]["offset"] == 100


def test_handles_naive_since(monkeypatch):
    naive = dt.datetime(2026, 6, 10, 12, 0, 0)
    after = dt.datetime(2026, 6, 10, 12, 0, 30, tzinfo=dt.timezone.utc)
    updates = [make_update(1, ALLOWED, "HI", unix(after))]

    monkeypatch.setattr("alerts.telegram.requests.get",
                        lambda url, params, timeout: mock_get_response(updates))

    result = get_new_telegram_messages(naive, ALLOWED)
    assert len(result) == 1


def test_skips_updates_without_message(monkeypatch):
    updates = [{"update_id": 1, "edited_message": {"text": "nope"}}]

    monkeypatch.setattr("alerts.telegram.requests.get",
                        lambda url, params, timeout: mock_get_response(updates))

    assert get_new_telegram_messages(SINCE, ALLOWED) == []


def test_empty_text_becomes_empty_string(monkeypatch):
    after = SINCE + dt.timedelta(seconds=5)
    update = make_update(1, ALLOWED, None, unix(after))
    update["message"]["text"] = None

    monkeypatch.setattr("alerts.telegram.requests.get",
                        lambda url, params, timeout: mock_get_response([update]))

    result = get_new_telegram_messages(SINCE, ALLOWED)
    assert result[0].text == ""
