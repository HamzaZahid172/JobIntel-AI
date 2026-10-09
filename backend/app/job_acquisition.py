"""Practical application decisions. Scores are heuristics, not hiring probabilities."""
import re
from datetime import date, datetime
from urllib.parse import urlparse


DIRECT_SOURCES = {"Lever", "Ashby", "SmartRecruiters", "Greenhouse"}
FOLLOWUP_STATES = {"Applied", "Screening"}


def opportunity_assessment(job, match: dict | None, *, today: date | None = None) -> dict:
    today = today or date.today()
    score = float((match or {}).get("overall_score") or 0)
    role_score = float((match or {}).get("role_score") or 0)
    blockers = list((match or {}).get("hard_blockers") or [])
    posted_at = getattr(job, "posted_at", None)
    age_days = max((today - posted_at.date()).days, 0) if posted_at else None
    if age_days is None:
        freshness = 5
    elif age_days <= 2:
        freshness = 15
    elif age_days <= 7:
        freshness = 12
    elif age_days <= 14:
        freshness = 8
    elif age_days <= 30:
        freshness = 4
    else:
        freshness = 0

    direct = getattr(job, "source", "") in DIRECT_SOURCES
    score_value = min(100, round(score * 0.7 + freshness + (8 if direct else 4) + (7 if role_score >= 70 else 3 if role_score >= 45 else 0)))
    if blockers:
        score_value = min(score_value, 39)
        decision = "Skip"
    elif score >= 73 and role_score >= 45 and score_value >= 77:
        decision = "Apply Now"
    elif score >= 60 and role_score >= 35:
        decision = "Review"
    else:
        decision = "Skip"

    title = (getattr(job, "title", "") or "").lower()
    descriptions = (getattr(job, "job_types", "") or "").lower()
    # Block adjacent non-engineering roles: keyword overlap alone must never
    # recommend Product Management, sales or exclusively manual testing.
    off_target = bool(re.search(
        r"\\b(product manager|project manager|program manager|scrum master|"
        r"technical product owner|sales engineer|sales manager|account manager|"
        r"marketing|recruiter|hr manager|business development|"
        r"manual tester|manual testing|customer support)\\b", title
    ))
    if off_target:
        score_value = min(score_value, 34)
        decision = "Skip"
    words = title + " " + descriptions
    track = (
        "Internship" if re.search(r"intern(ship)?|praktik(um|ant)", words)
        else "Working Student" if re.search(r"werkstudent|working.student|student.assistant", words)
        else "Full-time / Other"
    )
    reasons = [
        f"CV-job match: {round(score)}%",
        f"Posted: {age_days} days ago" if age_days is not None else "Posting date not supplied",
        "Direct employer ATS source" if direct else "External job feed (verify employer listing)",
    ]
    if blockers:
        reasons.append("Blockers: " + "; ".join(blockers))
    if off_target:
        reasons.append("Role title does not match the candidate's engineering target roles.")
    return {
        "score": score_value,
        "decision": decision,
        "track": track,
        "age_days": age_days,
        "freshness_points": freshness,
        "direct_employer": direct,
        "reasons": reasons,
        "blockers": blockers,
        "disclaimer": "Heuristic priority, not the probability of receiving an offer.",
    }


def _followup_dates(notes: str) -> list[date]:
    results = []
    for value in re.findall(r"Follow-up sent: (\d{4}-\d{2}-\d{2})", notes or ""):
        try:
            results.append(date.fromisoformat(value))
        except ValueError:
            continue
    return results


def followup_due(application, *, today: date | None = None) -> bool:
    today = today or date.today()
    if application.status not in FOLLOWUP_STATES:
        return False
    if not application.applied_date or (today - application.applied_date).days < 7:
        return False
    previous = _followup_dates(application.notes or "")
    return not previous or (today - max(previous)).days >= 10


def followup_draft(application, name: str) -> dict:
    subject = f"Follow-up: {application.role} application at {application.company}"
    body = (
        f"Dear Hiring Team,\n\n"
        f"I hope you are doing well. I am following up on my application for the "
        f"{application.role} position at {application.company}, submitted on "
        f"{application.applied_date.isoformat() if application.applied_date else 'the previously recorded date'}. "
        "I remain interested in the opportunity and would appreciate an update "
        "on the hiring process when convenient.\n\n"
        "Thank you for your consideration.\n\n"
        f"Kind regards,\n{name}"
    )
    return {
        "application_id": application.id,
        "company": application.company,
        "role": application.role,
        "days_waiting": (date.today() - application.applied_date).days if application.applied_date else 0,
        "subject": subject,
        "body": body,
        "requires_approval": True,
    }


def _cv_evidence(cv_text: str, skills: list[str], limit: int = 5) -> list[str]:
    fragments = re.split(r"\n+|(?<=[.!?])\s+", cv_text or "")
    evidence = []
    for fragment in fragments:
        text = re.sub(r"\s+", " ", fragment).strip("• -*\t")
        if not 22 <= len(text) <= 280:
            continue
        if not any(re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", text, re.I) for skill in skills):
            continue
        if text not in evidence:
            evidence.append(text)
        if len(evidence) >= limit:
            break
    return evidence


def cv_tailoring_draft(cv_text: str, job, match: dict) -> dict:
    """Never claim a skill absent from CV evidence; do not silently edit the CV."""
    matched = list(match.get("matched_required_skills") or match.get("matched_skills") or [])
    missing = list(match.get("missing_required_skills") or [])
    evidence = _cv_evidence(cv_text, matched)
    highlights = ", ".join(matched[:5])
    summary = (
        f"Software professional applying for the {job.title} role at {job.company}. "
        + (f"Relevant skills documented in the CV include {highlights}. " if highlights else "")
        + "Experienced in delivering software-related work, with detailed examples in the original CV."
    )
    return {
        "job_id": job.id,
        "job_title": job.title,
        "company": job.company,
        "suggested_summary": summary,
        "cv_evidence": evidence,
        "matched_skills": matched,
        "missing_skills_do_not_claim": missing,
        "review_required": True,
        "instructions": "Review this evidence-based draft. Preserve your CV's dates, qualifications and experience; do not claim missing skills.",
    }
