import html
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from .intelligence import extract_skills, match_cv_to_job
from .models import CVProfile, LiveJob

logger = logging.getLogger("jobintel.sources")

ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"
JOBICY_URL = "https://jobicy.com/api/v2/remote-jobs"
MIN_SYNC_INTERVAL = timedelta(hours=1)

ROLE_TERMS = (
    "software", "developer", "engineer", "backend", "full stack", "fullstack",
    "data", "automation", "qa", "quality assurance", "test", "machine learning",
    "artificial intelligence", " ai ", "ml ", "platform", "devops", "cloud",
    "site reliability", "sre", "python", "fastapi", "werkstudent", "working student",
)

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
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def relevant_role(title: str, description: str = "") -> bool:
    haystack = f" {title} {description[:4000]} ".lower()
    return any(term in haystack for term in ROLE_TERMS)


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


def latest_cv(db: Session) -> CVProfile | None:
    return db.query(CVProfile).order_by(CVProfile.uploaded_at.desc()).first()


def _score(cv: CVProfile | None, title: str, description: str) -> float | None:
    if not cv:
        return None
    return float(match_cv_to_job(cv.text, f"{title}\n{description}")["overall_score"])


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
            if not relevant_role(title, description):
                continue
            if not germany_relevant(location, remote, url):
                continue
            tags = listish(item.get("tags"))
            skills = extract_skills(" ".join([title, description, " ".join(tags)]))
            jobs.append({
                "source": "Arbeitnow",
                "source_id": str(item.get("slug") or url),
                "title": title,
                "company": item.get("company_name") or "Unknown",
                "location": location,
                "remote": remote,
                "url": url,
                "description": description,
                "skills": skills,
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
        skills = extract_skills(" ".join([title, description, " ".join(industries)]))
        jobs.append({
            "source": "Jobicy",
            "source_id": str(item.get("id") or item.get("url")),
            "title": title,
            "company": item.get("companyName") or "Unknown",
            "location": item.get("jobGeo") or "Remote · Germany",
            "remote": True,
            "url": item.get("url") or "",
            "description": description,
            "skills": skills,
            "job_types": listish(item.get("jobType")),
            "posted_at": parse_timestamp(item.get("pubDate")),
        })
    return jobs


def sync_current_jobs(db: Session) -> dict:
    last_job = db.query(LiveJob).order_by(LiveJob.fetched_at.desc()).first()
    if last_job and datetime.utcnow() - last_job.fetched_at < MIN_SYNC_INTERVAL:
        return {
            "stored": db.query(LiveJob).count(),
            "fetched": 0,
            "errors": [],
            "sources": ["Arbeitnow", "Jobicy"],
            "cached": True,
            "next_refresh_after": (last_job.fetched_at + MIN_SYNC_INTERVAL).isoformat(),
        }

    cv = latest_cv(db)
    fetched: list[dict] = []
    errors: list[str] = []

    with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": "JobIntelAI/0.2"}) as client:
        for name, loader in (("Arbeitnow", fetch_arbeitnow), ("Jobicy", fetch_jobicy)):
            try:
                fetched.extend(loader(client))
            except Exception as exc:
                logger.exception("%s sync failed", name)
                errors.append(f"{name}: {type(exc).__name__}")

    deduped: dict[tuple[str, str], dict] = {}
    for item in fetched:
        deduped[(item["source"], item["source_id"])] = item

    if deduped:
        db.query(LiveJob).delete()
        now = datetime.utcnow()
        for item in deduped.values():
            description = item["description"]
            db.add(LiveJob(
                source=item["source"],
                source_id=item["source_id"],
                title=item["title"],
                company=item["company"],
                location=item["location"],
                remote=item["remote"],
                url=item["url"],
                description=description,
                skills=",".join(item["skills"]),
                job_types=",".join(item["job_types"]),
                match_score=_score(cv, item["title"], description),
                posted_at=item["posted_at"],
                fetched_at=now,
            ))
        db.commit()

    return {
        "stored": db.query(LiveJob).count(),
        "fetched": len(fetched),
        "errors": errors,
        "sources": ["Arbeitnow", "Jobicy"],
        "cached": False,
    }


def rescore_jobs(db: Session, cv: CVProfile) -> int:
    jobs = db.query(LiveJob).all()
    for job in jobs:
        job.match_score = _score(cv, job.title, job.description)
    db.commit()
    return len(jobs)
