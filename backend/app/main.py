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
from pypdf import PdfReader
from sqlalchemy.orm import Session

from .assistant import answer, assistant_status
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
from .models import Application, CVProfile, Job, LiveJob, User
from .schemas import (
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    AssistantRequest,
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
    return match_cv_to_job(cv.text, job.description, job.title)


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
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        "fetched_at": job.fetched_at.isoformat() if job.fetched_at else None,
    }


def candidate_job_records(cv: CVProfile | None, jobs: list[LiveJob]) -> list[tuple[LiveJob, dict | None]]:
    if not cv:
        return [(job, None) for job in jobs]

    strongest = {item["skill"] for item in rank_cv_skills(cv.text, limit=10)}
    records: list[tuple[LiveJob, dict]] = []
    for job in jobs:
        details = match_details(cv, job)
        job_skills = set(details["job_skills"])
        strong_overlap = strongest & job_skills
        if details["role_score"] < 45:
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
    cv_skills = set(extract_skills(cv.text))
    missing = Counter()
    for job in jobs[:100]:
        for skill in [s for s in job.skills.split(",") if s]:
            if skill not in cv_skills:
                missing[skill] += 1

    suggestions = improvement_suggestions([s for s, _ in missing.most_common(12)])
    for suggestion in suggestions:
        key = suggestion["skill"].lower()
        suggestion["market_count"] = missing.get(key, 0)
    return suggestions[:6]


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


app = FastAPI(title="JobIntel AI API", version="0.5.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.5.0"}


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
            {"name": "Manual Import", "mode": "URL + description", "status": "active"},
        ],
        "planned": [
            {"name": "Direct employer ATS", "mode": "Greenhouse / Lever / SmartRecruiters / Teamtailor", "status": "planned"},
            {"name": "XING", "mode": "Authorized integration only", "status": "restricted"},
            {"name": "StepStone", "mode": "Authorized integration only", "status": "restricted"},
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
        records = candidate_job_records(cv, live_jobs)
    return [serialize_job(job, details) for job, details in records[: min(max(limit, 1), 500)]]


@app.post("/api/jobs/sync")
def sync_jobs(
    force: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = sync_current_jobs(db, force=force)
    return {
        **result,
        "message": "Current public job feeds refreshed and stored in PostgreSQL.",
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
    relevant = candidate_job_records(cv, db.query(LiveJob).all())
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

    records = candidate_job_records(cv, all_jobs)
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
    records = candidate_job_records(cv, all_jobs)
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
