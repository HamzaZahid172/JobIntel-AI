"""Find real employer reply addresses; never invent guessed contacts."""
import os
import re
from datetime import datetime
from email.utils import parseaddr
from urllib.parse import urlparse, quote

import httpx
from sqlalchemy.orm import Session

from .gmail_sync import GMAIL_API, ensure_access_token, match_application
from .models import Application, GmailConnection, GmailEvent, LiveJob

EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Za-z0-9.!#$%&'*+/=?^_{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![\w-])")
BAD_MAILBOX = re.compile(
    r"(^|[._-])(no.?reply|do.?not.?reply|notification|automated|mailer.?daemon|"
    r"bounce|unsubscribe|newsletter|alerts?|marketing|support|help|helpdesk|sales|billing|press|media)([._+-]|$)", re.I,
)
FREE_DOMAINS = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "gmx.de", "web.de"}
JOB_BOARD_HOSTS = {"arbeitnow.com", "jobicy.com", "remotive.com", "linkedin.com", "indeed.com", "stepstone.de", "workwise.io", "glassdoor.com"}
ATS_HOSTS = {"ashbyhq.com", "greenhouse.io", "lever.co", "smartrecruiters.com", "myworkdayjobs.com"}


def valid_contact(raw: str) -> str | None:
    if not raw or any(c in raw for c in "\r\n") or "," in raw or ";" in raw:
        return None
    email = parseaddr(raw)[1].strip().lower()
    if not EMAIL_RE.fullmatch(email):
        return None
    local, domain = email.split("@", 1)
    if BAD_MAILBOX.search(local) or domain.startswith("localhost") or domain.endswith(".local"):
        return None
    return email


def known_employer_domain(domain: str, company: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", company.lower())
    stop = {"gmbh", "ag", "inc", "ltd", "group", "holding", "company", "the", "technologies", "technology", "software"}
    strong = [t for t in tokens if len(t) >= 5 and t not in stop]
    label = domain.lower().split(".", 1)[0]
    return any(t in label for t in strong)


def candidate(email: str, source: str, detail: str, confidence: str, evidence_url: str = "") -> dict:
    return {
        "email": email, "source": source, "source_detail": detail[:140],
        "confidence": confidence, "evidence_url": evidence_url, "requires_review": True,
    }


def _eligible_sender(value: str, own_email: str, company: str, *, explicit_reply_to: bool = False) -> str | None:
    address = valid_contact(value)
    if not address or address == (own_email or "").lower():
        return None
    domain = address.rsplit("@", 1)[1]
    if domain in FREE_DOMAINS:
        return None
    if any(domain == host or domain.endswith("." + host) for host in JOB_BOARD_HOSTS):
        return None
    if not explicit_reply_to and any(domain == host or domain.endswith("." + host) for host in ATS_HOSTS):
        return None
    return address


def event_contacts(events: list[GmailEvent], own_email: str, company: str) -> list[dict]:
    contacts = []
    for event in events:
        if event.outcome in {"Rejected", "Offer"}:
            continue
        address = _eligible_sender(event.sender, own_email, company)
        if address:
            domain = address.split("@")[1]
            confidence = "high" if known_employer_domain(domain, company) else "review"
            contacts.append(candidate(address, "gmail_history", f"Application correspondence: {event.subject}", confidence))
    return contacts


def description_contacts(app: Application, jobs: list[LiveJob]) -> list[dict]:
    contacts = []
    for job in jobs:
        if (job.company or "").strip().lower() != (app.company or "").strip().lower():
            continue
        if app.url and job.url and app.url.rstrip("/") != job.url.rstrip("/") and job.title.strip().lower() != app.role.strip().lower():
            continue
        text = (job.description or "")[:40000]
        for email in set(EMAIL_RE.findall(text)):
            address = _eligible_sender(email, "", app.company)
            if not address:
                continue
            idx = text.lower().find(email.lower())
            surrounding = text[max(0, idx-180):idx+180].lower()
            if not any(t in surrounding for t in ("application", "apply", "bewerbung", "recruit", "career", "hr team", "hiring", "talent")):
                continue
            contacts.append(candidate(address, "job_posting", f"Listed in {job.source} job description", "review", job.url))
    return contacts


def normalize_candidates(contacts: list[dict]) -> list[dict]:
    unique = {}
    priority = {"gmail_reply_to": 0, "gmail_history": 1, "gmail_sender": 2, "job_posting": 3, "public_web": 4}
    for item in contacts:
        key = item["email"].lower()
        if key not in unique or priority.get(item["source"], 99) < priority.get(unique[key]["source"], 99):
            unique[key] = item
    return sorted(unique.values(), key=lambda c: (priority.get(c["source"], 99), 0 if c["confidence"] == "high" else 1, c["email"]))


def _gmail_metadata(message: dict) -> dict:
    return {
        h["name"].lower(): h.get("value", "")
        for h in message.get("payload", {}).get("headers", [])
        if h.get("name", "").lower() in {"from", "reply-to", "subject", "date"}
    }


def mailbox_contacts(db: Session, connection: GmailConnection, app: Application, applications: list[Application]) -> list[dict]:
    token = ensure_access_token(db, connection)
    headers = {"Authorization": f"Bearer {token}"}
    company = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß .&-]", "", app.company or "").strip()[:90]
    if not company or len(company) < 3:
        return []
    params = {"q": f'in:anywhere -in:spam -in:sent newer_than:180d "{company}"',
              "maxResults": 35, "includeSpamTrash": True}
    listing = httpx.get(f"{GMAIL_API}/users/me/messages", headers=headers, params=params, timeout=12)
    listing.raise_for_status()
    results = []
    for summary in listing.json().get("messages", [])[:35]:
        message_id = summary.get("id")
        if not message_id:
            continue
        response = httpx.get(
            f"{GMAIL_API}/users/me/messages/{message_id}", headers=headers,
            params=[("format", "metadata"), ("metadataHeaders", "From"),
                    ("metadataHeaders", "Reply-To"), ("metadataHeaders", "Subject")],
            timeout=12,
        )
        response.raise_for_status()
        message = response.json()
        meta = _gmail_metadata(message)
        subject, sender, snippet = meta.get("subject", ""), meta.get("from", ""), message.get("snippet", "")
        matched = match_application(applications, subject, sender, snippet)
        if matched is None or matched.id != app.id:
            continue
        internal = message.get("internalDate")
        if internal and app.applied_date:
            try:
                if datetime.fromtimestamp(int(internal) / 1000).date() < app.applied_date:
                    continue
            except (ValueError, TypeError, OverflowError):
                continue
        for header, source in (("reply-to", "gmail_reply_to"), ("from", "gmail_sender")):
            addr = _eligible_sender(meta.get(header, ""), connection.google_email, app.company, explicit_reply_to=header=="reply-to")
            if not addr:
                continue
            domain = addr.rsplit("@", 1)[1]
            confidence = "high" if known_employer_domain(domain, app.company) else "review"
            results.append(candidate(addr, source, f"{header.title()} of an application email: {subject}", confidence))
        if len(results) >= 12:
            break
    return results


