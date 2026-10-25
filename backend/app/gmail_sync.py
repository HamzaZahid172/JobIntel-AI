import base64
import os
import re
import secrets
import threading
from html.parser import HTMLParser
from email.message import EmailMessage
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from .models import Application, GmailConnection, GmailEvent, GmailOAuthState

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
_SYNC_LOCK = threading.RLock()


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


def create_oauth_state(db: Session, user_id: int, *, allow_send: bool = False) -> GmailOAuthState:
    db.query(GmailOAuthState).filter(
        GmailOAuthState.user_id == user_id,
        GmailOAuthState.expires_at <= datetime.utcnow(),
    ).delete()
    row = GmailOAuthState(
        user_id=user_id,
        state=("send_" if allow_send else "read_") + secrets.token_urlsafe(32),
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def build_authorization_url(state: str, *, allow_send: bool = False) -> str:
    cfg = gmail_config()
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": GMAIL_SCOPE + (" " + GMAIL_SEND_SCOPE if allow_send else ""),
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


def validate_gmail_send_upgrade(
    existing_email: str,
    authenticated_email: str,
    scope: str,
) -> None:
    """Never silently replace the linked mailbox during Send re-authorization."""
    if not existing_email or not authenticated_email or existing_email.casefold() != authenticated_email.casefold():
        raise ValueError("Choose the same Gmail account already connected to JobIntel.")
    granted = set((scope or "").split())
    if GMAIL_SEND_SCOPE not in granted:
        raise ValueError("Google did not grant gmail.send. Approve the requested Send permission.")


def gmail_can_send(connection: GmailConnection | None) -> bool:
    return bool(connection and GMAIL_SEND_SCOPE in (connection.scope or "").split())


def gmail_send_approved(
    db: Session,
    connection: GmailConnection,
    recipient: str,
    subject: str,
    body: str,
) -> str:
    """Only called after an authenticated user's explicit Send action."""
    if not gmail_can_send(connection):
        raise RuntimeError("Gmail sending is not authorized. Enable sending in Settings.")
    if not recipient or not subject.strip() or not body.strip():
        raise ValueError("Recipient, subject and message are required.")
    message = EmailMessage()
    message["From"] = connection.google_email
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    token = ensure_access_token(db, connection)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    response = httpx.post(
        f"{GMAIL_API}/users/me/messages/send",
        headers={"Authorization": f"Bearer {token}"},
        json={"raw": raw},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("id"):
        raise RuntimeError("Gmail did not return a message ID; verify your Sent folder.")
    return data["id"]


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


# Only an explicit rejection decision can automatically reject an application.
# "other candidates", "leider nicht", "regret to inform" and the like alone
# are not evidence of an actual rejection.
_REJECTION_PATTERNS = (
    r"\b(?:we|our team)\s+(?:have\s+)?(?:decided|chosen)\s+not\s+to\s+(?:move\s+forward|proceed|progress)\b",
    r"\b(?:we|our team)\s+(?:will\s+not|won't|cannot|can't)\s+(?:be\s+)?(?:moving\s+forward|proceed(?:ing)?|progress(?:ing)?)\b",
    r"\b(?:we|our team)\s+(?:have\s+)?(?:decided|chosen)\s+to\s+(?:move\s+forward|proceed)\s+with\s+other\s+(?:candidates|applicants)\b",
    r"\bwe(?:\s+have|\x27ve)\s+made\s+the\s+decision\s+to\s+(?:move\s+forward|proceed)\s+with\s+(?:other\s+)?candidates\b",
    r"\byour\s+application\s+(?:was|has\s+been|is)\s+(?:not\s+successful|unsuccessful|not\s+selected|rejected|declined)\b",
    r"\byou\s+(?:were\s+not|have\s+not\s+been|are\s+not)\s+selected\s+for\s+(?:this|the|our)\s+(?:role|position|job)\b",
    r"\b(?:we|our team)\s+(?:are\s+)?(?:unable|not\s+able)\s+to\s+offer\s+you\s+(?:this|the|a)\s+(?:role|position|job)\b",
    r"\b(?:we|our team)\s+(?:regretfully|unfortunately)\s+(?:must\s+)?(?:decline|reject)\s+your\s+application\b",
    r"\babsage\s+(?:ihrer|deiner)\s+bewerbung\b",
    r"\bwir\s+können\s+(?:sie|dich)\s+leider\s+nicht\s+berücksichtigen\b",
    r"\bwir\s+haben\s+uns\s+(?:leider\s+)?für\s+andere\s+bewerber(?:innen)?\s+entschieden\b",
    r"\b(?:leider\s+müssen\s+wir\s+(?:ihnen|dir)\s+absagen|wir\s+müssen\s+(?:ihnen|dir)\s+leider\s+absagen)\b",
)
_REJECTION_REGEX = tuple(re.compile(pattern, re.I) for pattern in _REJECTION_PATTERNS)


def rejection_evidence(subject: str, body: str) -> str | None:
    """Return an actual reject decision excerpt, not a general hiring phrase."""
    original = f"{subject or ''} {body or ''}"
    normalized = original.replace("’", "'").replace("‘", "'")
    for pattern in _REJECTION_REGEX:
        match = pattern.search(normalized)
        if not match:
            continue
        clause = normalized[max(0, match.start() - 90):match.start()]
        boundary = max(clause.rfind("."), clause.rfind("!"), clause.rfind("?"), clause.rfind("\n"))
        clause = clause[boundary + 1:].strip().lower()
        # A hypothetical description is not a decision about the applicant.
        if re.search(r"\b(?:if|when|whether|unless|should)\b", clause):
            continue
        return original[max(0, match.start() - 65):min(len(original), match.end() + 120)].strip()
    return None


def classify_message(subject: str, snippet: str) -> str | None:
    """Conservative classification requiring an explicit rejection decision."""
    value = f"{subject} {snippet}".lower().replace("’", "'").replace("‘", "'")
    if rejection_evidence(subject, snippet):
        return "Rejected"
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
        "application has been successfully submitted",
        "your application was submitted successfully",
    )
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
    # Employer names can appear as shifttechnology in a tracker but as
    # Shift Technology / shift-technology.com in email. Require a sufficiently
    # long exact compact name, then still require unique role/application evidence.
    compact = re.sub(r"[^a-z0-9]", "", text)
    def company_matches(app):
        if _app_company_match(app, text, tokens):
            return True
        name = re.sub(r"[^a-z0-9]", "", (app.company or "").lower())
        return len(name) >= 8 and name in compact

    candidates = [app for app in applications if company_matches(app)]
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


class _EmailHTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.segments: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style", "head"}:
            self.hidden_depth += 1
        if tag in {"p", "br", "div", "li", "tr"}:
            self.segments.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "head"}:
            self.hidden_depth = max(self.hidden_depth - 1, 0)

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.segments.append(data)


