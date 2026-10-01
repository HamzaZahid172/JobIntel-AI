import json
import logging
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from io import BytesIO

from docx import Document
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader
from sqlalchemy.orm import Session

from .assistant import answer
from .db import Base, SessionLocal, engine, get_db, wait_for_database
from .intelligence import (
    aggregate_skills,
    ats_check,
    extract_skills,
    improvement_suggestions,
    match_cv_to_job,
)
from .models import Application, CVProfile, Job, LiveJob
from .schemas import (
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    AssistantRequest,
    MatchRequest,
)
from .sources import latest_cv, rescore_jobs, sync_current_jobs

logger = logging.getLogger("jobintel")


def cleanup_legacy_demo_data(db: Session) -> None:
    """Remove only the exact starter demo rows from early JobIntel builds."""
    apps = db.query(Application).all()
    demo_companies = {"SAP", "Bosch", "Example GmbH"}
    if apps and len(apps) <= 3 and {a.company for a in apps}.issubset(demo_companies):
        for app in apps:
            db.delete(app)
    # The legacy jobs table is no longer used by the dashboard.
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


def serialize_job(job: LiveJob) -> dict:
    return {
        "id": job.id,
        "source": job.source,
        "source_id": job.source_id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "remote": job.remote,
        "url": job.url,
        "skills": [s for s in job.skills.split(",") if s],
        "job_types": [s for s in job.job_types.split(",") if s],
        "match": job.match_score,
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        "fetched_at": job.fetched_at.isoformat() if job.fetched_at else None,
    }


def build_skill_gap(cv: CVProfile | None, jobs: list[LiveJob]) -> list[dict]:
    if not cv:
        return []
    cv_skills = set(extract_skills(cv.text))
    missing = Counter()
    for job in jobs[:60]:
        for skill in [s for s in job.skills.split(",") if s]:
            if skill not in cv_skills:
                missing[skill] += 1
    suggestions = improvement_suggestions([s for s, _ in missing.most_common(8)])
    for suggestion in suggestions:
        key = suggestion["skill"].lower()
        suggestion["market_count"] = missing.get(key, 0)
    return suggestions[:4]


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
    return sorted(result, key=lambda x: (x["value"], x["applications"]), reverse=True)[:4]


@asynccontextmanager
async def lifespan(app: FastAPI):
    wait_for_database()
    Base.metadata.create_all(bind=engine)
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


app = FastAPI(title="JobIntel AI API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0"}


@app.get("/api/jobs")
def jobs(limit: int = 100, db: Session = Depends(get_db)):
    cv = latest_cv(db)
    query = db.query(LiveJob)
    if cv:
        query = query.order_by(LiveJob.match_score.desc().nullslast(), LiveJob.posted_at.desc().nullslast())
    else:
        query = query.order_by(LiveJob.posted_at.desc().nullslast())
    return [serialize_job(job) for job in query.limit(min(max(limit, 1), 300)).all()]


@app.post("/api/jobs/sync")
def sync_jobs(db: Session = Depends(get_db)):
    result = sync_current_jobs(db)
    return {
        **result,
        "message": "Current job feeds refreshed and stored in PostgreSQL.",
        "synced_at": datetime.utcnow().isoformat(),
    }


@app.get("/api/applications", response_model=list[ApplicationOut])
def applications(db: Session = Depends(get_db)):
    return db.query(Application).order_by(Application.created_at.desc()).all()


