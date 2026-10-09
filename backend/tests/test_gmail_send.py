import base64
from datetime import datetime, timedelta
from email import message_from_bytes
from types import SimpleNamespace

import pytest

from app.gmail_sync import GMAIL_SEND_SCOPE, gmail_can_send, gmail_send_approved


def test_readonly_gmail_cannot_send():
    readonly = SimpleNamespace(
        scope="https://www.googleapis.com/auth/gmail.readonly"
    )
    assert not gmail_can_send(readonly)
    with pytest.raises(RuntimeError):
        gmail_send_approved(None, readonly, "recruiter@example.com", "Follow up", "Test message")


def test_explicit_gmail_send_scope_builds_proper_message(monkeypatch):
    conn = SimpleNamespace(
        scope="https://www.googleapis.com/auth/gmail.readonly " + GMAIL_SEND_SCOPE,
        google_email="applicant@example.com",access_token="secret",
        token_expires_at=datetime.utcnow()+timedelta(hours=1)
    )
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"id":"gmail-message-1"}
    def fake_post(url, headers, json, timeout):
        assert url.endswith("/users/me/messages/send")
        message = message_from_bytes(base64.urlsafe_b64decode(json["raw"]))
        assert message["To"] == "recruiter@example.com"
        assert message["From"] == "applicant@example.com"
        assert message["Subject"] == "Following up"
        assert "Could I get an update" in message.get_payload(decode=True).decode()
        return Response()
    monkeypatch.setattr("app.gmail_sync.httpx.post", fake_post)
    assert gmail_send_approved(None,conn,"recruiter@example.com","Following up","Could I get an update?") == "gmail-message-1"
