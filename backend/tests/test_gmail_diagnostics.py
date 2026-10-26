from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.main as main
from app.db import Base
from app.models import GmailConnection


def test_diagnostics_distinguishes_network_error_from_connected(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(GmailConnection(
            user_id=17, google_email="user@example.com", access_token="token",
            refresh_token="refresh",
            token_expires_at=datetime.utcnow()+timedelta(hours=1),
            scope="https://www.googleapis.com/auth/gmail.readonly",
        ))
        db.commit()
        monkeypatch.setattr(main, "gmail_configured", lambda: True)
        monkeypatch.setattr(main, "ensure_access_token", lambda db, connection: "token")
        monkeypatch.setattr(main, "gmail_profile", lambda token: {"emailAddress": "user@example.com"})
        user=SimpleNamespace(id=17)
        ok=main.gmail_diagnostics(user=user,db=db)
        assert ok["code"]=="CONNECTED"
        assert ok["mailbox_reachable"] is True

        def no_connection(token):
            raise httpx.ConnectError("includes-sensitive-host-information")
        monkeypatch.setattr(main, "gmail_profile", no_connection)
        failed=main.gmail_diagnostics(user=user,db=db)
        assert failed["code"]=="NETWORK_UNAVAILABLE"
        assert failed["mailbox_reachable"] is False
        assert "sensitive" not in str(failed)
    engine.dispose()


def test_diagnostics_not_connected_is_actionable(monkeypatch):
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        monkeypatch.setattr(main, "gmail_configured", lambda: True)
        result=main.gmail_diagnostics(user=SimpleNamespace(id=200),db=db)
        assert result["code"]=="NOT_CONNECTED"
        assert "Settings" in result["next_step"]
    engine.dispose()