@app.post("/api/applications", response_model=ApplicationOut)
def add_application(payload: ApplicationCreate, db: Session = Depends(get_db)):
    item = Application(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.patch("/api/applications/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: int,
    payload: ApplicationUpdate,
    db: Session = Depends(get_db),
):
    item = db.get(Application, application_id)
    if not item:
        raise HTTPException(404, "Application not found")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/cv")
def get_cv(db: Session = Depends(get_db)):
    cv = latest_cv(db)
    if not cv:
        return {"uploaded": False}
    details = json.loads(cv.ats_json or "{}")
    return {
        "uploaded": True,
        "id": cv.id,
        "filename": cv.filename,
        "uploaded_at": cv.uploaded_at.isoformat(),
        "skills": [s for s in cv.skills.split(",") if s],
        "ats": details,
    }


@app.post("/api/cv/upload")
async def upload_cv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    raw = await file.read()
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(400, "CV file is too large. Maximum size is 8 MB.")

    text = extract_document_text(file.filename or "cv.pdf", raw)
    if len(text.split()) < 80:
        raise HTTPException(400, "Not enough readable CV text was extracted from the file.")

    result = ats_check(text)
    profile = CVProfile(
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
        "message": "CV saved locally and all current jobs were rescored.",
    }


@app.post("/api/cv/ats")
async def cv_ats(file: UploadFile = File(...)):
    raw = await file.read()
    text = extract_document_text(file.filename or "cv.pdf", raw)
    return ats_check(text)


@app.post("/api/match")
def match(payload: MatchRequest):
    return match_cv_to_job(payload.cv_text, payload.job_description)


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    live_jobs = (
        db.query(LiveJob)
        .order_by(LiveJob.match_score.desc().nullslast(), LiveJob.posted_at.desc().nullslast())
        .all()
    )
    apps = db.query(Application).order_by(Application.created_at.desc()).all()
    cv = latest_cv(db)

    statuses = ["Saved", "Applied", "Screening", "Interview", "Final", "Offer", "Rejected"]
    counts = {status: sum(1 for app in apps if app.status == status) for status in statuses}
    interview_count = counts["Interview"] + counts["Final"] + counts["Offer"]

    today = date.today()
    new_today = sum(1 for job in live_jobs if job.posted_at and job.posted_at.date() == today)
    top_skills = aggregate_skills([job.skills for job in live_jobs])

    if cv:
        matches = [serialize_job(job) for job in live_jobs if job.match_score is not None][:5]
        ats = json.loads(cv.ats_json or "{}")
        readiness_score = round(sum((j.match_score or 0) for j in live_jobs[:5]) / max(1, min(5, len(live_jobs))))
        readiness_level = "High" if readiness_score >= 80 else "Medium" if readiness_score >= 65 else "Developing"
    else:
        matches = [serialize_job(job) for job in live_jobs[:5]]
        ats = None
        readiness_score = 0
        readiness_level = "Upload CV"

    last_sync = max((job.fetched_at for job in live_jobs if job.fetched_at), default=None)
    source_counts = Counter(job.source for job in live_jobs)
    gaps = build_skill_gap(cv, live_jobs)
    performance = application_performance(apps)

    followups = []
    for app_row in apps:
        if app_row.status in {"Applied", "Screening", "Interview"}:
            days = (today - app_row.applied_date).days
            if days >= 5:
                followups.append({
                    "company": app_row.company,
                    "role": app_row.role,
                    "status": app_row.status,
                    "days": days,
                })

    suggestions = []
    if not cv:
        suggestions.append({
            "title": "Upload your CV",
            "detail": "JobIntel needs your CV before it can calculate real ATS readiness and job-match scores.",
        })
    else:
        for gap in gaps[:3]:
            suggestions.append({
                "title": f"Improve {gap['skill']}",
                "detail": f"Seen in {gap.get('market_count', 0)} current tracked roles. {gap['action']}",
            })
        if not suggestions:
            suggestions.append({
                "title": "Your tracked market gaps are small",
                "detail": "Focus on tailoring your strongest project evidence to the highest-match roles.",
            })

    return {
        "summary": {
            "active_jobs": len(live_jobs),
            "new_today": new_today,
            "applications": len(apps),
            "interviews": interview_count,
            "offers": counts["Offer"],
            "ats_score": ats["score"] if ats else None,
        },
        "market": {
            "last_sync": last_sync.isoformat() if last_sync else None,
            "sources": dict(source_counts),
            "live": bool(live_jobs),
        },
        "cv": {
            "uploaded": bool(cv),
            "filename": cv.filename if cv else None,
            "uploaded_at": cv.uploaded_at.isoformat() if cv else None,
            "ats": ats,
        },
        "matches": matches,
        "top_skills": top_skills,
        "pipeline": counts,
        "performance": performance,
        "skill_gap": gaps,
        "interview_readiness": {"score": readiness_score, "level": readiness_level},
        "followups": followups[:5],
        "ai_suggestions": suggestions[:4],
    }


@app.post("/api/assistant")
async def assistant(payload: AssistantRequest, db: Session = Depends(get_db)):
    cv = latest_cv(db)
    jobs = db.query(LiveJob).order_by(LiveJob.match_score.desc().nullslast()).limit(20).all()
    context = {
        "cv_uploaded": bool(cv),
        "applications": db.query(Application).count(),
        "tracked_live_jobs": db.query(LiveJob).count(),
        "top_matches": [
            {"title": j.title, "company": j.company, "match": j.match_score}
            for j in jobs[:5]
        ],
        "top_missing_skills": [g["skill"] for g in build_skill_gap(cv, jobs)],
    }
    return {"answer": await answer(payload.message, context)}
