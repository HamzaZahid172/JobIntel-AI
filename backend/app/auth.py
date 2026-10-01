import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, Header, HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .db import engine, get_db
from .models import AuthSession, User

SESSION_DAYS = 30
PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256$" + str(PBKDF2_ITERATIONS) + "$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(40)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=datetime.utcnow() + timedelta(days=SESSION_DAYS),
        )
    )
    db.commit()
    return token


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Login required.")
    token = authorization.split(" ", 1)[1].strip()
    session = (
        db.query(AuthSession)
        .filter(
            AuthSession.token_hash == hash_token(token),
            AuthSession.expires_at > datetime.utcnow(),
        )
        .first()
    )
    if not session:
        raise HTTPException(401, "Session expired. Please log in again.")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "User account not found.")
    return user


def logout_token(db: Session, authorization: str | None) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return
    token = authorization.split(" ", 1)[1].strip()
    db.query(AuthSession).filter(AuthSession.token_hash == hash_token(token)).delete()
    db.commit()


def ensure_auth_columns() -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table in ("cv_profiles", "applications"):
            columns = {column["name"] for column in inspector.get_columns(table)}
            if "user_id" not in columns:
                connection.execute(text("ALTER TABLE " + table + " ADD COLUMN user_id INTEGER"))
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_" + table + "_user_id ON " + table + "(user_id)"))


def claim_legacy_workspace(db: Session, user: User) -> None:
    db.execute(text("UPDATE cv_profiles SET user_id=:uid WHERE user_id IS NULL"), {"uid": user.id})
    db.execute(text("UPDATE applications SET user_id=:uid WHERE user_id IS NULL"), {"uid": user.id})
    db.commit()