def _web_contact_candidates(company: str) -> list[dict]:
    """Optional public-web lookup: published addresses only, never guess a mailbox."""
    api_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        return []
    response = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        params={"q": f'"{company}" careers recruitment email contact', "count": 5,
                "country": "de", "search_lang": "en"}, timeout=10,
    )
    response.raise_for_status()
    contacts = []
    for result in response.json().get("web", {}).get("results", []):
        url = result.get("url", "")
        try:
            parsed = urlparse(url)
        except ValueError:
            continue
        if parsed.scheme != "https" or not parsed.hostname:
            continue
        host = parsed.hostname.lower()
        if not known_employer_domain(host, company):
            continue
        snippets = result.get("extra_snippets") or []
        text = " ".join([result.get("title", ""), result.get("description", ""), " ".join(snippets) if isinstance(snippets, list) else ""])
        if not any(k in text.lower() for k in ("career", "recruit", "application", "jobs", "bewerbung", "talent", "kontakt")):
            continue
        for email in set(EMAIL_RE.findall(text)):
            addr = _eligible_sender(email, "", company)
            if not addr or not known_employer_domain(addr.split("@")[1], company):
                continue
            contacts.append(candidate(addr, "public_web", "Public search result — verify on employer website before sending", "review", url))
    return contacts


def discover_contact(db: Session, user_id: int, app: Application, *, search: bool = False) -> dict:
    events = db.query(GmailEvent).filter(
        GmailEvent.user_id == user_id, GmailEvent.application_id == app.id
    ).order_by(GmailEvent.received_at.desc().nullslast(), GmailEvent.created_at.desc()).limit(30).all()
    connection = db.query(GmailConnection).filter(GmailConnection.user_id == user_id).first()
    contacts = event_contacts(events, connection.google_email if connection else "", app.company)
    jobs = db.query(LiveJob).filter(LiveJob.company.ilike(app.company)).limit(50).all()
    contacts.extend(description_contacts(app, jobs))
    warning = ""
    if search and connection:
        try:
            applications = db.query(Application).filter(Application.user_id == user_id).all()
            contacts.extend(mailbox_contacts(db, connection, app, applications))
        except (httpx.HTTPError, RuntimeError, ValueError):
            warning = "Gmail lookup was unavailable; saved application correspondence was checked."
    if search:
        try:
            contacts.extend(_web_contact_candidates(app.company))
        except (httpx.HTTPError, ValueError):
            warning += " Public web lookup was unavailable."
    sorted_contacts = normalize_candidates(contacts)
    high = [x for x in sorted_contacts if x["confidence"] == "high" and x["source"].startswith("gmail")]
    recommended = high[0]["email"] if len({x["email"] for x in high}) == 1 else None
    query = quote(f'{app.company} careers recruiting HR email contact')
    return {
        "application_id": app.id, "company": app.company,
        "candidates": sorted_contacts[:12], "recommended": recommended,
        "warning": warning.strip(),
        "web_search_url": f"https://www.google.com/search?q={query}",
        "lookup_mode": "gmail_and_public_results" if search else "saved_correspondence_and_job_ad",
        "public_search_enabled": bool(os.getenv("BRAVE_SEARCH_API_KEY")),
    }
