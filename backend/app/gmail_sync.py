import os
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from .models import Application, GmailConnection, GmailEvent, GmailOAuthState

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"


def gmail_config() -> dict:
    return {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv(
            "GOOGLE_GMAIL_REDIRECT_URI",
            "http://localhost:8100/api/gmail/callback",
        ).strip(),
    }


def gmail_configured() -> bool:
    cfg = gmail_config()
    return bool(cfg["client_id"] and cfg["client_secret"] and cfg["redirect_uri"])


def create_oauth_state(db: Session, user_id: int) -> GmailOAuthState:
    db.query(GmailOAuthState).filter(
        GmailOAuthState.user_id == user_id,
        GmailOAuthState.expires_at <= datetime.utcnow(),
    ).delete()
    row = GmailOAuthState(
        user_id=user_id,
        state=secrets.token_urlsafe(32),
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def build_authorization_url(state: str) -> str:
    cfg = gmail_config()
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": GMAIL_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return GOOGLE_AUTH_URL + "?" + urlencode(params)


def exchange_code(code: str) -> dict:
    cfg = gmail_config()
    response = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "redirect_uri": cfg["redirect_uri"],
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def _refresh_access_token(connection: GmailConnection) -> None:
    if not connection.refresh_token:
        raise RuntimeError("Gmail refresh token is missing. Reconnect Gmail.")
    cfg = gmail_config()
    response = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "refresh_token": connection.refresh_token,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    connection.access_token = payload["access_token"]
    connection.token_expires_at = datetime.utcnow() + timedelta(
        seconds=max(int(payload.get("expires_in", 3600)) - 60, 60)
    )


def ensure_access_token(db: Session, connection: GmailConnection) -> str:
    if (
        not connection.access_token
        or not connection.token_expires_at
        or connection.token_expires_at <= datetime.utcnow() + timedelta(seconds=60)
    ):
        _refresh_access_token(connection)
        db.commit()
    return connection.access_token


def gmail_profile(access_token: str) -> dict:
    response = httpx.get(
        f"{GMAIL_API}/users/me/profile",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def _normalise(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"\b(gmbh|ag|se|inc|ltd|llc|group|company|co)\b", " ", value)
    value = re.sub(r"[^a-z0-9+#.]+", " ", value)
    return " ".join(value.split())


def _tokens(value: str) -> set[str]:
    stop = {
        "senior", "junior", "working", "student", "engineer", "developer",
        "software", "the", "and", "for", "with", "remote", "germany",
    }
    return {x for x in _normalise(value).split() if len(x) >= 3 and x not in stop}


def classify_message(subject: str, snippet: str) -> str | None:
    """Conservative classification: generic words never trigger a rejection."""
    value = f"{subject} {snippet}".lower()
    rejection = (
        "regret to inform", "not moving forward", "not proceed with your",
        "other candidates", "other applicants", "application was unsuccessful",
        "will not be moving", "we have decided not to",
        "not selected", "unable to offer you", "won't be proceeding",
        "will not proceed", "nicht berücksichtigen", "leider absagen",
        "leider nicht", "absage ihrer bewerbung", "bewerbung leider",
    )
    offers = ("job offer", "offer letter", "pleased to offer you", "employment offer")
    interviews = (
        "invite you to an interview", "invitation to interview",
        "would like to interview you", "schedule an interview",
        "schedule a call with you", "interview invitation",
        "einladung zum vorstellungsgespräch",
    )
    screening = (
        "complete the assessment", "coding challenge invitation",
        "please complete the test", "take-home assignment",
        "invitation to assessment",
    )
    applied = (
        "application received", "thank you for applying", "thanks for applying",
        "we received your application", "application confirmation",
        "eingangsbestätigung ihrer bewerbung",
    )
    if any(phrase in value for phrase in rejection):
        return "Rejected"
    if any(phrase in value for phrase in offers):
        return "Offer"
    if any(phrase in value for phrase in interviews):
        return "Interview"
    if any(phrase in value for phrase in screening):
        return "Screening"
    if any(phrase in value for phrase in applied):
        return "Applied"
    return None


def _app_company_match(app: Application, text: str, tokens: set[str]) -> bool:
    company = _normalise(app.company)
    company_tokens = _tokens(app.company)
    return bool(
        company and company in text
        or company_tokens and len(company_tokens & tokens) >= len(company_tokens)
    )


def match_application(
    applications: list[Application],
    subject: str,
    sender: str,
    snippet: str,
) -> Application | None:
    """Require company evidence and a unique role; never guess between roles."""
    text = _normalise(f"{subject} {sender} {snippet}")
    tokens = _tokens(text)
    candidates = [app for app in applications if _app_company_match(app, text, tokens)]
    if not candidates:
        return None

    strong = []
    for app in candidates:
        role = _normalise(app.role)
        role_tokens = _tokens(app.role)
        if role and role in text or role_tokens and len(role_tokens & tokens) >= 2:
            strong.append(app)
    if len(strong) == 1:
        return strong[0]
    if len(strong) > 1:
        return None  # ambiguous: manual review is safer than a wrong rejection

    # Employer emails often omit the title, but a *single* application at this
    # employer is safe when the message clearly relates to a job application.
    application_context = any(word in text for word in (
        "application", "applied", "bewerbung", "position", "role", "vacancy",
        "candidate", "hiring", "interview",
    ))
    return candidates[0] if len(candidates) == 1 and application_context else None


def _gmail_headers(message: dict) -> dict:
    result = {}
    for header in message.get("payload", {}).get("headers", []):
        name = (header.get("name") or "").lower()
        if name in {"subject", "from", "date"}:
            result[name] = header.get("value") or ""
    return result


def _apply_outcome(app: Application, outcome: str) -> bool:
    if outcome == "Rejected":
        if app.status == "Offer":
            return False
        if app.status != "Rejected":
            app.status = "Rejected"
            return True
        return False

    rank = {
        "Saved": 0,
        "Applied": 1,
        "Screening": 2,
        "Interview": 3,
        "Final": 4,
        "Offer": 5,
        "Rejected": 6,
    }
    if app.status == "Rejected":
        return False
    if rank.get(outcome, 0) > rank.get(app.status, 0):
        app.status = outcome
        return True
    return False


def _gmail_message_query(days: int) -> str:
    return f"in:anywhere -in:spam newer_than:{max(days, 1)}d"


def sync_gmail(db: Session, user_id: int, days: int = 45, max_results: int = 300) -> dict:
    connection = (
        db.query(GmailConnection)
        .filter(GmailConnection.user_id == user_id)
        .first()
    )
    if not connection:
        raise RuntimeError("Gmail is not connected.")

    access_token = ensure_access_token(db, connection)
    headers = {"Authorization": f"Bearer {access_token}"}

    applications = (
        db.query(Application)
        .filter(Application.user_id == user_id)
        .order_by(Application.created_at.desc())
        .all()
    )
    if not applications:
        connection.last_synced_at = datetime.utcnow()
        db.commit()
        return {"scanned": 0, "matched": 0, "updated": 0, "events": 0, "outcomes": {}}

    gmail_query = _gmail_message_query(days)
    message_ids: list[str] = []
    seen_ids: set[str] = set()
    page_token = None
    max_results = min(max(int(max_results), 1), 500)
    # Follow nextPageToken; Gmail can return fewer messages than requested.
    while len(message_ids) < max_results:
        params = {
            "q": gmail_query,
            "maxResults": min(100, max_results - len(message_ids)),
            "includeSpamTrash": True,
        }
        if page_token:
            params["pageToken"] = page_token
        listing = httpx.get(
            f"{GMAIL_API}/users/me/messages",
            headers=headers,
            params=params,
            timeout=20,
        )
        if listing.status_code == 401 and connection.refresh_token:
            _refresh_access_token(connection)
            db.commit()
            headers["Authorization"] = f"Bearer {connection.access_token}"
            listing = httpx.get(
                f"{GMAIL_API}/users/me/messages",
                headers=headers,
                params=params,
                timeout=20,
            )
        listing.raise_for_status()
        listing_data = listing.json()
        for item in listing_data.get("messages", []):
            message_id = item.get("id")
            if message_id and message_id not in seen_ids:
                seen_ids.add(message_id)
                message_ids.append(message_id)
        next_page = listing_data.get("nextPageToken")
        if not next_page or next_page == page_token or not listing_data.get("messages"):
            break
        page_token = next_page

    scanned = matched = updated = events_created = 0
    outcomes: dict[str, int] = {}

    for message_id in message_ids:
        if not message_id:
            continue
        if (
            db.query(GmailEvent)
            .filter(
                GmailEvent.user_id == user_id,
                GmailEvent.gmail_message_id == message_id,
            )
            .first()
        ):
            continue

        response = httpx.get(
            f"{GMAIL_API}/users/me/messages/{message_id}",
            headers=headers,
            params=[
                ("format", "metadata"),
                ("metadataHeaders", "Subject"),
                ("metadataHeaders", "From"),
                ("metadataHeaders", "Date"),
            ],
            timeout=20,
        )
        response.raise_for_status()
        message = response.json()
        scanned += 1

        meta = _gmail_headers(message)
        subject = meta.get("subject", "")
        sender = meta.get("from", "")
        snippet = message.get("snippet", "")
        outcome = classify_message(subject, snippet)
        if not outcome:
            continue

        app = match_application(applications, subject, sender, snippet)
        if not app:
            continue

        received_at = None
        internal_date = message.get("internalDate")
        if internal_date:
            try:
                received_at = datetime.fromtimestamp(int(internal_date) / 1000)
            except (TypeError, ValueError):
                received_at = None

        if received_at and app.applied_date and received_at.date() < app.applied_date:
            continue  # an older message cannot change a newer application's status
        matched += 1
        changed = _apply_outcome(app, outcome)
        if changed:
            updated += 1

        db.add(
            GmailEvent(
                user_id=user_id,
                application_id=app.id,
                gmail_message_id=message_id,
                outcome=outcome,
                subject=subject[:500],
                sender=sender[:500],
                snippet=snippet,
                received_at=received_at,
            )
        )
        events_created += 1
        outcomes[outcome] = outcomes.get(outcome, 0) + 1

        signal = f"Gmail signal: {outcome} — {subject}".strip()
        if signal and signal not in (app.notes or ""):
            app.notes = ((app.notes or "").rstrip() + "\n" + signal).strip()

    connection.last_synced_at = datetime.utcnow()
    db.commit()

    return {
        "scanned": scanned,
        "listed": len(message_ids),
        "matched": matched,
        "updated": updated,
        "events": events_created,
        "outcomes": outcomes,
        "last_synced_at": connection.last_synced_at.isoformat(),
    }


def serialize_event(event: GmailEvent) -> dict:
    return {
        "id": event.id,
        "application_id": event.application_id,
        "outcome": event.outcome,
        "subject": event.subject,
        "sender": event.sender,
        "snippet": event.snippet,
        "received_at": event.received_at.isoformat() if event.received_at else None,
        "created_at": event.created_at.isoformat(),
    }
