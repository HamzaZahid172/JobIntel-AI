"""Evidence-first review before a candidate submits an employer application.

Heuristic checks are not employer decisions, legal work-permit advice, or a
prediction of interview probability. Never infer consent or work authorization.
"""
import re
from datetime import date


def job_role_family(title: str) -> str:
    value = (title or "").lower()
    if re.search(r"\b(?:qa|sdet|quality assurance|test automation|automation test|test engineer|tester)\b", value):
        return "qa"
    if re.search(r"\b(?:data engineer|data engineering|etl|analytics engineer|data pipeline|data platform)\b", value):
        return "data"
    if re.search(r"\b(?:backend|back.end|python developer|software engineer|full.stack|ai engineer|ml engineer)\b", value):
        return "backend"
    return "general"


def pre_application_review(job, cv, report: dict, *, selected_role: str = "general",
                           saved_cv: bool = False, today: date | None = None) -> dict:
    today = today or date.today()
    role = job_role_family(getattr(job, "title", ""))
    problems = []
    def add(code: str, level: str, message: str) -> None:
        problems.append({"code": code, "level": level, "message": message})

    if not cv:
        add("missing_cv", "blocker", "Upload a readable CV before applying.")
    elif role != "general" and selected_role != role:
        add("role_cv", "review", f"A dedicated {role.upper()} CV was not selected. Check whether this general CV highlights the right experience.")

    if cv and not saved_cv:
        add("original_attachment", "review", "No original CV attachment is linked for this version. Verify the uploaded PDF/DOCX in the employer form.")

    score = float((report or {}).get("overall_score") or 0)
    blockers = list((report or {}).get("hard_blockers") or [])
    for blocker in blockers:
        add("eligibility_blocker", "blocker", blocker)
    eligibility = (report or {}).get("eligibility") or {}
    for question in eligibility.get("needs_confirmation") or []:
        add("eligibility_unknown", "review", question)
    if (report or {}).get("location_score", 100) < 60:
        add("location_unknown", "review", "Confirm this employer accepts candidates working from Germany.")

    missing = list((report or {}).get("missing_required_skills") or [])
    if missing:
        add("skills_to_check", "review", "Required skills without CV evidence: " + ", ".join(missing[:8]) + ". Do not claim missing experience.")

    posted = getattr(job, "posted_at", None)
    age = max(0, (today - posted.date()).days) if posted else None
    if age is None or age > 30:
        add("vacancy_open", "review", "Verify the vacancy is still accepting applications on the employer website.")

    if role != "general" and cv:
        text = cv.text or ""
        if not re.search(r"\b(?:experience|employment|work history|berufserfahrung)\b", text, re.I):
            add("work_history", "review", "Check that the CV has a clearly labeled employment history.")
        if not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text):
            add("contact", "review", "Verify that the employer can read your contact email in the CV.")

    add("work_permission", "review", "Confirm your current work authorization for this specific position; do not assume unrestricted full-time permission.")
    add("application_confirmation", "review", "After submitting, verify the employer's confirmation. Clicking Submit alone is not proof.")
    add("cv_history", "info", "Check official job titles and dates against your experience letter; do not turn responsibilities into unverified titles.")

    status = ("Not recommended until blockers resolved" if any(x["level"] == "blocker" for x in problems)
              else "Review before applying")
    return {
        "status": status,
        "role_family": role,
        "cv_filename": getattr(cv, "filename", None),
        "selected_cv_family": selected_role,
        "cv_document_saved": saved_cv,
        "technical_match_percent": round(score),
        "score_meaning": "Heuristic CV/description overlap, not probability of interview or ATS approval.",
        "vacancy_age_days": age,
        "missing_required_skills": missing,
        "checks": problems,
        "human_confirmation_required": True,
        "employer_submission_verified": False,
    }
