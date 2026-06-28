import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from alerts import IncomingMessage
from alerts.whatsapp import _whatsapp_addr, get_new_whatsapp_messages, send_whatsapp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_twilio_message(body, date_sent, sid="SM123"):
    msg = MagicMock()
    msg.body = body
    msg.date_sent = date_sent
    msg.sid = sid
    return msg


SECRETS = {
    "twilio-account-sid": "ACtest",
    "twilio-auth-token": "authtoken",
    "twilio-whatsapp-number": "+14155238886",
}


@pytest.fixture(autouse=True)
def patch_secrets(monkeypatch):
    monkeypatch.setattr("alerts.whatsapp.get_secret", lambda key: SECRETS[key])


# ---------------------------------------------------------------------------
# _whatsapp_addr
# ---------------------------------------------------------------------------

def test_whatsapp_addr_adds_prefix():
    assert _whatsapp_addr("+15555550123") == "whatsapp:+15555550123"


def test_whatsapp_addr_no_double_prefix():
    assert _whatsapp_addr("whatsapp:+15555550123") == "whatsapp:+15555550123"


# ---------------------------------------------------------------------------
# send_whatsapp
# ---------------------------------------------------------------------------

def test_send_whatsapp_calls_twilio(monkeypatch):
    mock_client = MagicMock()
    monkeypatch.setattr("alerts.whatsapp._client", lambda: mock_client)

    send_whatsapp("+15555550123", "Hello from bot")

    mock_client.messages.create.assert_called_once_with(
        from_="whatsapp:+14155238886",
        to="whatsapp:+15555550123",
        body="Hello from bot",
    )


def test_send_whatsapp_normalises_to_prefix(monkeypatch):
    mock_client = MagicMock()
    monkeypatch.setattr("alerts.whatsapp._client", lambda: mock_client)

    send_whatsapp("whatsapp:+15555550123", "Hi")

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["to"] == "whatsapp:+15555550123"


# ---------------------------------------------------------------------------
# get_new_whatsapp_messages
# ---------------------------------------------------------------------------

SINCE = dt.datetime(2026, 6, 10, 12, 0, 0, tzinfo=dt.timezone.utc)
ALLOWED = "+15555550123"


def test_get_new_messages_returns_messages_after_since(monkeypatch):
    after = SINCE + dt.timedelta(seconds=30)
    twilio_msg = make_twilio_message("YES", after)

    mock_client = MagicMock()
    mock_client.messages.list.return_value = [twilio_msg]
    monkeypatch.setattr("alerts.whatsapp._client", lambda: mock_client)

    result = get_new_whatsapp_messages(SINCE, ALLOWED)

    assert len(result) == 1
    assert result[0].text == "YES"
    assert result[0].sender == ALLOWED
    assert result[0].timestamp == after
    assert result[0].is_from_me is False


def test_get_new_messages_excludes_at_or_before_since(monkeypatch):
    at_since = make_twilio_message("OLD", SINCE)
    before = make_twilio_message("OLDER", SINCE - dt.timedelta(seconds=1))

    mock_client = MagicMock()
    mock_client.messages.list.return_value = [at_since, before]
    monkeypatch.setattr("alerts.whatsapp._client", lambda: mock_client)

    result = get_new_whatsapp_messages(SINCE, ALLOWED)

    assert result == []


def test_get_new_messages_returns_oldest_first(monkeypatch):
    t1 = SINCE + dt.timedelta(seconds=10)
    t2 = SINCE + dt.timedelta(seconds=20)
    # Twilio returns newest first
    mock_client = MagicMock()
    mock_client.messages.list.return_value = [
        make_twilio_message("second", t2),
        make_twilio_message("first", t1),
    ]
    monkeypatch.setattr("alerts.whatsapp._client", lambda: mock_client)

    result = get_new_whatsapp_messages(SINCE, ALLOWED)

    assert [m.text for m in result] == ["first", "second"]


def test_get_new_messages_queries_correct_numbers(monkeypatch):
    mock_client = MagicMock()
    mock_client.messages.list.return_value = []
    monkeypatch.setattr("alerts.whatsapp._client", lambda: mock_client)

    get_new_whatsapp_messages(SINCE, ALLOWED)

    mock_client.messages.list.assert_called_once_with(
        to="whatsapp:+14155238886",
        from_="whatsapp:+15555550123",
        date_sent_after=SINCE,
    )


def test_get_new_messages_handles_naive_since(monkeypatch):
    naive_since = dt.datetime(2026, 6, 10, 12, 0, 0)  # no tzinfo
    after = naive_since.replace(tzinfo=dt.timezone.utc) + dt.timedelta(seconds=5)
    twilio_msg = make_twilio_message("HI", after)

    mock_client = MagicMock()
    mock_client.messages.list.return_value = [twilio_msg]
    monkeypatch.setattr("alerts.whatsapp._client", lambda: mock_client)

    result = get_new_whatsapp_messages(naive_since, ALLOWED)

    assert len(result) == 1


def test_get_new_messages_skips_none_body(monkeypatch):
    after = SINCE + dt.timedelta(seconds=5)
    twilio_msg = make_twilio_message(None, after)

    mock_client = MagicMock()
    mock_client.messages.list.return_value = [twilio_msg]
    monkeypatch.setattr("alerts.whatsapp._client", lambda: mock_client)

    result = get_new_whatsapp_messages(SINCE, ALLOWED)

    assert result[0].text == ""


def test_get_new_messages_skips_none_date(monkeypatch):
    twilio_msg = make_twilio_message("HI", None)

    mock_client = MagicMock()
    mock_client.messages.list.return_value = [twilio_msg]
    monkeypatch.setattr("alerts.whatsapp._client", lambda: mock_client)

    result = get_new_whatsapp_messages(SINCE, ALLOWED)

    assert result == []
