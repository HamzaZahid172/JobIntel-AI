import re
from datetime import datetime

from .intelligence import rank_cv_skills


def _language_note(cv_text: str, language: str) -> str | None:
    lower = (cv_text or "").lower()
    if language.lower() == "german":
        match = re.search(r"(german|deutsch).{0,25}\b(a1|a2|b1|b2|c1|c2)\b", lower)
        if match:
            return match.group(2).upper()
        if "german" in lower or "deutsch" in lower:
            return "Mentioned in CV"
    if language.lower() in lower:
        return "Mentioned in CV"
    return None


def build_screening_drafts(cv_text: str, job, match_report: dict, user) -> list[dict]:
    matched = match_report.get("matched_required_skills") or match_report.get("matched_skills") or []
    top_cv = [row["skill"] for row in rank_cv_skills(cv_text, limit=8)]

    answers = [
        {
            "key": "why_role",
            "question": "Why are you interested in this role?",
            "status": "draft",
            "answer": (
                f"I am interested in the {job.title} role at {job.company} because it aligns with "
                f"my experience in {', '.join((matched or top_cv)[:5])}. "
                "The position is relevant to the kind of software engineering work I want to continue developing."
            ),
        },
        {
            "key": "relevant_experience",
            "question": "What experience is most relevant?",
            "status": "draft",
            "answer": (
                "My strongest directly relevant technical experience includes "
                + ", ".join((matched or top_cv)[:6])
                + ". I would use that background as the starting point for the responsibilities in this role."
            ),
        },
        {
            "key": "work_authorization",
            "question": "What is your work authorization / visa status?",
            "status": "needs_user_input",
            "answer": "",
        },
        {
            "key": "salary_expectation",
            "question": "What is your salary expectation?",
            "status": "needs_user_input",
            "answer": "",
        },
        {
            "key": "availability",
            "question": "When can you start / what is your notice period?",
            "status": "needs_user_input",
            "answer": "",
        },
    ]

    for requirement in match_report.get("requirements", {}).get("languages", []):
        language = requirement.get("language")
        evidence = _language_note(cv_text, language)
        answers.append({
            "key": f"language_{language.lower()}",
            "question": f"What is your {language} proficiency?",
            "status": "draft" if evidence else "needs_user_input",
            "answer": evidence or "",
        })

    return answers


def build_validation(match_report: dict, minimum_match: float) -> dict:
    score = float(match_report.get("overall_score") or 0)
    blockers = list(match_report.get("hard_blockers") or [])
    checks = [
        {
            "name": "minimum_match",
            "passed": score >= minimum_match,
            "detail": f"Match {round(score)}% vs threshold {round(minimum_match)}%",
        },
        {
            "name": "role_alignment",
            "passed": (match_report.get("role_score") or 0) >= 45,
            "detail": f"Role alignment {match_report.get('role_score', 0)}%",
        },
        {
            "name": "hard_blockers",
            "passed": not blockers,
            "detail": "No hard blockers" if not blockers else "; ".join(blockers),
        },
    ]
    return {
        "passed": all(row["passed"] for row in checks),
        "checks": checks,
        "hard_blockers": blockers,
    }


def build_application_package_payload(
    *,
    job,
    cv,
    user,
    match_report: dict,
    cover_letter_text: str,
    cover_letter_generator: str,
    minimum_match: float,
) -> dict:
    screening = build_screening_drafts(cv.text, job, match_report, user)
    validation = build_validation(match_report, minimum_match)
    unresolved = [row["key"] for row in screening if row["status"] == "needs_user_input"]

    status = "Package Ready" if validation["passed"] and not unresolved else "Needs Review"

    return {
        "status": status,
        "prepared_at": datetime.utcnow().isoformat(),
        "job": {
            "id": job.id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "source": job.source,
            "url": job.url,
        },
        "candidate": {
            "name": user.display_name,
            "email": user.email,
            "cv_filename": cv.filename,
            "cv_profile_id": cv.id,
        },
        "match": match_report,
        "cover_letter": {
            "generator": cover_letter_generator,
            "ready": bool(cover_letter_text.strip()),
        },
        "screening_answers": screening,
        "unresolved_fields": unresolved,
        "validation": validation,
    }
