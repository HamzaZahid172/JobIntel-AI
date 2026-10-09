import html
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from .intelligence import extract_skills, is_target_technical_role
from .models import CVProfile, LiveJob

logger = logging.getLogger("jobintel.sources")

ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
JOBICY_URL = "https://jobicy.com/api/v2/remote-jobs"
REMOTIVE_URL = "https://remotive.com/api/remote-jobs"
FEED_SOURCES = ("Arbeitnow", "Jobicy", "Remotive")
MIN_SYNC_INTERVAL = timedelta(hours=1)
# Respect Remotive's public API guidance; refresh this source no more than every 6 h.
REMOTIVE_MIN_SYNC_INTERVAL = timedelta(hours=6)

GERMAN_LOCATIONS = (
    "germany", "berlin", "munich", "münchen", "hamburg", "frankfurt", "cologne",
    "köln", "stuttgart", "dresden", "leipzig", "düsseldorf", "dusseldorf", "bonn",
    "nuremberg", "nürnberg", "hannover", "hanover", "bremen", "erfurt", "ilmenau",
    "karlsruhe", "darmstadt", "potsdam", "aachen", "mannheim", "heidelberg",
    "regensburg", "ulm", "jena", "remote",
)


def listish(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if x]
    return [str(value)]


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def relevant_role(title: str, description: str = "") -> bool:
    return is_target_technical_role(title, description)


def germany_relevant(location: str, remote: bool, url: str = "") -> bool:
    loc = (location or "").lower()
    if any(place in loc for place in GERMAN_LOCATIONS):
        return True
    return bool(remote and "arbeitnow.com" in (url or "").lower())


