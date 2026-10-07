import base64
import hashlib
import json
import logging
import secrets
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date, datetime
from io import BytesIO

from docx import Document
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pypdf import PdfReader
from sqlalchemy.orm import Session

from .assistant import answer, assistant_status
from .application_preparation import build_application_package_payload
from .ats_collectors import PROVIDER_SOURCE, sync_configured_ats
from .cover_letter import build_cover_letter_docx, generate_cover_letter_text, safe_filename
from .auth import (
    claim_legacy_workspace,
    create_session,
    ensure_auth_columns,
    get_current_user,
    hash_password,
    logout_token,
    verify_password,
)
from .db import Base, SessionLocal, engine, get_db, wait_for_database
from .intelligence import (
    aggregate_skills,
    ats_check,
    extract_skills,
    improvement_suggestions,
    match_cv_to_job,
    profile_role_families,
    rank_cv_skills,
)
from .match_layer import build_match_report
from .models import Application, ApplicationPackage, CVProfile, CollectorTarget, Job, LiveJob, User
from .schemas import (
    ApplicationCreate,
    ApplicationOut,
    ApplicationPackageAnswerUpdate,
    ApplicationPreparationRequest,
    ApplicationUpdate,
    AssistantRequest,
    BulkJobImport,
    CollectorTargetCreate,
    LoginRequest,
    ManualJobImport,
    MatchRequest,
    ProfileUpdate,
    RegisterRequest,
)
from .sources import latest_cv, rescore_jobs, sync_current_jobs

logger = logging.getLogger("jobintel")


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "target_roles": user.target_roles,
        "target_locations": user.target_locations,
        "created_at": user.created_at.isoformat(),
    }


def cleanup_legacy_demo_data(db: Session) -> None:
    apps = db.query(Application).all()
    demo_companies = {"SAP", "Bosch", "Example GmbH"}
    if apps and len(apps) <= 3 and {a.company for a in apps}.issubset(demo_companies):
        for app in apps:
            db.delete(app)
    db.query(Job).delete()
    db.commit()


