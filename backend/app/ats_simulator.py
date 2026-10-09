"""Deterministic, evidence-based ATS simulation (not a proprietary ATS score)."""
import re

from .intelligence import ats_check


def ats_review(cv_text: str, match_report: dict) -> dict:
    raw = cv_text or ""
    clean = re.sub(r"\s+", " ", raw).strip()
    baseline = ats_check(raw)
    requirements = match_report.get("requirements") or {}
    required = (
        requirements.get("required_skills")
        or match_report.get("required_skills")
        or []
    )
    preferred = (
        requirements.get("preferred_skills")
        or match_report.get("preferred_skills")
        or []
    )
    # Use matches reported by the existing structured match layer; preserve source truth.
    matched = set(x.lower() for x in match_report.get("matched_required_skills") or [])
    confirmed = [skill for skill in required if skill.lower() in matched or
                 re.search(r"(?<!\w)"+re.escape(skill)+r"(?!\w)", raw, re.I)]
    missing = [skill for skill in required if skill not in confirmed]
    sections = {
        "experience": bool(re.search(r"\b(experience|employment|work history|berufserfahrung)\b",raw,re.I)),
        "education": bool(re.search(r"\b(education|university|degree|ausbildung|studium)\b",raw,re.I)),
        "skills": bool(re.search(r"\b(skills|technologies|technical|kompetenzen)\b",raw,re.I)),
        "contact_email": bool(re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",raw)),
    }
    evidence_count = len(confirmed)
    coverage = round(100*evidence_count/len(required)) if required else None
    blockers = list(match_report.get("hard_blockers") or [])
    notes = []
    if not sections["contact_email"]:
        notes.append("Add a clearly readable contact email to the uploaded CV.")
    for field in ("experience","education","skills"):
        if not sections[field]:
            notes.append("Check that the "+field+" section is clearly labelled and readable.")
    if missing:
        notes.append("Do not invent missing skills. Provide evidence only for skills you actually have.")
    if blockers:
        notes.append("Resolve role, language or eligibility blockers before applying.")
    return {
        "label": "Local job-specific ATS simulation — NOT an employer ATS result",
        "ats_readiness": baseline.get("score"),
        "cv_parse_checks": sections,
        "required_skill_coverage": coverage,
        "required_skills_found": confirmed,
        "required_skills_missing": missing,
        "preferred_skills": preferred,
        "hard_blockers": blockers,
        "job_match_score": match_report.get("overall_score"),
        "suggestions": notes,
        "pass_guarantee": False,
    }