def parse_timestamp(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def latest_cv(db: Session, user_id: int | None = None) -> CVProfile | None:
    query = db.query(CVProfile)
    if user_id is not None:
        query = query.filter(CVProfile.user_id == user_id)
    return query.order_by(CVProfile.uploaded_at.desc()).first()


def fetch_arbeitnow(client: httpx.Client, pages: int = 3) -> list[dict]:
    jobs: list[dict] = []
    for page in range(1, pages + 1):
        response = client.get(ARBEITNOW_URL, params={"page": page})
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data", [])
        for item in rows:
            description = strip_html(item.get("description"))
            title = item.get("title") or ""
            location = item.get("location") or "Germany"
            remote = bool(item.get("remote"))
            url = item.get("url") or ""
            if not relevant_role(title, description) or not germany_relevant(location, remote, url):
                continue
            tags = listish(item.get("tags"))
            jobs.append({
                "source": "Arbeitnow",
                "source_id": str(item.get("slug") or url),
                "title": title,
                "company": item.get("company_name") or "Unknown",
                "location": location,
                "remote": remote,
                "url": url,
                "description": description,
                "skills": extract_skills(" ".join([title, description, " ".join(tags)])),
                "job_types": listish(item.get("job_types")),
                "posted_at": parse_timestamp(item.get("created_at")),
            })
        if not rows:
            break
    return jobs


def fetch_jobicy(client: httpx.Client, count: int = 100) -> list[dict]:
    response = client.get(JOBICY_URL, params={"count": count, "geo": "germany"})
    response.raise_for_status()
    payload = response.json()
    jobs: list[dict] = []
    for item in payload.get("jobs", []):
        description = strip_html(item.get("jobDescription"))
        title = item.get("jobTitle") or ""
        if not relevant_role(title, description):
            continue
        industries = listish(item.get("jobIndustry"))
        jobs.append({
            "source": "Jobicy",
            "source_id": str(item.get("id") or item.get("url")),
            "title": title,
            "company": item.get("companyName") or "Unknown",
            "location": item.get("jobGeo") or "Remote · Germany",
            "remote": True,
            "url": item.get("url") or "",
            "description": description,
            "skills": extract_skills(" ".join([title, description, " ".join(industries)])),
            "job_types": listish(item.get("jobType")),
            "posted_at": parse_timestamp(item.get("pubDate")),
        })
    return jobs


def remotive_germany_eligible(location: str) -> bool:
    """Accept German, EU/EMEA, or genuinely worldwide remote openings."""
    value = (location or "").lower().strip()
    return any(term in value for term in (
        "germany", "deutschland", "europe", "european union",
        "emea", "eu only", "worldwide", "anywhere", "global",
    ))


def fetch_remotive(client: httpx.Client, limit: int = 100) -> list[dict]:
    """Public Remotive API; keep attribution and link directly to Remotive."""
    response = client.get(REMOTIVE_URL, params={"limit": limit})
    response.raise_for_status()
    rows = response.json().get("jobs", [])
    jobs = []
    for item in rows:
        title = item.get("title") or ""
        location = item.get("candidate_required_location") or ""
        description = strip_html(item.get("description"))
        if not remotive_germany_eligible(location) or not relevant_role(title, description):
            continue
        url = item.get("url") or ""
        if not url.startswith("https://remotive.com/"):
            continue
        jobs.append({
            "source": "Remotive",
            "source_id": str(item.get("id") or url),
            "title": title,
            "company": item.get("company_name") or "Unknown",
            "location": location,
            "remote": True,
            "url": url,
            "description": description,
            "skills": extract_skills(title + " " + description),
            "job_types": listish(item.get("job_type")),
            "posted_at": parse_timestamp(item.get("publication_date")),
        })
    return jobs


def sync_current_jobs(db: Session, force: bool = False) -> dict:
    now = datetime.utcnow()
    latest_general = (
        db.query(LiveJob).filter(LiveJob.source.in_(("Arbeitnow", "Jobicy")))
        .order_by(LiveJob.fetched_at.desc()).first()
    )
    if (
        not force and latest_general
        and now - latest_general.fetched_at < MIN_SYNC_INTERVAL
    ):
        return {
            "stored": db.query(LiveJob).count(), "fetched": 0,
            "errors": [], "sources": list(FEED_SOURCES), "cached": True,
            "next_refresh_after": (latest_general.fetched_at + MIN_SYNC_INTERVAL).isoformat(),
        }

    latest_remotive = (
        db.query(LiveJob).filter(LiveJob.source == "Remotive")
        .order_by(LiveJob.fetched_at.desc()).first()
    )
    remotive_due = not latest_remotive or now - latest_remotive.fetched_at >= REMOTIVE_MIN_SYNC_INTERVAL
    loaders = [("Arbeitnow", fetch_arbeitnow), ("Jobicy", fetch_jobicy)]
    if remotive_due:
        loaders.append(("Remotive", fetch_remotive))

    results: dict[str, list[dict]] = {}
    errors: list[str] = []
    with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": "JobIntelAI/1.0"}) as client:
        for name, loader in loaders:
            try:
                results[name] = loader(client)
            except Exception as exc:
                logger.exception("%s sync failed", name)
                errors.append(f"{name}: {type(exc).__name__}")

    # Update successful sources independently; retain the last known listings
    # from any source whose API temporarily failed.
    fetched = 0
    for name, rows in results.items():
        deduped = {(item["source"], item["source_id"]): item for item in rows}
        db.query(LiveJob).filter(LiveJob.source == name).delete(synchronize_session=False)
        for item in deduped.values():
            db.add(LiveJob(
                source=item["source"],
                source_id=item["source_id"],
                title=item["title"],
                company=item["company"],
                location=item["location"],
                remote=item["remote"],
                url=item["url"],
                description=item["description"],
                skills=",".join(item["skills"]),
                job_types=",".join(item["job_types"]),
                match_score=None,
                posted_at=item["posted_at"],
                fetched_at=now,
            ))
        fetched += len(rows)
    if results:
        db.commit()

    return {
        "stored": db.query(LiveJob).count(),
        "fetched": fetched,
        "errors": errors,
        "sources": list(FEED_SOURCES),
        "cached": False,
        "remotive_cached": not remotive_due,
    }


def rescore_jobs(db: Session, cv: CVProfile) -> int:
    return db.query(LiveJob).count()
