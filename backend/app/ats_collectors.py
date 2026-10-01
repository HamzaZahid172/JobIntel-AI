import logging
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from .intelligence import extract_skills, is_target_technical_role
from .models import CollectorTarget, LiveJob
from .sources import parse_timestamp, strip_html

logger = logging.getLogger("jobintel.ats_collectors")

GERMANY_HINTS = (
    "germany", "deutschland", "berlin", "munich", "münchen", "hamburg",
    "frankfurt", "cologne", "köln", "stuttgart", "dresden", "leipzig",
    "düsseldorf", "dusseldorf", "hannover", "nuremberg", "nürnberg",
    "bremen", "erfurt", "ilmenau", "karlsruhe", "darmstadt", "aachen",
    "mannheim", "heidelberg", "regensburg", "ulm", "jena",
)

REMOTE_EU_HINTS = ("remote", "europe", "eu", "emea", "cet", "cest")

PROVIDER_SOURCE = {
    "lever": "Lever",
    "lever-eu": "Lever",
    "smartrecruiters": "SmartRecruiters",
    "ashby": "Ashby",
}


def _germany_or_remote_eu(location: str, remote: bool = False, country: str = "") -> bool:
    loc = (location or "").lower()
    country_l = (country or "").lower()
    if country_l in {"de", "deu", "germany", "deutschland"}:
        return True
    if any(hint in loc for hint in GERMANY_HINTS):
        return True
    return bool(remote and any(hint in loc for hint in REMOTE_EU_HINTS))