def _decode_body_data(data: str) -> str:
    if not data:
        return ""
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        return raw.decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _message_body_text(message: dict, max_chars: int = 80000) -> str:
    """Use full Gmail payload to detect outcomes beyond snippet length.

    Prefer text/plain to avoid duplicate quoted HTML content; decode nested MIME
    parts, ignore attachments and cap text before feeding the classifier.
    """
    plain: list[str] = []
    html: list[str] = []

    def walk(part: dict, depth: int = 0) -> None:
        if depth > 12:
            return
        if part.get("filename"):
            return
        mime = (part.get("mimeType") or "").lower()
        data = (part.get("body") or {}).get("data", "")
        if mime == "text/plain" and data:
            plain.append(_decode_body_data(data))
        elif mime == "text/html" and data:
            html.append(_decode_body_data(data))
        for nested in part.get("parts") or []:
            walk(nested, depth + 1)

    walk(message.get("payload") or {})
    if plain:
        return " ".join(plain)[:max_chars]
    if html:
        parser = _EmailHTMLText()
        parser.feed(" ".join(html)[:max_chars])
        return " ".join(parser.segments)[:max_chars]
    return ""


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
    # Prevent user-triggered and scheduled syncs racing on a shared connection.
    with _SYNC_LOCK:
        return _sync_gmail_impl(db, user_id, days=days, max_results=max_results)


def sync_active_applications_gmail(db: Session, user_id: int) -> dict:
    """Refresh active applications using targeted employer Gmail searches only.

    Intended for page refresh. Avoid a large, unrelated inbox scan and reuse
    the same deduplication and safe application matching as scheduled syncs.
    """
    with _SYNC_LOCK:
        return _sync_gmail_impl(
            db, user_id, days=45, max_results=100, targeted_only=True
        )


