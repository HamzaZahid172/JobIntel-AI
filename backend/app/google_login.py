"""Google OIDC sign-in, deliberately separate from Gmail data-access OAuth.

An existing password account can only be linked while authenticated. Merely
presenting a verified Google email never grants access to that existing user.
"""
import hashlib
import html
import json
import os
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    User, GoogleLoginState, GoogleLoginIdentity, GoogleLoginTicket
)


def configured() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


def redirect_uri() -> str:
    return os.getenv(
        "GOOGLE_LOGIN_REDIRECT_URI",
        "http://localhost:8100/api/auth/google/callback"
    )


def frontend_origin() -> str:
    return os.getenv("GOOGLE_LOGIN_FRONTEND_ORIGIN", "http://localhost:3100").rstrip("/")


def begin_google_login(db: Session, link_user_id: int | None = None) -> str:
    if not configured():
        raise HTTPException(503,"Google Sign-In is not configured in Settings/environment.")
    nonce=secrets.token_urlsafe(32)
    state=secrets.token_urlsafe(32)
    db.add(GoogleLoginState(
        state=state, nonce=nonce, link_user_id=link_user_id,
        expires_at=datetime.utcnow()+timedelta(minutes=8),
    ))
    db.commit()
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id":os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri":redirect_uri(),
        "response_type":"code",
        "scope":"openid email profile",
        "state":state,
        "nonce":nonce,
        "prompt":"select_account",
    })


def verify_google_id_token(token: str) -> dict:
    """Cryptographic signature + issuer + audience + expiration are verified by google-auth."""
    claims=id_token.verify_oauth2_token(
        token, Request(), os.environ["GOOGLE_CLIENT_ID"]
    )
    if claims.get("iss") not in {"accounts.google.com","https://accounts.google.com"}:
        raise HTTPException(401,"Google identity issuer is invalid.")
    if claims.get("email_verified") is not True or not claims.get("sub") or not claims.get("email"):
        raise HTTPException(401,"Google account email must be verified.")
    return claims


def complete_google_oauth(db: Session, state: str, code: str) -> dict:
    record=db.query(GoogleLoginState).filter(
        GoogleLoginState.state==state,
        GoogleLoginState.expires_at>datetime.utcnow()
    ).first()
    if record is None:
        raise HTTPException(400,"Google Sign-In request expired. Try again.")
    nonce=record.nonce
    link_user_id=record.link_user_id
    db.delete(record)
    db.commit()  # single use: even invalid codes cannot replay the state
    try:
        result=httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code":code, "client_id":os.environ["GOOGLE_CLIENT_ID"],
                "client_secret":os.environ["GOOGLE_CLIENT_SECRET"],
                "redirect_uri":redirect_uri(), "grant_type":"authorization_code",
            },timeout=20)
        result.raise_for_status()
        google_token=result.json().get("id_token")
        if not google_token:
            raise HTTPException(401,"Google did not issue an identity token.")
        claims=verify_google_id_token(google_token)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502,"Google Sign-In could not be verified.") from exc
    if claims.get("nonce") != nonce:
        raise HTTPException(401,"Google Sign-In session could not be verified.")

    subject=str(claims["sub"])
    email=str(claims["email"]).lower().strip()
    existing=db.query(GoogleLoginIdentity).filter(
        GoogleLoginIdentity.google_subject==subject
    ).first()

    if link_user_id is not None:
        user=db.get(User,link_user_id)
        if user is None or email!=user.email.lower():
            raise HTTPException(403,"Google email must match the signed-in JobIntel account.")
        if existing and existing.user_id!=user.id:
            raise HTTPException(409,"This Google identity is linked to another account.")
        other=db.query(GoogleLoginIdentity).filter(
            GoogleLoginIdentity.user_id==user.id
        ).first()
        if other and other.google_subject!=subject:
            raise HTTPException(409,"This account is already linked to another Google identity.")
        if not existing:
            db.add(GoogleLoginIdentity(
                user_id=user.id,google_subject=subject,google_email=email
            ))
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(409,"Google identity is already linked.") from exc
        return {"linked":True}

    if existing:
        user=db.get(User,existing.user_id)
        if user is None:
            raise HTTPException(403,"Linked JobIntel account is unavailable.")
    else:
        if db.query(User).filter(User.email==email).first():
            raise HTTPException(
                409,
                "This email already has a password account. Log in with your password and link Google Sign-In from Settings first.",
            )
        user=User(
            email=email,
            display_name=str(claims.get("name") or email.split("@")[0])[:120],
            password_hash="!google-oidc-account-no-local-password"
        )
        db.add(user)
        db.flush()
        db.add(GoogleLoginIdentity(
            user_id=user.id,google_subject=subject,google_email=email
        ))
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(409,"A linked account was created concurrently. Try again.") from exc

    secret=secrets.token_urlsafe(48)
    db.add(GoogleLoginTicket(
        user_id=user.id,token_hash=hashlib.sha256(secret.encode()).hexdigest(),
        expires_at=datetime.utcnow()+timedelta(minutes=2)
    ))
    db.commit()
    return {"ticket":secret}


def exchange_ticket(db: Session, ticket: str) -> User:
    hash_value=hashlib.sha256(ticket.encode()).hexdigest()
    record=db.query(GoogleLoginTicket).filter(
        GoogleLoginTicket.token_hash==hash_value,
        GoogleLoginTicket.expires_at>datetime.utcnow()
    ).first()
    if record is None:
        raise HTTPException(401,"Google login ticket expired or already used.")
    uid=record.user_id
    deleted=db.query(GoogleLoginTicket).filter(
        GoogleLoginTicket.id==record.id,
        GoogleLoginTicket.token_hash==hash_value
    ).delete(synchronize_session=False)
    db.commit()
    if deleted!=1:
        raise HTTPException(401,"Google login ticket already consumed.")
    user=db.get(User,uid)
    if not user:
        raise HTTPException(404,"Account no longer exists.")
    return user


def popup_result_page(data: dict) -> str:
    # Data only contains a random single-use ticket, linked boolean or a
    # backend-authored error message. JSON is escaped for the HTML script context.
    payload=json.dumps({"type":"jobintel-google-auth",**data}).replace("<","\\u003c")
    origin=json.dumps(frontend_origin()).replace("<","\\u003c")
    return (
        "<!doctype html><meta charset='utf-8'><title>JobIntel Google Sign-In</title>"
        "<p>Returning to JobIntel… You may close this tab.</p>"
        "<script>if(window.opener){window.opener.postMessage("
        +payload+","+origin+");window.close();}</script>"
    )
