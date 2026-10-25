import base64
import hashlib
import json
import logging
import os
import re
import secrets
from email.utils import parseaddr

import httpx
from collections import Counter
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from io import BytesIO

from docx import Document
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pypdf import PdfReader
from sqlalchemy.orm import Session

from .assistant import answer, assistant_status
from .google_login import begin_google_login, complete_google_oauth, exchange_ticket, popup_result_page, configured as google_login_configured
from .interview_practice import question_bank, answer_feedback
from .conversion_analytics import application_analytics
from .ats_simulator import ats_review as evaluate_cv_ats
from .application_preparation import build_application_package_payload
from .followup_contacts import discover_contact
from .job_acquisition import (
    cv_tailoring_draft,
    followup_draft,
    followup_due,
    opportunity_assessment,
)
from .ats_collectors import PROVIDER_SOURCE, sync_configured_ats
from .cover_letter import build_cover_letter_docx, generate_cover_letter_text, safe_filename
from .document_vault import store_document, read_document, public_document, choose_document
from .pre_application_review import job_role_family, pre_application_review
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
from .rejection_insights import rejection_review
from .gmail_sync import GMAIL_API, _message_body_text, ensure_access_token, classify_message, _gmail_headers, rejection_evidence
from .gmail_worker import start_gmail_worker
from .gmail_sync import (
    build_authorization_url,
    create_oauth_state,
    exchange_code,
    gmail_configured,
    gmail_can_send,
    validate_gmail_send_upgrade,
    gmail_send_approved,
    gmail_profile,
    serialize_event,
    sync_gmail,
    sync_application_gmail,
    sync_active_applications_gmail,
)
from .models import (
    Application,
    ApplicationPackage,
    InterviewPractice,
    CVProfile,
    CandidateDocument,
    CandidateProfile,
    CollectorTarget,
    GmailConnection,
    GmailEvent,
    GmailOAuthState,
    GoogleLoginIdentity,
    Job,
    LiveJob,
    User,
)
from .schemas import (
    ApplicationCreate,
    ApplicationOut,
    CandidateProfileUpdate,
    CoverLetterDraft,
    GoogleLoginExchange,
    ApprovedFollowupSend,
    ApplicationPackageAnswerUpdate,
    ApplicationPreparationRequest,
    InterviewAnswer,
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
from .sources import canonical_job_url, latest_cv, rescore_jobs, sync_current_jobs

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
        "opportunity": opportunity_assessment(job, details) if details else None,
        "recommended_cv_family": job_role_family(job.title),
        "cv_used_filename": details.get("cv_used_filename") if details else None,
        "cv_used_id": details.get("cv_used_id") if details else None,
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


def _deduplicate_candidate_jobs(jobs: list[LiveJob]) -> list[LiveJob]:
    """Hide cross-feed URL duplicates without deleting source records."""
    result = {}
    for job in jobs:
        url_key = canonical_job_url(job.url or "")
        key = ("url", url_key) if url_key else ("source", job.source, job.source_id)
        previous = result.get(key)
        if previous is None or (job.posted_at or datetime.min) > (previous.posted_at or datetime.min):
            result[key] = job
    return list(result.values())


def candidate_job_records(
    cv: CVProfile | None,
    jobs: list[LiveJob],
    target_roles: str = "",
    cv_tracks: dict[str, CVProfile] | None = None,
) -> list[tuple[LiveJob, dict | None]]:
    jobs = _deduplicate_candidate_jobs(jobs)
    if not cv:
        return [(job, None) for job in jobs]

    target_families = _target_role_families(target_roles)
    records: list[tuple[LiveJob, dict]] = []
    skills_cache = {}
    for job in jobs:
        selected_cv = (cv_tracks or {}).get(job_role_family(job.title), cv)
        if selected_cv.id not in skills_cache:
            skills_cache[selected_cv.id] = {
                item["skill"] for item in rank_cv_skills(selected_cv.text, limit=10)
            }
        details = match_details(selected_cv, job)
        details["cv_used_id"] = selected_cv.id
        details["cv_used_filename"] = selected_cv.filename
        job_skills = set(details["job_skills"])
        job_families = set(details["job_role_families"])
        strong_overlap = skills_cache[selected_cv.id] & job_skills
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
        ("Remotive", "Public API (remote; links attributed)", True),
        ("Ashby", "Employer ATS", False),
        ("Lever", "Employer ATS", False),
        ("SmartRecruiters", "Employer ATS", False),
        ("Greenhouse", "Employer ATS", False),
        ("Personio", "Employer ATS", False),
        ("Workable", "Employer ATS", False),
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
    gmail_stop, gmail_thread = start_gmail_worker()
    try:
        yield
    finally:
        gmail_stop.set()
        gmail_thread.join(timeout=3)


app = FastAPI(title="JobIntel AI API", version="0.7.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("JOBINTEL_ALLOWED_ORIGINS", "http://localhost:3100,http://127.0.0.1:3100").split(",") if origin.strip()],
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


@app.get("/api/auth/google/status")
def google_signin_status(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    identity=db.query(GoogleLoginIdentity).filter(
        GoogleLoginIdentity.user_id==user.id
    ).first()
    return {"configured":google_login_configured(),"linked":bool(identity),
            "google_email":identity.google_email if identity else None}


@app.post("/api/auth/google/start")
def google_signin_start(db: Session = Depends(get_db)):
    return {"authorization_url":begin_google_login(db)}


@app.post("/api/auth/google/link")
def google_signin_link(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return {"authorization_url":begin_google_login(db,link_user_id=user.id)}


@app.get("/api/auth/google/callback", response_class=HTMLResponse)
def google_signin_callback(
    state: str | None = None, code: str | None = None,
    error: str | None = None, db: Session = Depends(get_db)
):
    if error or not code or not state:
        return popup_result_page({"error":"Google Sign-In was cancelled or missing authorization."})
    try:
        return popup_result_page(complete_google_oauth(db,state,code))
    except HTTPException as exc:
        return popup_result_page({"error":str(exc.detail)})
    except Exception:
        logger.exception("Google Sign-In callback failed")
        return popup_result_page({"error":"Google Sign-In failed. Please try again."})


@app.post("/api/auth/google/exchange")
def google_signin_exchange(
    payload: GoogleLoginExchange, db: Session = Depends(get_db)
):
    user=exchange_ticket(db,payload.ticket)
    token=create_session(db,user)
    return {"token":token,"user":user_payload(user)}


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


@app.get("/api/gmail/status")
def gmail_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = (
        db.query(GmailConnection)
        .filter(GmailConnection.user_id == user.id)
        .first()
    )
    return {
        "configured": gmail_configured(),
        "connected": bool(connection),
        "google_email": connection.google_email if connection else None,
        "last_synced_at": (
            connection.last_synced_at.isoformat()
            if connection and connection.last_synced_at
            else None
        ),
        "scope": connection.scope if connection else None,
        "can_send": gmail_can_send(connection),
    }


@app.post("/api/gmail/connect")
def gmail_connect(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not gmail_configured():
        raise HTTPException(
            503,
            "Gmail OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )
    state = create_oauth_state(db, user.id)
    return {"authorization_url": build_authorization_url(state.state)}


@app.post("/api/gmail/enable-send")
def gmail_enable_send(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not gmail_configured():
        raise HTTPException(503, "Gmail OAuth is not configured.")
    connection = db.query(GmailConnection).filter(GmailConnection.user_id == user.id).first()
    if not connection:
        raise HTTPException(400, "Connect Gmail read-only first.")
    state = create_oauth_state(db, user.id, allow_send=True)
    return {"authorization_url": build_authorization_url(state.state, allow_send=True)}


@app.get("/api/gmail/callback", response_class=HTMLResponse)
def gmail_callback(
    code: str,
    state: str,
    db: Session = Depends(get_db),
):
    oauth_state = (
        db.query(GmailOAuthState)
        .filter(
            GmailOAuthState.state == state,
            GmailOAuthState.expires_at > datetime.utcnow(),
        )
        .first()
    )
    if not oauth_state:
        raise HTTPException(400, "Gmail connection request expired. Start again from Settings.")

    try:
        token = exchange_code(code)
        access_token = token["access_token"]
        profile = gmail_profile(access_token)
    except Exception as exc:
        logger.exception("Gmail OAuth callback failed.")
        raise HTTPException(502, "Google authorization could not be completed.") from exc

    connection = (
        db.query(GmailConnection)
        .filter(GmailConnection.user_id == oauth_state.user_id)
        .first()
    )
    if oauth_state.state.startswith("send_"):
        if not connection:
            raise HTTPException(400, "Connect Gmail read-only before enabling Send.")
        try:
            validate_gmail_send_upgrade(
                connection.google_email,
                profile.get("emailAddress", ""),
                token.get("scope", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    if not connection:
        connection = GmailConnection(
            user_id=oauth_state.user_id,
            access_token=access_token,
        )
        db.add(connection)

    connection.access_token = access_token
    if token.get("refresh_token"):
        connection.refresh_token = token["refresh_token"]
    connection.token_expires_at = datetime.utcnow() + timedelta(
        seconds=max(int(token.get("expires_in", 3600)) - 60, 60)
    )
    connection.scope = token.get("scope", connection.scope)
    connection.google_email = profile.get("emailAddress", "")
    connection.connected_at = datetime.utcnow()

    db.delete(oauth_state)
    db.commit()

    return HTMLResponse(
        "<html><body style='font-family:system-ui;padding:40px'>"
        "<h2>Gmail connected to JobIntel AI</h2>"
        "<p>You can close this tab and return to JobIntel Settings.</p>"
        "</body></html>"
    )


def gmail_sync_failure(exc: httpx.HTTPError) -> HTTPException:
    """Give actionable, privacy-safe OAuth failures instead of a generic 502."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return HTTPException(
                409,
                "Gmail access was denied or expired. In Settings, reconnect Gmail "
                "with read-only permission, then retry the check.",
            )
        if code == 429:
            return HTTPException(
                503, "Gmail rate limit reached. Try the check again shortly."
            )
    return HTTPException(
        502, "Gmail could not be reached. Check your network and Gmail connection in Settings."
    )


@app.post("/api/gmail/sync")
def gmail_sync_now(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return sync_gmail(db, user.id)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.exception("Gmail sync failed.")
        raise gmail_sync_failure(exc) from exc


@app.post("/api/gmail/sync-applications")
def gmail_sync_applications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Targeted Gmail refresh when the My Applications page is opened/refreshed."""
    try:
        return sync_active_applications_gmail(db, user.id)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.exception("Gmail application refresh failed for user %s", user.id)
        raise gmail_sync_failure(exc) from exc


@app.post("/api/applications/{application_id}/sync-gmail-status")
def sync_application_status_now(
    application_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app_item = db.query(Application).filter(
        Application.id == application_id,
        Application.user_id == user.id,
    ).first()
    if app_item is None:
        raise HTTPException(404, "Application not found.")
    try:
        result = sync_application_gmail(db, user.id, application_id)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (httpx.HTTPError, ValueError) as exc:
        logger.exception("Application-specific Gmail check failed for user %s", user.id)
        raise gmail_sync_failure(exc) from exc
    db.refresh(app_item)
    return {
        **result,
        "application_id": app_item.id,
        "company": app_item.company,
        "status": app_item.status,
        "message": (
            "Rejection detected and application archived from the active list."
            if app_item.status == "Rejected"
            else "No confirmed rejection matched this application in the connected Gmail account."
        ),
    }


@app.get("/api/gmail/events")
def gmail_events(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(GmailEvent)
        .filter(GmailEvent.user_id == user.id)
        .order_by(GmailEvent.received_at.desc().nullslast(), GmailEvent.created_at.desc())
        .limit(min(max(limit, 1), 200))
        .all()
    )
    return [serialize_event(row) for row in rows]


@app.delete("/api/gmail/disconnect")
def gmail_disconnect(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(GmailConnection).filter(GmailConnection.user_id == user.id).delete()
    db.query(GmailOAuthState).filter(GmailOAuthState.user_id == user.id).delete()
    db.commit()
    return {"ok": True}


@app.get("/api/sources")
def sources(user: User = Depends(get_current_user)):
    return {
        "active": [
            {"name": "Arbeitnow", "mode": "Public API", "status": "active"},
            {"name": "Jobicy", "mode": "Public API", "status": "active"},
            {"name": "Remotive", "mode": "Public API; links to source", "status": "active"},
            {"name": "Lever", "mode": "Public employer postings", "status": "configurable"},
            {"name": "SmartRecruiters", "mode": "Public employer postings", "status": "configurable"},
            {"name": "Ashby", "mode": "Public Job Postings API", "status": "configurable"},
            {"name": "Greenhouse", "mode": "Public Job Board API", "status": "configurable"},
            {"name": "Personio", "mode": "Public company XML feed", "status": "configurable"},
            {"name": "Workable", "mode": "Public company Jobs API", "status": "configurable"},
            {"name": "Manual / Bulk Import", "mode": "Normalized external jobs", "status": "active"},
        ],
        "planned": [
            {"name": "Additional ATS adapters", "mode": "More official/public employer feeds", "status": "planned"},
            {"name": "Apply Queue", "mode": "Human-approved application automation", "status": "architecture-ready"},
            {"name": "XING", "mode": "Authorized integration or manual import only", "status": "restricted"},
            {"name": "StepStone", "mode": "Authorized integration or manual import only", "status": "restricted"},
        ],
    }


def cv_tracks_for_user(db: Session, user_id: int) -> dict[str, CVProfile]:
    """Resolve saved default CV profiles once per request, not once per job."""
    rows = db.query(CandidateDocument).filter(
        CandidateDocument.user_id == user_id,
        CandidateDocument.kind == "cv",
        CandidateDocument.role_family.in_(("qa", "backend", "data")),
    ).order_by(CandidateDocument.default_document.desc(),
               CandidateDocument.created_at.desc()).all()
    selected = {}
    for row in rows:
        if row.role_family not in selected and row.cv_profile_id:
            selected[row.role_family] = row.cv_profile_id
    if not selected:
        return {}
    profiles = db.query(CVProfile).filter(
        CVProfile.user_id == user_id,
        CVProfile.id.in_(list(selected.values())),
    ).all()
    by_id = {profile.id: profile for profile in profiles}
    return {family: by_id[cv_id] for family, cv_id in selected.items()
            if cv_id in by_id}


@app.get("/api/jobs")
def jobs(
    limit: int = 300,
    include_all: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cv = latest_cv(db, user.id)
    live_jobs = db.query(LiveJob).order_by(LiveJob.posted_at.desc().nullslast()).all()
    tracks = cv_tracks_for_user(db, user.id) if cv else {}
    if include_all or not cv:
        records = []
        for job in live_jobs:
            selected = tracks.get(job_role_family(job.title), cv)
            details = match_details(selected, job) if selected else None
            if details and selected:
                details["cv_used_id"] = selected.id
                details["cv_used_filename"] = selected.filename
            records.append((job, details))
    else:
        records = candidate_job_records(cv, live_jobs, user.target_roles, tracks)
    if cv:
        records.sort(
            key=lambda row: opportunity_assessment(row[0], row[1])["score"],
            reverse=True,
        )
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
        location=payload.location.strip() or "Location not verified",
        remote=payload.remote,
        url=payload.url.strip(),
        description=payload.description.strip(),
        skills=",".join(extract_skills(payload.title + " " + payload.description)),
        job_types="",
        match_score=None,
        posted_at=None,  # Import time is not the employer's posting date.
        fetched_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    cv, _, _ = resolve_job_cv(db, user.id, job)
    details = match_details(cv, job) if cv else None
    return serialize_job(job, details)


@app.get("/api/analytics/conversion")
def application_conversion_report(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    apps=db.query(Application).filter(Application.user_id == user.id).all()
    return application_analytics(apps)


@app.post("/api/jobs/{job_id}/interview-practice")
def start_interview_practice(
    job_id: int, user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    job=db.get(LiveJob,job_id)
    if job is None:
        raise HTTPException(404,"Job not found.")
    cv=latest_cv(db,user.id)
    if cv is None:
        raise HTTPException(400,"Upload a CV before starting interview practice.")
    questions=question_bank(job.title,job.description,cv.text)
    item=InterviewPractice(
        user_id=user.id,live_job_id=job.id,cv_profile_id=cv.id,
        questions_json=json.dumps(questions),answers_json="{}"
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id":item.id,"job_title":job.title,"company":job.company,
        "questions":questions,"answers":{},"created_at":item.created_at.isoformat(),
        "disclaimer":"Practice based on your selected job description and CV, not the employer's actual questions.",
    }


@app.get("/api/interview-practice")
def list_interview_practices(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    sessions=db.query(InterviewPractice).filter(
        InterviewPractice.user_id==user.id
    ).order_by(InterviewPractice.updated_at.desc()).limit(25).all()
    return [
        {"id":s.id,"job_id":s.live_job_id,
         "created_at":s.created_at.isoformat(),
         "questions_count":len(json.loads(s.questions_json or "[]")),
         "answers_count":len(json.loads(s.answers_json or "{}"))}
        for s in sessions
    ]


@app.get("/api/interview-practice/{practice_id}")
def get_interview_practice(
    practice_id: int,user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    session=db.query(InterviewPractice).filter(
        InterviewPractice.id==practice_id,
        InterviewPractice.user_id==user.id
    ).first()
    if session is None:
        raise HTTPException(404,"Interview practice session not found.")
    job=db.get(LiveJob,session.live_job_id)
    return {
        "id":session.id, "job_title":job.title if job else "Saved vacancy",
        "company":job.company if job else "Employer",
        "questions":json.loads(session.questions_json or "[]"),
        "answers":json.loads(session.answers_json or "{}"),
        "created_at":session.created_at.isoformat(),
    }


@app.post("/api/interview-practice/{practice_id}/answer")
def submit_interview_practice_answer(
    practice_id: int,payload: InterviewAnswer,
    user: User = Depends(get_current_user),db: Session = Depends(get_db)
):
    session=db.query(InterviewPractice).filter(
        InterviewPractice.id==practice_id,
        InterviewPractice.user_id==user.id
    ).first()
    if session is None:
        raise HTTPException(404,"Interview practice session not found.")
    questions=json.loads(session.questions_json or "[]")
    if payload.question_index<0 or payload.question_index>=len(questions):
        raise HTTPException(400,"Invalid question index.")
    cv=db.query(CVProfile).filter(
        CVProfile.id==session.cv_profile_id,CVProfile.user_id==user.id
    ).first()
    if cv is None:
        raise HTTPException(409,"Your saved CV version is no longer available.")
    try:
        feedback=answer_feedback(questions[payload.question_index],payload.answer,cv.text)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    answers=json.loads(session.answers_json or "{}")
    answers[str(payload.question_index)]={"answer":payload.answer,"feedback":feedback}
    session.answers_json=json.dumps(answers)
    session.updated_at=datetime.utcnow()
    db.commit()
    return {"question_index":payload.question_index,"feedback":feedback,
            "saved":True}


@app.get("/api/action-center")
def action_center(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cv = latest_cv(db, user.id)
    applications = (
        db.query(Application).filter(Application.user_id == user.id).all()
    )
    due = []
    for app in applications:
        if followup_due(app):
            draft = followup_draft(app, user.display_name)
            draft["recipient_lookup"] = discover_contact(db, user.id, app)
            due.append(draft)
    if not cv:
        return {"cv_uploaded": False, "opportunities": [], "followups": due,
                "apply_now": 0, "review": 0}

    jobs_all = db.query(LiveJob).all()
    tracked_urls = {app.url.rstrip("/").lower() for app in applications if app.url}
    tracked_pairs = {
        (app.company.lower().strip(), app.role.lower().strip())
        for app in applications
    }
    assessments = []
    cv_tracks = cv_tracks_for_user(db, user.id)
    for job in jobs_all:
        if job.url.rstrip("/").lower() in tracked_urls or (
            job.company.lower().strip(), job.title.lower().strip()
        ) in tracked_pairs:
            continue
        selected_cv = cv_tracks.get(job_role_family(job.title), cv)
        report = match_details(selected_cv, job)
        report["cv_used_id"] = selected_cv.id
        report["cv_used_filename"] = selected_cv.filename
        opportunity = opportunity_assessment(job, report)
        if opportunity["decision"] == "Skip":
            continue
        assessments.append({
            "job": serialize_job(job, report),
            "opportunity": opportunity,
        })
    assessments.sort(
        key=lambda item: (item["opportunity"]["score"], item["job"]["match"] or 0),
        reverse=True,
    )
    return {
        "cv_uploaded": True,
        "opportunities": assessments[:12],
        "followups": due,
        "apply_now": sum(1 for row in assessments if row["opportunity"]["decision"] == "Apply Now"),
        "review": sum(1 for row in assessments if row["opportunity"]["decision"] == "Review"),
        "disclaimer": "These are heuristics, not predicted hiring probabilities.",
    }


def resolve_job_cv(db: Session, user_id: int, job: LiveJob,
                   cv_id: int | None = None) -> tuple[CVProfile | None, str, bool]:
    """Use the saved job-family CV when no explicit CV version is requested."""
    role = job_role_family(job.title)
    chosen = choose_document(db, user_id, "cv", role)
    if cv_id is not None:
        cv = db.query(CVProfile).filter(
            CVProfile.id == cv_id, CVProfile.user_id == user_id
        ).first()
        saved = db.query(CandidateDocument).filter(
            CandidateDocument.user_id == user_id,
            CandidateDocument.kind == "cv",
            CandidateDocument.cv_profile_id == cv_id,
        ).order_by(CandidateDocument.default_document.desc()).first()
        return cv, saved.role_family if saved else "general", bool(saved)
    if chosen and chosen.cv_profile_id:
        cv = db.query(CVProfile).filter(
            CVProfile.id == chosen.cv_profile_id,
            CVProfile.user_id == user_id,
        ).first()
        if cv:
            return cv, chosen.role_family, True
    return latest_cv(db, user_id), "general", False


@app.get("/api/jobs/{job_id}/application-quality")
def application_quality(
    job_id: int, cv_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(LiveJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    cv, family, saved = resolve_job_cv(db, user.id, job, cv_id)
    if not cv:
        raise HTTPException(400, "Upload your CV before reviewing an application.")
    details = match_details(cv, job)
    return {
        "job_id": job.id, "cv_id": cv.id,
        "review": pre_application_review(job, cv, details,
                   selected_role=family, saved_cv=saved),
    }


@app.get("/api/cv/versions")
def cv_versions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profiles = (
        db.query(CVProfile)
        .filter(CVProfile.user_id == user.id)
        .order_by(CVProfile.uploaded_at.desc())
        .limit(30)
        .all()
    )
    ids = [row.id for row in profiles]
    documents = db.query(CandidateDocument).filter(
        CandidateDocument.user_id == user.id,
        CandidateDocument.kind == "cv",
        CandidateDocument.cv_profile_id.in_(ids),
    ).all() if ids else []
    families = {doc.cv_profile_id: doc.role_family for doc in documents}
    return [{"id": row.id, "filename": row.filename,
             "uploaded_at": row.uploaded_at.isoformat(),
             "role_family": families.get(row.id, "general"),
             "ats_score": row.ats_score} for row in profiles]


@app.get("/api/jobs/{job_id}/tailor-cv")
def tailor_cv(
    job_id: int,
    cv_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(LiveJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    cv, _, _ = resolve_job_cv(db, user.id, job, cv_id)
    if not cv:
        raise HTTPException(400, "Upload a CV or select one of your own CV versions.")
    report = match_details(cv, job)
    return {"cv_id": cv.id, "cv_filename": cv.filename,
            "match": report, "draft": cv_tailoring_draft(cv.text, job, report)}


@app.post("/api/applications/{application_id}/follow-up-sent")
def mark_followup_sent(
    application_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == user.id)
        .first()
    )
    if app is None:
        raise HTTPException(404, "Application not found.")
    if not followup_due(app):
        raise HTTPException(409, "Follow-up is not due, or this application has already closed.")
    app.notes = ((app.notes or "").rstrip() + f"\nFollow-up sent: {date.today().isoformat()}").strip()
    db.commit()
    return {"ok": True, "application_id": app.id,
            "sent_at": date.today().isoformat()}


@app.post("/api/applications/{application_id}/find-contact")
def find_followup_contact(
    application_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app = db.query(Application).filter(
        Application.user_id == user.id, Application.id == application_id
    ).first()
    if app is None:
        raise HTTPException(404, "Application not found.")
    if not followup_due(app):
        raise HTTPException(409, "This application is not due for a follow-up.")
    return discover_contact(db, user.id, app, search=True)


@app.post("/api/applications/{application_id}/send-follow-up")
def send_followup(
    application_id: int,
    payload: ApprovedFollowupSend,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = (
        db.query(Application)
        .filter(Application.id == application_id, Application.user_id == user.id)
        .first()
    )
    if not application:
        raise HTTPException(404, "Application not found.")
    if not followup_due(application):
        raise HTTPException(409, "This application is closed or the next follow-up is not due.")
    connection = db.query(GmailConnection).filter(GmailConnection.user_id == user.id).first()
    if not gmail_can_send(connection):
        raise HTTPException(403, "Enable Gmail Send permission in Settings before sending.")
    recipient = payload.recipient.strip()
    if (
        not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", recipient)
        or "\n" in recipient or "\r" in recipient
    ):
        raise HTTPException(400, "Enter one valid verified recruiter email address.")
    local = recipient.split("@", 1)[0].lower().replace("-", "").replace("_", "")
    if "noreply" in local or "donotreply" in local:
        raise HTTPException(400, "Do not send a follow-up to a no-reply address.")
    try:
        message_id = gmail_send_approved(db, connection, recipient, payload.subject.strip(), payload.body.strip())
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.exception("Gmail send failed for application %s", application_id)
        raise HTTPException(502, "Gmail did not accept the message. Check permissions and retry carefully.") from exc
    application.notes = ((application.notes or "").rstrip() + f"\nFollow-up sent: {date.today().isoformat()}").strip()
    db.commit()
    return {"sent": True, "message_id": message_id, "application_id": application.id}


@app.get("/api/jobs/{job_id}/ats-review")
def job_ats_review(
    job_id: int,
    cv_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(LiveJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    cv, _, _ = resolve_job_cv(db, user.id, job, cv_id)
    if not cv:
        raise HTTPException(400, "Upload or select your CV first.")
    return {"cv_filename": cv.filename, "job": serialize_job(job),
            "assessment": evaluate_cv_ats(cv.text, match_details(cv, job))}


@app.get("/api/jobs/{job_id}/match-report")
def job_match_report(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(LiveJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")

    cv, _, _ = resolve_job_cv(db, user.id, job)
    if not cv:
        raise HTTPException(400, "Upload your CV before calculating a match report.")

    details = match_details(cv, job)
    return {
        "job": serialize_job(job, details),
        "match": details,
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

    cv, _, _ = resolve_job_cv(db, user.id, job)
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

    cv, _, _ = resolve_job_cv(db, user.id, job)
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
    supported = {"lever", "lever-eu", "smartrecruiters", "ashby", "greenhouse", "personio", "workable"}
    if provider not in supported:
        raise HTTPException(
            400,
            "Supported providers: lever, lever-eu, smartrecruiters, ashby, greenhouse, personio, workable.",
        )

    identifier = payload.identifier.strip().strip("/")
    if provider == "ashby" and "jobs.ashbyhq.com/" in identifier:
        identifier = identifier.split("jobs.ashbyhq.com/", 1)[1].split("/", 1)[0]
    if not identifier:
        raise HTTPException(400, "Company/job-board identifier is required.")
    if provider in {"personio", "workable"} and not re.fullmatch(r"[A-Za-z0-9-]{1,100}", identifier):
        raise HTTPException(400, "Personio and Workable require a company slug, not a full URL.")

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
        "cover_letter_text": item.cover_letter_text,
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

    cv, _, _ = resolve_job_cv(db, user.id, job, payload.cv_id)
    if not cv:
        raise HTTPException(400, "Upload or select one of your own CV versions before preparation.")

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


@app.post("/api/jobs/{job_id}/cover-letter-render")
def render_approved_cover_letter(
    job_id: int, payload: CoverLetterDraft,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    job = db.get(LiveJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    content = build_cover_letter_docx(payload.text, user, job)
    filename = safe_filename(f"{user.display_name}_{job.company}_Cover_Letter") + ".docx"
    return {"name": filename,
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "base64": base64.b64encode(content).decode("ascii")}


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
def applications(
    active_only: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Application).filter(Application.user_id == user.id)
    if active_only:
        query = query.filter(Application.status != "Rejected")
    return query.order_by(Application.created_at.desc()).all()


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


@app.get("/api/applications/{application_id}/rejection-review")
def review_application_rejection(
    application_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    app_item = db.query(Application).filter(
        Application.id == application_id, Application.user_id == user.id
    ).first()
    if not app_item:
        raise HTTPException(404, "Application not found.")
    event = db.query(GmailEvent).filter(
        GmailEvent.user_id == user.id,
        GmailEvent.application_id == app_item.id,
        GmailEvent.outcome == "Rejected",
    ).order_by(GmailEvent.received_at.desc().nullslast(), GmailEvent.created_at.desc()).first()
    if not event:
        return {
            "application_id": app_item.id,
            "company": app_item.company,
            "status": app_item.status,
            "reason_available": False,
            "message": "No matched Gmail rejection is recorded yet. Sync Gmail and verify the employer email was matched to this application.",
        }
    connection = db.query(GmailConnection).filter(GmailConnection.user_id == user.id).first()
    if not connection:
        raise HTTPException(409, "Connect Gmail to review the original rejection.")
    try:
        token = ensure_access_token(db, connection)
        response = httpx.get(
            f"{GMAIL_API}/users/me/messages/{event.gmail_message_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"format": "full"},
            timeout=20,
        )
        response.raise_for_status()
    except (httpx.HTTPError, RuntimeError) as exc:
        logger.warning("Could not retrieve rejection review email for user %s", user.id)
        raise HTTPException(502, "Could not read the original Gmail rejection. Verify Gmail connection and try again.") from exc
    original = response.json()
    headers = _gmail_headers(original)
    original_subject = headers.get("subject") or event.subject
    original_sender = headers.get("from") or event.sender
    body = _message_body_text(original) or original.get("snippet") or event.snippet or ""
    verified_evidence = rejection_evidence(original_subject, body)
    if not verified_evidence or classify_message(original_subject, body) != "Rejected":
        return {
            "application_id": app_item.id,
            "company": app_item.company,
            "status": app_item.status,
            "reason_available": False,
            "source_subject": original_subject,
            "source_sender": original_sender,
            "message": "This original email does not contain a confirmed rejection. JobIntel will re-check the recorded status automatically; refresh My Applications to see the correction.",
        }
    review = rejection_review(body, original_subject)
    return {
        "application_id": app_item.id,
        "company": app_item.company,
        "role": app_item.role,
        "status": app_item.status,
        "reason_available": True,
        "source_subject": original_subject,
        "source_sender": original_sender,
        "gmail_received_at": event.received_at.isoformat() if event.received_at else None,
        "confirmed_rejection_excerpt": verified_evidence,
        **review,
    }


@app.get("/api/cv")
def get_cv(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cv = latest_cv(db, user.id)
    if not cv:
        return {"uploaded": False}

    details = refresh_cv_analysis(db, cv)
    relevant = candidate_job_records(cv, db.query(LiveJob).all(), user.target_roles,
                                     cv_tracks_for_user(db, user.id))
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


@app.get("/api/candidate-profile")
def get_candidate_profile(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    row = db.query(CandidateProfile).filter(CandidateProfile.user_id == user.id).first()
    verified = json.loads(row.profile_json or "{}") if row else {}
    full_name = user.display_name.split()
    return {
        "firstName": verified.get("firstName", full_name[0] if full_name else ""),
        "lastName": verified.get("lastName", " ".join(full_name[1:])),
        "email": user.email, "fullName": user.display_name,
        **{key: verified.get(key, "") for key in (
            "phone", "city", "country", "linkedin", "github", "portfolio",
            "education", "employment", "languages"
        )},
        "verified": bool(row),
    }


@app.patch("/api/candidate-profile")
def update_candidate_profile(
    payload: CandidateProfileUpdate,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    values = payload.model_dump()
    for key in ("linkedin", "github", "portfolio"):
        link = values.get(key, "").strip()
        if link and (not link.startswith("https://") or "@" in link.split("/", 3)[2]):
            raise HTTPException(400, key + " must be a public HTTPS URL.")
    row = db.query(CandidateProfile).filter(CandidateProfile.user_id == user.id).first()
    if row is None:
        row = CandidateProfile(user_id=user.id)
        db.add(row)
    row.profile_json = json.dumps(values)
    row.updated_at = datetime.utcnow()
    db.commit()
    return get_candidate_profile(user=user, db=db)


@app.get("/api/documents")
def list_candidate_documents(
    kind: str | None = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    query = db.query(CandidateDocument).filter(CandidateDocument.user_id == user.id)
    if kind:
        if kind not in {"cv", "experience", "cover"}:
            raise HTTPException(400, "Unknown document kind.")
        query = query.filter(CandidateDocument.kind == kind)
    return [public_document(row) for row in query.order_by(CandidateDocument.created_at.desc()).all()]


@app.get("/api/documents/selected")
def selected_documents_for_job(
    job_id: int,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    job = db.get(LiveJob, job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    family = job_role_family(job.title)
    docs = {}
    for kind in ("cv", "experience", "cover"):
        row = choose_document(db, user.id, kind, family if kind == "cv" else "general")
        if row:
            docs[kind] = public_document(row)
    return {"role_family": family, "documents": docs}


@app.post("/api/documents")
async def upload_candidate_document(
    file: UploadFile = File(...), kind: str = "cv", role_family: str = "general",
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if kind == "cv":
        raise HTTPException(400, "Use the CV upload flow to save and analyze a CV.")
    raw = await file.read(8 * 1024 * 1024 + 1)
    row = store_document(db, user.id, file.filename or "document.pdf", raw, kind, role_family)
    return public_document(row)


@app.post("/api/documents/{document_id}/default")
def set_default_candidate_document(
    document_id: int,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    row = db.query(CandidateDocument).filter(
        CandidateDocument.id == document_id, CandidateDocument.user_id == user.id
    ).first()
    if not row:
        raise HTTPException(404, "Document not found.")
    db.query(CandidateDocument).filter(
        CandidateDocument.user_id == user.id, CandidateDocument.kind == row.kind,
        CandidateDocument.role_family == row.role_family
    ).update({"default_document": False})
    row.default_document = True
    db.commit()
    return public_document(row)


@app.get("/api/documents/{document_id}/content")
def candidate_document_content(
    document_id: int,
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    row = db.query(CandidateDocument).filter(
        CandidateDocument.id == document_id, CandidateDocument.user_id == user.id
    ).first()
    if not row:
        raise HTTPException(404, "Document not found.")
    return {
        "name": row.filename,
        "mimeType": row.mime_type,
        "base64": base64.b64encode(read_document(row)).decode("ascii"),
    }


@app.post("/api/cv/upload")
async def upload_cv(
    file: UploadFile = File(...),
    role_family: str = "general",
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
    # Preserve the exact source bytes as well as extracted CV text.
    # Users who uploaded before this release need to upload once more.
    store_document(db, user.id, file.filename or "cv.pdf", raw, "cv",
                   role_family, cv_profile_id=profile.id)
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

    records = candidate_job_records(cv, all_jobs, user.target_roles,
                                    cv_tracks_for_user(db, user.id))
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
    records = candidate_job_records(cv, all_jobs, user.target_roles,
                                    cv_tracks_for_user(db, user.id))
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