def sync_application_gmail(db: Session, user_id: int, application_id: int) -> dict:
    """Targeted user-authorized scan for one tracked application, no full-inbox fetch."""
    with _SYNC_LOCK:
        return _sync_gmail_impl(
            db, user_id, days=45, max_results=20, only_app_id=application_id
        )


def _sync_gmail_impl(
    db: Session, user_id: int, days: int = 45, max_results: int = 300,
    only_app_id: int | None = None, targeted_only: bool = False,
) -> dict:
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
    if only_app_id is not None and not any(a.id == only_app_id for a in applications):
        raise ValueError("Tracked application not found.")
    target_applications = [
        a for a in applications if only_app_id is None or a.id == only_app_id
    ]
    if not applications:
        connection.last_synced_at = datetime.utcnow()
        db.commit()
        return {"scanned": 0, "matched": 0, "updated": 0, "events": 0, "outcomes": {}}

    message_ids: list[str] = []
    seen_ids: set[str] = set()
    max_results = min(max(int(max_results), 1), 500)
    # Always recheck previously stored rejections against the original full
    # message. Older classifier versions could incorrectly label confirmations.
    previous_rejections = db.query(GmailEvent).filter(
        GmailEvent.user_id == user_id,
        GmailEvent.outcome == "Rejected",
    ).order_by(GmailEvent.received_at.desc().nullslast()).limit(100).all()
    for signal in previous_rejections:
        if only_app_id is not None and signal.application_id != only_app_id:
            continue
        if signal.gmail_message_id not in seen_ids:
            seen_ids.add(signal.gmail_message_id)
            message_ids.append(signal.gmail_message_id)

    # High-priority employer search: recent application outcomes must not be
    # buried behind a 300-message general inbox limit.
    targeted_listed = 0
    recent_cutoff = datetime.utcnow().date() - timedelta(days=60)
    company_queries: set[str] = set()
    for app in target_applications:
        if only_app_id is None and (app.status in {"Rejected", "Offer"} or (app.applied_date and app.applied_date < recent_cutoff)):
            continue
        company = re.sub(r"[^a-zA-Z0-9 äöüÄÖÜß&.-]", "", app.company or "").strip()
        if len(company) < 3 or company.casefold() in company_queries:
            continue
        company_queries.add(company.casefold())
        if len(company_queries) > 12:
            break
        query = f'in:anywhere -in:spam newer_than:{max(days, 1)}d "{company}"'
        def search_messages(search_query: str) -> list[dict]:
            response = httpx.get(
                f"{GMAIL_API}/users/me/messages",
                headers=headers,
                params={"q": search_query, "maxResults": 30, "includeSpamTrash": True},
                timeout=12,
            )
            # Refresh expired Google tokens for targeted searches too, not only
            # the general inbox scan. Do not retry repeatedly on 403/429.
            if response.status_code == 401 and connection.refresh_token:
                _refresh_access_token(connection)
                db.commit()
                headers["Authorization"] = f"Bearer {connection.access_token}"
                response = httpx.get(
                    f"{GMAIL_API}/users/me/messages",
                    headers=headers,
                    params={"q": search_query, "maxResults": 30, "includeSpamTrash": True},
                    timeout=12,
                )
            response.raise_for_status()
            return response.json().get("messages", [])

        listed = search_messages(query)
        # A company saved as "shifttechnology" may be written as "Shift
        # Technology" in the message. Fall back to a distinctive role phrase
        # if the exact company query returns no results.
        if not listed and app.role:
            # Use the distinctive core of the role, excluding bracketed
            # duration. Gmail commonly ignores some punctuation in phrases.
            role_title = re.sub(r"\\([^)]*\\)", " ", app.role)
            role_words = re.findall(r"[A-Za-z]{3,}", role_title)
            role_words = [w for w in role_words if w.lower() not in
                          {"data", "software", "engineer", "working", "student"}]
            # Keep engineer when the remaining title would be too short.
            if len(role_words) < 2:
                role_words = re.findall(r"[A-Za-z]{3,}", role_title)
            phrase = " ".join(role_words[:4])
            if len(phrase) >= 10:
                role_query = f'in:anywhere -in:spam newer_than:{max(days, 1)}d "{phrase}"'
                listed = search_messages(role_query)
        for item in listed:
            message_id = item.get("id")
            if message_id and message_id not in seen_ids and targeted_listed < 150:
                seen_ids.add(message_id)
                message_ids.append(message_id)
                targeted_listed += 1

    if only_app_id is None and not targeted_only:
        gmail_query = _gmail_message_query(days)
        page_token = None
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
    classified_messages = unmatched_messages = previously_processed = 0
    revised_rejections = 0
    invalidated_apps: set[int] = set()
    invalidated_subjects: dict[int, set[str]] = {}
    outcomes: dict[str, int] = {}

    for message_id in message_ids:
        if not message_id:
            continue
        existing = db.query(GmailEvent).filter(
            GmailEvent.user_id == user_id,
            GmailEvent.gmail_message_id == message_id,
        ).first()
        if existing:
            previously_processed += 1
            linked = next(
                (app for app in applications if app.id == existing.application_id),
                None,
            )
            if only_app_id is not None and (not linked or linked.id != only_app_id):
                continue
            if existing.outcome == "Rejected":
                # Revalidate legacy decisions from the actual Gmail body,
                # never trust the cached classifier result as proof forever.
                response = httpx.get(
                    f"{GMAIL_API}/users/me/messages/{message_id}",
                    headers=headers,
                    params=[("format", "full"), ("metadataHeaders", "Subject"),
                            ("metadataHeaders", "From"), ("metadataHeaders", "Date")],
                    timeout=20,
                )
                response.raise_for_status()
                original = response.json()
                meta = _gmail_headers(original)
                actual_subject = meta.get("subject", existing.subject)
                actual_sender = meta.get("from", existing.sender)
                actual_body = _message_body_text(original) or original.get("snippet", "")
                new_outcome = classify_message(actual_subject, actual_body)
                candidate = match_application(
                    applications, actual_subject, actual_sender, actual_body[:2000]
                )
                valid_match = linked and candidate and candidate.id == linked.id
                if new_outcome != "Rejected" or not valid_match:
                    existing.outcome = new_outcome if valid_match and new_outcome else "NeedsReview"
                    existing.subject = actual_subject[:500]
                    existing.sender = actual_sender[:500]
                    revised_rejections += 1
                    if linked:
                        invalidated_apps.add(linked.id)
                        invalidated_subjects.setdefault(linked.id, set()).add(actual_subject)
                    continue
            if linked and existing.outcome:
                if _apply_outcome(linked, existing.outcome):
                    updated += 1
            continue

        response = httpx.get(
            f"{GMAIL_API}/users/me/messages/{message_id}",
            headers=headers,
            params=[
                ("format", "full"),
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
        body_text = _message_body_text(message)
        outcome = classify_message(subject, f"{snippet} {body_text}")
        if not outcome:
            continue
        classified_messages += 1

        app = match_application(applications, subject, sender, f"{snippet} {body_text[:2000]}")
        if not app or (only_app_id is not None and app.id != only_app_id):
            unmatched_messages += 1
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

    # Recalculate ONLY the applications whose cached "Rejected" event has
    # just failed revalidation. Never erase a different genuine rejection.
    for app_id in invalidated_apps:
        linked = next((app for app in applications if app.id == app_id), None)
        if not linked or linked.status != "Rejected":
            continue
        signals = db.query(GmailEvent).filter(
            GmailEvent.user_id == user_id,
            GmailEvent.application_id == app_id,
        ).order_by(GmailEvent.received_at.desc().nullslast(), GmailEvent.created_at.desc()).all()
        if any(signal.outcome == "Rejected" for signal in signals):
            continue
        for candidate in signals:
            if candidate.outcome in {"Offer", "Interview", "Screening", "Applied"}:
                linked.status = candidate.outcome
                break
        else:
            linked.status = "Applied"
        # Remove only invalidated auto-generated rejection note lines.
        invalid_subjects = invalidated_subjects.get(app_id, set())
        linked.notes = "\n".join(
            line for line in (linked.notes or "").splitlines()
            if not (
                line.startswith("Gmail signal: Rejected")
                and any(subject in line for subject in invalid_subjects)
            )
        )
        updated += 1

    connection.last_synced_at = datetime.utcnow()
    db.commit()

    return {
        "scanned": scanned,
        "listed": len(message_ids),
        "targeted_listed": targeted_listed,
        "classified": classified_messages,
        "unmatched": unmatched_messages,
        "already_processed": previously_processed,
        "corrected_false_rejections": revised_rejections,
        "gmail_account": connection.google_email,
        "targeted_only": targeted_only or only_app_id is not None,
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