def fetch_lever(client: httpx.Client, target: CollectorTarget) -> list[dict]:
    provider = target.provider.lower()
    host = "https://api.eu.lever.co" if provider == "lever-eu" else "https://api.lever.co"
    response = client.get(
        f"{host}/v0/postings/{target.identifier}",
        params={"mode": "json", "limit": 100},
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    rows = response.json()
    jobs = []
    for item in rows:
        title = item.get("text") or ""
        categories = item.get("categories") or {}
        location = categories.get("location") or ", ".join(categories.get("allLocations") or []) or "Unknown"
        remote = (item.get("workplaceType") or "").lower() == "remote"
        country = item.get("country") or ""
        description = item.get("descriptionPlain") or strip_html(item.get("description"))
        if not is_target_technical_role(title, description):
            continue
        if not _germany_or_remote_eu(location, remote, country):
            continue
        jobs.append({
            "source": "Lever",
            "source_id": f"{target.identifier}:{item.get('id')}",
            "title": title,
            "company": target.label,
            "location": location,
            "remote": remote,
            "url": item.get("hostedUrl") or item.get("applyUrl") or "",
            "description": description,
            "skills": extract_skills(title + " " + description),
            "job_types": [categories.get("commitment")] if categories.get("commitment") else [],
            "posted_at": parse_timestamp((item.get("createdAt") or 0) / 1000 if item.get("createdAt") else None),
        })
    return jobs


def _smart_description(detail: dict) -> str:
    sections = ((detail.get("jobAd") or {}).get("sections") or {})
    parts = []
    for key in ("jobDescription", "qualifications", "additionalInformation"):
        section = sections.get(key) or {}
        if section.get("text"):
            parts.append(strip_html(section["text"]))
    return "\n".join(parts).strip()


def fetch_smartrecruiters(client: httpx.Client, target: CollectorTarget) -> list[dict]:
    base = f"https://api.smartrecruiters.com/v1/companies/{target.identifier}/postings"
    response = client.get(
        base,
        params={"country": "de", "destination": "PUBLIC", "limit": 100, "offset": 0},
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("content") or payload.get("results") or []
    jobs = []
    for item in rows:
        title = item.get("name") or ""
        if not is_target_technical_role(title, ""):
            continue
        posting_id = item.get("id") or item.get("uuid")
        if not posting_id:
            continue
        detail_response = client.get(f"{base}/{posting_id}", headers={"Accept": "application/json"})
        detail_response.raise_for_status()
        detail = detail_response.json()
        description = _smart_description(detail)
        if not is_target_technical_role(title, description):
            continue
        location_obj = detail.get("location") or item.get("location") or {}
        location = ", ".join(
            str(x) for x in (location_obj.get("city"), location_obj.get("region"), location_obj.get("country"))
            if x
        ) or "Germany"
        remote = bool(location_obj.get("remote"))
        if not _germany_or_remote_eu(location, remote, location_obj.get("country") or ""):
            continue
        company = (detail.get("company") or {}).get("name") or target.label
        employment = detail.get("typeOfEmployment") or {}
        jobs.append({
            "source": "SmartRecruiters",
            "source_id": f"{target.identifier}:{posting_id}",
            "title": title,
            "company": company,
            "location": location,
            "remote": remote,
            "url": detail.get("postingUrl") or detail.get("applyUrl") or "",
            "description": description,
            "skills": extract_skills(title + " " + description),
            "job_types": [employment.get("label")] if employment.get("label") else [],
            "posted_at": parse_timestamp(detail.get("releasedDate") or item.get("releasedDate")),
        })
    return jobs


def _ashby_location(item: dict) -> tuple[str, str]:
    primary = item.get("location") or ""
    secondary = [
        row.get("location") or ""
        for row in (item.get("secondaryLocations") or [])
        if row.get("location")
    ]
    all_locations = [primary, *secondary]
    location = " · ".join(dict.fromkeys(x for x in all_locations if x)) or "Unknown"

    postal = ((item.get("address") or {}).get("postalAddress") or {})
    country = postal.get("addressCountry") or ""
    if not country:
        for row in item.get("secondaryLocations") or []:
            country = ((row.get("address") or {}).get("addressCountry") or "")
            if country:
                break
    return location, country


def fetch_ashby(client: httpx.Client, target: CollectorTarget) -> list[dict]:
    response = client.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{target.identifier}",
        params={"includeCompensation": "false"},
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    jobs = []

    for item in payload.get("jobs") or []:
        if item.get("isListed") is False:
            continue

        title = item.get("title") or ""
        description = item.get("descriptionPlain") or strip_html(item.get("descriptionHtml"))
        if not is_target_technical_role(title, description):
            continue

        location, country = _ashby_location(item)
        remote = bool(item.get("isRemote")) or (item.get("workplaceType") or "").lower() == "remote"
        if not _germany_or_remote_eu(location, remote, country):
            continue

        stable_id = item.get("jobUrl") or item.get("applyUrl") or f"{title}:{location}"
        jobs.append({
            "source": "Ashby",
            "source_id": f"{target.identifier}:{stable_id}",
            "title": title,
            "company": target.label,
            "location": location,
            "remote": remote,
            "url": item.get("applyUrl") or item.get("jobUrl") or "",
            "description": description,
            "skills": extract_skills(title + " " + description),
            "job_types": [item.get("employmentType")] if item.get("employmentType") else [],
            "posted_at": parse_timestamp(item.get("publishedAt")),
        })

    return jobs


def _fetch_target(client: httpx.Client, target: CollectorTarget) -> tuple[str, list[dict]]:
    provider = target.provider.lower().strip()
    if provider in {"lever", "lever-eu"}:
        return "Lever", fetch_lever(client, target)
    if provider == "smartrecruiters":
        return "SmartRecruiters", fetch_smartrecruiters(client, target)
    if provider == "ashby":
        return "Ashby", fetch_ashby(client, target)
    raise ValueError(f"Unsupported provider: {target.provider}")


def sync_configured_ats(db: Session, user_id: int) -> dict:
    targets = (
        db.query(CollectorTarget)
        .filter(CollectorTarget.user_id == user_id, CollectorTarget.enabled.is_(True))
        .all()
    )
    fetched = 0
    errors = []
    target_summaries = []

    with httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": "JobIntelAI/0.6"},
    ) as client:
        for target in targets:
            try:
                source, jobs = _fetch_target(client, target)
                prefix = f"{target.identifier}:"
                db.query(LiveJob).filter(
                    LiveJob.source == source,
                    LiveJob.source_id.like(prefix + "%"),
                ).delete(synchronize_session=False)

                now = datetime.utcnow()
                for item in jobs:
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

                db.commit()
                fetched += len(jobs)
                target_summaries.append({
                    "target": target.label,
                    "provider": target.provider,
                    "jobs": len(jobs),
                })
            except Exception as exc:
                db.rollback()
                logger.exception("ATS target sync failed: %s", target.label)
                errors.append(f"{target.label}: {type(exc).__name__}")

    return {
        "fetched": fetched,
        "targets": target_summaries,
        "errors": errors,
    }