def extract_document_text(filename: str, raw: bytes) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".pdf"):
        reader = PdfReader(BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if lower.endswith(".docx"):
        doc = Document(BytesIO(raw))
        return "\n".join(p.text for p in doc.paragraphs).strip()
    if lower.endswith(".txt"):
        return raw.decode("utf-8", errors="ignore").strip()
    raise HTTPException(400, "Upload a PDF, DOCX or TXT CV.")


def refresh_cv_analysis(db: Session, cv: CVProfile) -> dict:
    result = ats_check(cv.text)
    cv.skills = ",".join(result["skills_detected"])
    cv.ats_score = result["score"]
    cv.ats_status = result["status"]
    cv.ats_json = json.dumps(result)
    db.commit()
    return result


def match_details(cv: CVProfile, job: LiveJob) -> dict:
    return build_match_report(
        cv.text,
        job.title,
        job.description,
        job.location,
        job.remote,
    )


def serialize_job(job: LiveJob, details: dict | None = None) -> dict:
    return {
        "id": job.id,
        "source": job.source,
        "source_id": job.source_id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "remote": job.remote,
        "url": job.url,
        "description": job.description,
        "skills": [s for s in job.skills.split(",") if s],
        "job_types": [s for s in job.job_types.split(",") if s],
        "match": details["overall_score"] if details else job.match_score,
        "role_score": details["role_score"] if details else None,
        "matched_skills": details["matched_skills"] if details else [],
        "missing_skills": details["missing_skills"] if details else [],
        "job_role_families": details["job_role_families"] if details else [],
        "score_breakdown": details.get("score_breakdown", {}) if details else {},
        "requirements": details.get("requirements", {}) if details else {},
        "hard_blockers": details.get("hard_blockers", []) if details else [],
        "reasons": details.get("reasons", []) if details else [],
        "eligible_for_preparation": details.get("eligible_for_preparation", False) if details else False,
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        "fetched_at": job.fetched_at.isoformat() if job.fetched_at else None,
    }


def _target_role_families(target_roles: str = "") -> set[str]:
    text = (target_roles or "").lower()
    families = set()
    if any(term in text for term in ("backend", "python", "software engineer", "software developer")):
        families.add("software_backend")
    if any(term in text for term in ("qa", "automation", "sdet", "test")):
        families.add("automation_qa")
    if any(term in text for term in ("data engineer", "data engineering", "etl", "data platform")):
        families.add("data_engineering")
    if any(term in text for term in ("ai", "ml", "machine learning", "llm")):
        families.add("ai_ml")
    if any(term in text for term in ("frontend", "fullstack", "full stack")):
        families.add("frontend_fullstack")
    if any(term in text for term in ("devops", "platform", "sre", "cloud engineer")):
        families.add("devops_platform")
    return families


def candidate_job_records(
    cv: CVProfile | None,
    jobs: list[LiveJob],
    target_roles: str = "",
) -> list[tuple[LiveJob, dict | None]]:
    if not cv:
        return [(job, None) for job in jobs]

    strongest = {item["skill"] for item in rank_cv_skills(cv.text, limit=10)}
    target_families = _target_role_families(target_roles)
    records: list[tuple[LiveJob, dict]] = []
    for job in jobs:
        details = match_details(cv, job)
        job_skills = set(details["job_skills"])
        job_families = set(details["job_role_families"])
        strong_overlap = strongest & job_skills
        if target_families and job_families and not (target_families & job_families):
            continue
        if details["hard_blockers"]:
            continue
        if details["overall_score"] < 65 or details["role_score"] < 45:
            continue
        if not strong_overlap and len(details["matched_skills"]) < 2:
            continue
        records.append((job, details))

    records.sort(
        key=lambda row: (
            row[1]["overall_score"],
            row[1]["role_score"],
            row[0].posted_at or datetime.min,
        ),
        reverse=True,
    )
    return records


def build_skill_gap(cv: CVProfile | None, jobs: list[LiveJob]) -> list[dict]:
    if not cv:
        return []

    required_missing = Counter()
    preferred_missing = Counter()

    for job in jobs[:100]:
        details = match_details(cv, job)
        for skill in details.get("missing_required_skills", []):
            required_missing[skill] += 1
        for skill in details.get("missing_preferred_skills", []):
            preferred_missing[skill] += 1

    combined = Counter(required_missing)
    for skill, count in preferred_missing.items():
        combined[skill] += count

    suggestions = improvement_suggestions([s for s, _ in combined.most_common(12)])
    for suggestion in suggestions:
        key = suggestion["skill"].lower()
        suggestion["market_count"] = combined.get(key, 0)
        suggestion["required_count"] = required_missing.get(key, 0)
        suggestion["preferred_count"] = preferred_missing.get(key, 0)
        suggestion["gap_type"] = (
            "Required"
            if required_missing.get(key, 0) >= preferred_missing.get(key, 0)
            else "Preferred"
        )
    return suggestions[:6]


def build_source_analytics(
    db: Session,
    user_id: int,
    all_jobs: list[LiveJob],
    relevant_jobs: list[LiveJob],
) -> list[dict]:
    all_counts = Counter(job.source for job in all_jobs)
    relevant_counts = Counter(job.source for job in relevant_jobs)
    targets = (
        db.query(CollectorTarget)
        .filter(CollectorTarget.user_id == user_id)
        .all()
    )

    by_provider = Counter()
    enabled_by_provider = Counter()
    for target in targets:
        provider = target.provider.lower()
        canonical = PROVIDER_SOURCE.get(provider)
        if canonical:
            by_provider[canonical] += 1
            if target.enabled:
                enabled_by_provider[canonical] += 1

    canonical_sources = [
        ("Arbeitnow", "Public API", True),
        ("Jobicy", "Public API", True),
        ("Ashby", "Employer ATS", False),
        ("Lever", "Employer ATS", False),
        ("SmartRecruiters", "Employer ATS", False),
        ("Greenhouse", "Employer ATS", False),
    ]

    last_sync_by_source = {}
    for job in all_jobs:
        if not job.fetched_at:
            continue
        previous = last_sync_by_source.get(job.source)
        if previous is None or job.fetched_at > previous:
            last_sync_by_source[job.source] = job.fetched_at

    rows = []
    for source, mode, always_enabled in canonical_sources:
        target_count = by_provider.get(source, 0)
        enabled_targets = enabled_by_provider.get(source, 0)
        configured = always_enabled or target_count > 0
        status = (
            "active"
            if always_enabled
            else "configured"
            if enabled_targets > 0
            else "disabled"
            if target_count > 0
            else "not configured"
        )
        rows.append({
            "source": source,
            "mode": mode,
            "status": status,
            "configured": configured,
            "targets": target_count,
            "enabled_targets": enabled_targets,
            "jobs": all_counts.get(source, 0),
            "relevant_jobs": relevant_counts.get(source, 0),
            "last_sync": (
                last_sync_by_source[source].isoformat()
                if source in last_sync_by_source
                else None
            ),
        })

    extra_sources = sorted(
        set(all_counts) - {row[0] for row in canonical_sources}
    )
    for source in extra_sources:
        rows.append({
            "source": source,
            "mode": "Imported / external",
            "status": "active",
            "configured": True,
            "targets": 0,
            "enabled_targets": 0,
            "jobs": all_counts.get(source, 0),
            "relevant_jobs": relevant_counts.get(source, 0),
            "last_sync": (
                last_sync_by_source[source].isoformat()
                if source in last_sync_by_source
                else None
            ),
        })

    return rows


def application_performance(apps: list[Application]) -> list[dict]:
    grouped: dict[str, list[Application]] = {}
    for app in apps:
        grouped.setdefault(app.cv_version or "Current CV", []).append(app)

    result = []
    positive = {"Interview", "Final", "Offer"}
    for label, rows in grouped.items():
        interviews = sum(1 for row in rows if row.status in positive)
        result.append({
            "label": label,
            "value": round(interviews / len(rows) * 100) if rows else 0,
            "applications": len(rows),
        })
    return sorted(result, key=lambda x: (x["value"], x["applications"]), reverse=True)[:6]


def application_conversion_insights(apps: list[Application]) -> dict:
    submitted = [
        row for row in apps
        if row.status in {"Applied", "Screening", "Interview", "Final", "Offer", "Rejected"}
    ]
    total = len(submitted)
    positive_statuses = {"Screening", "Interview", "Final", "Offer"}
    positive = sum(1 for row in submitted if row.status in positive_statuses)
    interviews = sum(1 for row in submitted if row.status in {"Interview", "Final", "Offer"})
    rejected = sum(1 for row in submitted if row.status == "Rejected")
    pending = sum(1 for row in submitted if row.status == "Applied")
    high_match_rejections = sum(
        1 for row in submitted
        if row.status == "Rejected" and (row.match_score or 0) >= 75
    )

    recommendations = []
    if total >= 5 and positive == 0:
        recommendations.append(
            "Stop optimizing for application volume. Prioritize only roles with 80%+ match and clear alignment to your primary role family."
        )
    if high_match_rejections >= 2:
        recommendations.append(
            "High-match applications are still being rejected. Treat this as a positioning problem: tailor the first-page summary and experience bullets to the job's top required skills."
        )
    if total >= 5 and rejected / total >= 0.6:
        recommendations.append(
            "Rejection rate is high. Narrow job selection by required language, seniority, work authorization and must-have skills before preparing an application."
        )
    if pending >= 3:
        recommendations.append(
            "Several applications are still at Applied. Use the follow-up queue after 5–7 days and prioritize direct employer applications over broad portals."
        )
    if not recommendations:
        recommendations.append(
            "Keep tracking outcomes. The system will become more useful once applications are consistently updated through Screening, Interview, Offer or Rejected."
        )

    return {
        "submitted": total,
        "positive_responses": positive,
        "positive_response_rate": round(positive / total * 100) if total else 0,
        "interviews": interviews,
        "interview_rate": round(interviews / total * 100) if total else 0,
        "rejections": rejected,
        "rejection_rate": round(rejected / total * 100) if total else 0,
        "pending": pending,
        "high_match_rejections": high_match_rejections,
        "recommendations": recommendations[:3],
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    wait_for_database()
    Base.metadata.create_all(bind=engine)
    ensure_auth_columns()
    db = SessionLocal()
    try:
        cleanup_legacy_demo_data(db)
        if db.query(LiveJob).count() == 0:
            try:
                sync_current_jobs(db)
            except Exception:
                logger.exception("Initial live-job sync failed; app will start with an empty market.")
    finally:
        db.close()
    yield


app = FastAPI(title="JobIntel AI API", version="0.7.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-JobIntel-Generator"],
)


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.7.1"}


@app.post("/api/auth/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Enter a valid email address.")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists.")
    try:
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    user = User(
        email=email,
        display_name=payload.display_name.strip() or email.split("@")[0],
        password_hash=password_hash,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    claim_legacy_workspace(db, user)
    token = create_session(db, user)
    return {"token": token, "user": user_payload(user)}


@app.post("/api/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password.")
    claim_legacy_workspace(db, user)
    token = create_session(db, user)
    return {"token": token, "user": user_payload(user)}


@app.post("/api/auth/logout")
def logout(
    authorization: str | None = Header(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logout_token(db, authorization)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)):
    return user_payload(user)


@app.patch("/api/profile")
def update_profile(
    payload: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(user, field, value.strip())
    db.commit()
    db.refresh(user)
    return user_payload(user)


@app.get("/api/sources")
def sources(user: User = Depends(get_current_user)):
    return {
        "active": [
            {"name": "Arbeitnow", "mode": "Public API", "status": "active"},
            {"name": "Jobicy", "mode": "Public API", "status": "active"},
            {"name": "Lever", "mode": "Public employer postings", "status": "configurable"},
            {"name": "SmartRecruiters", "mode": "Public employer postings", "status": "configurable"},
            {"name": "Ashby", "mode": "Public Job Postings API", "status": "configurable"},
            {"name": "Greenhouse", "mode": "Public Job Board API", "status": "configurable"},
            {"name": "Manual / Bulk Import", "mode": "Normalized external jobs", "status": "active"},
        ],
        "planned": [
            {"name": "Additional ATS adapters", "mode": "More official/public employer feeds", "status": "planned"},
            {"name": "Apply Queue", "mode": "Human-approved application automation", "status": "architecture-ready"},
            {"name": "XING", "mode": "Authorized integration or manual import only", "status": "restricted"},
            {"name": "StepStone", "mode": "Authorized integration or manual import only", "status": "restricted"},
        ],
    }


@app.get("/api/jobs")
def jobs(
    limit: int = 300,
    include_all: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cv = latest_cv(db, user.id)
    live_jobs = db.query(LiveJob).order_by(LiveJob.posted_at.desc().nullslast()).all()
    if include_all or not cv:
        records = [(job, match_details(cv, job) if cv else None) for job in live_jobs]
        if cv:
            records.sort(key=lambda row: row[1]["overall_score"], reverse=True)
    else:
        records = candidate_job_records(cv, live_jobs, user.target_roles)
    return [serialize_job(job, details) for job, details in records[: min(max(limit, 1), 500)]]


@app.post("/api/jobs/sync")
def sync_jobs(
    force: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = sync_current_jobs(db, force=force)
    ats_result = sync_configured_ats(db, user.id)
    return {
        **result,
        "ats_collectors": ats_result,
        "stored": db.query(LiveJob).count(),
        "message": "Public feeds and configured employer ATS collectors refreshed.",
        "synced_at": datetime.utcnow().isoformat(),
    }


@app.post("/api/jobs/import")
def import_job(
    payload: ManualJobImport,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source = payload.source.strip() or "Manual"
    source_id = "manual-" + secrets.token_hex(8)
    job = LiveJob(
        source=source,
        source_id=source_id,
        title=payload.title.strip(),
        company=payload.company.strip(),
        location=payload.location.strip() or "Germany",
        remote=payload.remote,
        url=payload.url.strip(),
        description=payload.description.strip(),
        skills=",".join(extract_skills(payload.title + " " + payload.description)),
        job_types="",
        match_score=None,
        posted_at=datetime.utcnow(),
        fetched_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    cv = latest_cv(db, user.id)
    details = match_details(cv, job) if cv else None
    return serialize_job(job, details)


@app.get("/api/jobs/{job_id}/match-report")
def job_match_report(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(LiveJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")

    cv = latest_cv(db, user.id)
    if not cv:
        raise HTTPException(400, "Upload your CV before calculating a match report.")

    return {
        "job": serialize_job(job, match_details(cv, job)),
        "match": match_details(cv, job),
        "cv": {
            "id": cv.id,
            "filename": cv.filename,
        },
    }


@app.post("/api/jobs/{job_id}/cover-letter")
async def create_cover_letter_payload(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(LiveJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")

    cv = latest_cv(db, user.id)
    if not cv:
        raise HTTPException(400, "Upload your CV before generating a cover letter.")

    details = match_details(cv, job)
    letter_text, generator_mode = await generate_cover_letter_text(cv.text, job, details, user)
    content = build_cover_letter_docx(letter_text, user, job)
    filename = safe_filename(
        f"{user.display_name}_{job.company}_{job.title}_Cover_Letter"
    ) + ".docx"

    return {
        "filename": filename,
        "generator": generator_mode,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


@app.post("/api/jobs/{job_id}/cover-letter.docx")
async def create_cover_letter(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(LiveJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")

    cv = latest_cv(db, user.id)
    if not cv:
        raise HTTPException(400, "Upload your CV before generating a cover letter.")

    details = match_details(cv, job)
    letter_text, generator_mode = await generate_cover_letter_text(cv.text, job, details, user)
    content = build_cover_letter_docx(letter_text, user, job)
    filename = safe_filename(
        f"{user.display_name}_{job.company}_{job.title}_Cover_Letter"
    ) + ".docx"

    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-JobIntel-Generator": generator_mode,
        },
    )


@app.post("/api/jobs/bulk-import")
def bulk_import_jobs(
    payload: BulkJobImport,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if len(payload.jobs) > 500:
        raise HTTPException(400, "A bulk import is limited to 500 jobs per request.")

    imported = 0
    updated = 0
    for row in payload.jobs:
        source = row.source.strip() or "External Collector"
        raw_key = "|".join([source, row.url.strip(), row.title.strip(), row.company.strip()])
        source_id = "external-" + hashlib.sha256(raw_key.encode()).hexdigest()[:24]
        existing = (
            db.query(LiveJob)
            .filter(LiveJob.source == source, LiveJob.source_id == source_id)
            .first()
        )
        values = {
            "title": row.title.strip(),
            "company": row.company.strip(),
            "location": row.location.strip() or "Germany",
            "remote": row.remote,
            "url": row.url.strip(),
            "description": row.description.strip(),
            "skills": ",".join(extract_skills(row.title + " " + row.description)),
            "job_types": "",
            "match_score": None,
            "posted_at": datetime.utcnow(),
            "fetched_at": datetime.utcnow(),
        }
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            updated += 1
        else:
            db.add(LiveJob(source=source, source_id=source_id, **values))
            imported += 1

    db.commit()
    return {
        "imported": imported,
        "updated": updated,
        "stored": db.query(LiveJob).count(),
        "message": "Collector output normalized into JobIntel.",
    }


@app.get("/api/collector-targets")
def collector_targets(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(CollectorTarget)
        .filter(CollectorTarget.user_id == user.id)
        .order_by(CollectorTarget.created_at.desc())
        .all()
    )
    return [
        {
            "id": row.id,
            "provider": row.provider,
            "identifier": row.identifier,
            "label": row.label,
            "enabled": row.enabled,
        }
        for row in rows
    ]


@app.post("/api/collector-targets")
def add_collector_target(
    payload: CollectorTargetCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    provider = payload.provider.strip().lower()
    supported = {"lever", "lever-eu", "smartrecruiters", "ashby"}
    if provider not in supported:
        raise HTTPException(
            400,
            "Supported providers: lever, lever-eu, smartrecruiters, ashby.",
        )

    identifier = payload.identifier.strip().strip("/")
    if provider == "ashby" and "jobs.ashbyhq.com/" in identifier:
        identifier = identifier.split("jobs.ashbyhq.com/", 1)[1].split("/", 1)[0]
    if not identifier:
        raise HTTPException(400, "Company/job-board identifier is required.")

    existing = (
        db.query(CollectorTarget)
        .filter(
            CollectorTarget.user_id == user.id,
            CollectorTarget.provider == provider,
            CollectorTarget.identifier == identifier,
        )
        .first()
    )
    if existing:
        existing.label = payload.label.strip() or identifier
        existing.enabled = payload.enabled
        db.commit()
        db.refresh(existing)
        row = existing
    else:
        row = CollectorTarget(
            user_id=user.id,
            provider=provider,
            identifier=identifier,
            label=payload.label.strip() or identifier,
            enabled=payload.enabled,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

    return {
        "id": row.id,
        "provider": row.provider,
        "identifier": row.identifier,
        "label": row.label,
        "enabled": row.enabled,
    }


@app.delete("/api/collector-targets/{target_id}")
def delete_collector_target(
    target_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(CollectorTarget)
        .filter(
            CollectorTarget.id == target_id,
            CollectorTarget.user_id == user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "Collector target not found.")

    source = PROVIDER_SOURCE.get(row.provider.lower())
    if source:
        prefix = row.identifier + ":"
        db.query(LiveJob).filter(
            LiveJob.source == source,
            LiveJob.source_id.like(prefix + "%"),
        ).delete(synchronize_session=False)

    db.delete(row)
    db.commit()
    return {"ok": True}


def serialize_application_package(item: ApplicationPackage) -> dict:
    try:
        payload = json.loads(item.package_json or "{}")
    except Exception:
        payload = {}

    return {
        "id": item.id,
        "user_id": item.user_id,
        "live_job_id": item.live_job_id,
        "cv_profile_id": item.cv_profile_id,
        "status": item.status,
        "match_score": item.match_score,
        "cover_letter_generator": item.cover_letter_generator,
        "package": payload,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


@app.post("/api/jobs/{job_id}/prepare-application")
async def prepare_application(
    job_id: int,
    payload: ApplicationPreparationRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(LiveJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")

    cv = latest_cv(db, user.id)
    if not cv:
        raise HTTPException(400, "Upload your CV before preparing an application.")

    report = match_details(cv, job)
    letter_text, generator_mode = await generate_cover_letter_text(
        cv.text,
        job,
        report,
        user,
    )
    package_payload = build_application_package_payload(
        job=job,
        cv=cv,
        user=user,
        match_report=report,
        cover_letter_text=letter_text,
        cover_letter_generator=generator_mode,
        minimum_match=payload.minimum_match,
    )

    item = (
        db.query(ApplicationPackage)
        .filter(
            ApplicationPackage.user_id == user.id,
            ApplicationPackage.live_job_id == job.id,
            ApplicationPackage.cv_profile_id == cv.id,
        )
        .first()
    )
    if item is None:
        item = ApplicationPackage(
            user_id=user.id,
            live_job_id=job.id,
            cv_profile_id=cv.id,
        )
        db.add(item)

    item.status = package_payload["status"]
    item.match_score = report["overall_score"]
    item.cover_letter_text = letter_text
    item.cover_letter_generator = generator_mode
    item.package_json = json.dumps(package_payload)
    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)

    return serialize_application_package(item)


@app.get("/api/application-packages")
def application_packages(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ApplicationPackage)
        .filter(ApplicationPackage.user_id == user.id)
        .order_by(ApplicationPackage.updated_at.desc())
        .all()
    )
    return [serialize_application_package(row) for row in rows]


@app.get("/api/application-packages/{package_id}")
def application_package(
    package_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(ApplicationPackage)
        .filter(
            ApplicationPackage.id == package_id,
            ApplicationPackage.user_id == user.id,
        )
        .first()
    )
    if not item:
        raise HTTPException(404, "Application package not found.")
    return serialize_application_package(item)


@app.patch("/api/application-packages/{package_id}/answers")
def update_application_package_answers(
    package_id: int,
    payload: ApplicationPackageAnswerUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(ApplicationPackage)
        .filter(
            ApplicationPackage.id == package_id,
            ApplicationPackage.user_id == user.id,
        )
        .first()
    )
    if not item:
        raise HTTPException(404, "Application package not found.")

    package = json.loads(item.package_json or "{}")
    rows = package.get("screening_answers", [])
    for row in rows:
        key = row.get("key")
        if key in payload.answers:
            value = (payload.answers[key] or "").strip()
            row["answer"] = value
            row["status"] = "complete" if value else "needs_user_input"

    package["unresolved_fields"] = [
        row.get("key")
        for row in rows
        if row.get("status") == "needs_user_input"
    ]
    validation_ok = bool((package.get("validation") or {}).get("passed"))
    item.status = (
        "Package Ready"
        if validation_ok and not package["unresolved_fields"]
        else "Needs Review"
    )
    package["status"] = item.status
    item.package_json = json.dumps(package)
    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return serialize_application_package(item)


@app.post("/api/application-packages/{package_id}/cover-letter")
def application_package_cover_letter(
    package_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(ApplicationPackage)
        .filter(
            ApplicationPackage.id == package_id,
            ApplicationPackage.user_id == user.id,
        )
        .first()
    )
    if not item:
        raise HTTPException(404, "Application package not found.")

    job = db.get(LiveJob, item.live_job_id)
    if not job:
        raise HTTPException(404, "Prepared job no longer exists.")

    content = build_cover_letter_docx(item.cover_letter_text, user, job)
    filename = safe_filename(
        f"{user.display_name}_{job.company}_{job.title}_Prepared_Cover_Letter"
    ) + ".docx"
    return {
        "filename": filename,
        "generator": item.cover_letter_generator,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


@app.get("/api/applications", response_model=list[ApplicationOut])
def applications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(Application)
        .filter(Application.user_id == user.id)
        .order_by(Application.created_at.desc())
        .all()
    )


@app.post("/api/applications", response_model=ApplicationOut)
def add_application(
    payload: ApplicationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = Application(user_id=user.id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.patch("/api/applications/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: int,
    payload: ApplicationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == user.id)
        .first()
    )
    if not item:
        raise HTTPException(404, "Application not found.")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/cv")
def get_cv(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cv = latest_cv(db, user.id)
    if not cv:
        return {"uploaded": False}

    details = refresh_cv_analysis(db, cv)
    relevant = candidate_job_records(cv, db.query(LiveJob).all(), user.target_roles)
    top_skills = rank_cv_skills(cv.text, [job.skills for job, _ in relevant], limit=12)
    return {
        "uploaded": True,
        "id": cv.id,
        "filename": cv.filename,
        "uploaded_at": cv.uploaded_at.isoformat(),
        "skills": [s for s in cv.skills.split(",") if s],
        "top_skills": top_skills,
        "role_families": profile_role_families(cv.text),
        "ats": details,
    }


@app.post("/api/cv/upload")
async def upload_cv(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(400, "CV file is too large. Maximum size is 8 MB.")

    text = extract_document_text(file.filename or "cv.pdf", raw)
    if len(text.split()) < 80:
        raise HTTPException(400, "Not enough readable CV text was extracted from the file.")

    result = ats_check(text)
    profile = CVProfile(
        user_id=user.id,
        filename=file.filename or "cv",
        text=text,
        skills=",".join(result["skills_detected"]),
        ats_score=result["score"],
        ats_status=result["status"],
        ats_json=json.dumps(result),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    rescored = rescore_jobs(db, profile)
    return {
        "uploaded": True,
        "filename": profile.filename,
        "ats": result,
        "jobs_rescored": rescored,
        "message": "CV saved locally. Current jobs will be filtered and scored against this profile.",
    }


@app.post("/api/match")
def match(payload: MatchRequest, user: User = Depends(get_current_user)):
    return match_cv_to_job(payload.cv_text, payload.job_description)


@app.get("/api/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    all_jobs = db.query(LiveJob).order_by(LiveJob.posted_at.desc().nullslast()).all()
    apps = (
        db.query(Application)
        .filter(Application.user_id == user.id)
        .order_by(Application.created_at.desc())
        .all()
    )
    cv = latest_cv(db, user.id)

    statuses = ["Saved", "Applied", "Screening", "Interview", "Final", "Offer", "Rejected"]
    counts = {status: sum(1 for app in apps if app.status == status) for status in statuses}
    interview_count = counts["Interview"] + counts["Final"] + counts["Offer"]

    records = candidate_job_records(cv, all_jobs, user.target_roles)
    relevant_jobs = [job for job, _ in records]
    today = date.today()
    new_today = sum(1 for job in relevant_jobs if job.posted_at and job.posted_at.date() == today)

    if cv:
        ats = refresh_cv_analysis(db, cv)
        top_skills = rank_cv_skills(cv.text, [job.skills for job in relevant_jobs], limit=10)
        matches = [serialize_job(job, details) for job, details in records[:5]]
        top_scores = [details["overall_score"] for _, details in records[:5]]
        readiness_score = round(sum(top_scores) / len(top_scores)) if top_scores else 0
        readiness_level = "Strong" if readiness_score >= 80 else "Good" if readiness_score >= 65 else "Developing"
        role_families = profile_role_families(cv.text)
    else:
        ats = None
        top_skills = []
        matches = [serialize_job(job) for job in all_jobs[:5]]
        readiness_score = 0
        readiness_level = "Upload CV"
        role_families = []

    last_sync = max((job.fetched_at for job in all_jobs if job.fetched_at), default=None)
    all_source_counts = Counter(job.source for job in all_jobs)
    relevant_source_counts = Counter(job.source for job in relevant_jobs)
    gaps = build_skill_gap(cv, relevant_jobs)
    performance = application_performance(apps)
    conversion = application_conversion_insights(apps)

    followups = []
    for row in apps:
        if row.status in {"Applied", "Screening", "Interview"}:
            days = (today - row.applied_date).days
            if days >= 5:
                followups.append({
                    "company": row.company,
                    "role": row.role,
                    "status": row.status,
                    "days": days,
                })

    suggestions = []
    if not cv:
        suggestions.append({
            "title": "Upload your CV",
            "detail": "JobIntel needs your CV before it can rank skills and filter jobs to your profile.",
        })
    else:
        for gap in gaps[:3]:
            suggestions.append({
                "title": f"Improve {gap['skill']}",
                "detail": f"Seen in {gap.get('market_count', 0)} CV-relevant jobs. {gap['action']}",
            })
        if not suggestions:
            suggestions.append({
                "title": "Your current overlap is strong",
                "detail": "Focus on tailoring project evidence and keywords to each high-match vacancy.",
            })

    return {
        "summary": {
            "active_jobs": len(relevant_jobs) if cv else len(all_jobs),
            "total_market_jobs": len(all_jobs),
            "new_today": new_today,
            "applications": len(apps),
            "interviews": interview_count,
            "offers": counts["Offer"],
            "ats_score": ats["score"] if ats else None,
        },
        "market": {
            "last_sync": last_sync.isoformat() if last_sync else None,
            "sources": dict(relevant_source_counts if cv else all_source_counts),
            "all_sources": dict(all_source_counts),
            "source_analytics": build_source_analytics(
                db,
                user.id,
                all_jobs,
                relevant_jobs if cv else all_jobs,
            ),
            "live": bool(all_jobs),
            "total_jobs": len(all_jobs),
            "relevant_jobs": len(relevant_jobs) if cv else len(all_jobs),
        },
        "profile": {
            "top_skills": top_skills,
            "role_families": role_families,
            "user": user_payload(user),
        },
        "cv": {
            "uploaded": bool(cv),
            "filename": cv.filename if cv else None,
            "uploaded_at": cv.uploaded_at.isoformat() if cv else None,
            "ats": ats,
        },
        "matches": matches,
        "top_skills": top_skills if cv else aggregate_skills([job.skills for job in all_jobs]),
        "pipeline": counts,
        "performance": performance,
        "conversion": conversion,
        "skill_gap": gaps,
        "interview_readiness": {"score": readiness_score, "level": readiness_level},
        "followups": followups[:5],
        "ai_suggestions": suggestions[:4],
    }


@app.get("/api/assistant/status")
async def get_assistant_status(user: User = Depends(get_current_user)):
    return await assistant_status()


@app.post("/api/assistant")
async def assistant(
    payload: AssistantRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cv = latest_cv(db, user.id)
    all_jobs = db.query(LiveJob).all()
    records = candidate_job_records(cv, all_jobs, user.target_roles)
    relevant_jobs = [job for job, _ in records]
    apps = db.query(Application).filter(Application.user_id == user.id).all()

    context = {
        "user": user_payload(user),
        "cv_uploaded": bool(cv),
        "applications": len(apps),
        "application_statuses": dict(Counter(app.status for app in apps)),
        "tracked_live_jobs": len(relevant_jobs) if cv else len(all_jobs),
        "top_profile_skills": [item["skill"] for item in rank_cv_skills(cv.text, limit=10)] if cv else [],
        "top_matches": [
            {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "match": details["overall_score"],
                "matched_skills": details["matched_skills"][:8],
                "missing_skills": details["missing_skills"][:8],
            }
            for job, details in records[:8] if details
        ],
        "top_missing_skills": [gap["skill"] for gap in build_skill_gap(cv, relevant_jobs)],
    }
    return await answer(payload.message, context)
