from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.google_login import begin_google_login, complete_google_oauth, exchange_ticket, popup_result_page
from app.models import User, GoogleLoginIdentity, GoogleLoginState


class FakeExchange:
    def raise_for_status(self): pass
    def json(self): return {"id_token":"signed-google-oidc-id-token"}


def setup_oauth(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID","test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET","private-test-secret")
    monkeypatch.setenv("GOOGLE_LOGIN_FRONTEND_ORIGIN","http://localhost:3100")
    monkeypatch.setattr("app.google_login.httpx.post", lambda *a, **k: FakeExchange())


def test_google_signup_and_one_time_exchange(monkeypatch):
    setup_oauth(monkeypatch)
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        url=begin_google_login(db)
        params=parse_qs(urlparse(url).query)
        assert params["scope"]==["openid email profile"]
        assert params["response_type"]==["code"]
        assert params["redirect_uri"]==["http://localhost:8100/api/auth/google/callback"]
        state=params["state"][0]
        nonce=params["nonce"][0]
        monkeypatch.setattr("app.google_login.verify_google_id_token",lambda _: {
            "sub":"stable-google-subject","email":"candidate@example.com",
            "email_verified":True,"nonce":nonce,"name":"Candidate Example"
        })
        completed=complete_google_oauth(db,state,"one-time-auth-code")
        assert completed["ticket"]
        assert db.query(User).count()==1
        user=exchange_ticket(db,completed["ticket"])
        assert user.email=="candidate@example.com"
        with pytest.raises(HTTPException) as exc:
            exchange_ticket(db,completed["ticket"])
        assert exc.value.status_code==401
        with pytest.raises(HTTPException):
            complete_google_oauth(db,state,"one-time-auth-code")
    engine.dispose()


def test_password_account_cannot_be_taken_over_by_google_email(monkeypatch):
    setup_oauth(monkeypatch)
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account=User(email="candidate@example.com",display_name="Existing",
                     password_hash="pbkdf2_sha256$fake")
        db.add(account);db.commit();db.refresh(account)
        url=begin_google_login(db)
        params=parse_qs(urlparse(url).query)
        nonce=params["nonce"][0]
        monkeypatch.setattr("app.google_login.verify_google_id_token",lambda _: {
            "sub":"google-verified-id","email":account.email,"email_verified":True,
            "nonce":nonce
        })
        with pytest.raises(HTTPException) as exc:
            complete_google_oauth(db,params["state"][0],"code")
        assert exc.value.status_code==409
        assert not db.query(GoogleLoginIdentity).count()
        # Only an authenticated account owner can request a linking state.
        url=begin_google_login(db,link_user_id=account.id)
        params=parse_qs(urlparse(url).query)
        monkeypatch.setattr("app.google_login.verify_google_id_token",lambda _: {
            "sub":"google-verified-id","email":account.email,"email_verified":True,
            "nonce":params["nonce"][0]
        })
        result=complete_google_oauth(db,params["state"][0],"link-code")
        assert result=={"linked":True}
        assert db.query(GoogleLoginIdentity).one().user_id==account.id
        login_url=begin_google_login(db)
        params=parse_qs(urlparse(login_url).query)
        monkeypatch.setattr("app.google_login.verify_google_id_token",lambda _: {
            "sub":"google-verified-id","email":account.email,"email_verified":True,
            "nonce":params["nonce"][0]
        })
        ticket=complete_google_oauth(db,params["state"][0],"login-code")["ticket"]
        assert exchange_ticket(db,ticket).id==account.id
        assert db.query(User).count()==1
    engine.dispose()


def test_nonce_mismatch_blocks_google_signin(monkeypatch):
    setup_oauth(monkeypatch)
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        url=begin_google_login(db)
        state=parse_qs(urlparse(url).query)["state"][0]
        monkeypatch.setattr("app.google_login.verify_google_id_token",lambda _: {
            "sub":"bad","email":"bad@example.com","email_verified":True,
            "nonce":"incorrect-nonce"
        })
        with pytest.raises(HTTPException) as exc:
            complete_google_oauth(db,state,"code")
        assert exc.value.status_code==401
        assert db.query(User).count()==0
    engine.dispose()


def test_callback_posts_to_configured_origin_and_escapes_html(monkeypatch):
    monkeypatch.setenv("GOOGLE_LOGIN_FRONTEND_ORIGIN","http://localhost:3100")
    page=popup_result_page({"error":"Invalid <script>alert('evil')</script>"})
    assert "http://localhost:3100" in page
    assert "<script>alert('evil')</script>" not in page
    assert "postMessage" in page
