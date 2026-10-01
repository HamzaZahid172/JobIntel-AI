import re
from dataclasses import dataclass

from .intelligence import (
    classify_job_role,
    extract_skills,
    profile_role_families,
)


REQUIRED_CUES = (
    "required", "must have", "must-have", "you have", "you bring",
    "requirements", "qualifications", "experience with", "proficiency in",
    "strong knowledge", "hands-on", "hands on",
)
PREFERRED_CUES = (
    "nice to have", "nice-to-have", "preferred", "bonus", "plus",
    "advantage", "ideally", "desirable",
)


def _sentences(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+|\n+", text or "")
        if part.strip()
    ]


def _skills_by_requirement(description: str) -> tuple[list[str], list[str]]:
    required = set()
    preferred = set()
    all_skills = set(extract_skills(description))

    for sentence in _sentences(description):
        sentence_l = sentence.lower()
        skills = set(extract_skills(sentence))
        if not skills:
            continue
        if any(cue in sentence_l for cue in PREFERRED_CUES):
            preferred.update(skills)
        elif any(cue in sentence_l for cue in REQUIRED_CUES):
            required.update(skills)

    # Skills mentioned without an explicit "preferred" cue are treated as
    # core job skills, but we keep explicit preferred skills separate.
    required.update(all_skills - preferred)
    return sorted(required), sorted(preferred)


def _years_required(text: str) -> int | None:
    values = [
        int(value)
        for value in re.findall(
            r"\b(\d{1,2})\+?\s*(?:years?|yrs?|jahre)\b",
            (text or "").lower(),
        )
    ]
    return max(values) if values else None


def _years_in_cv(text: str) -> int | None:
    values = [
        int(value)
        for value in re.findall(
            r"\b(\d{1,2})\+?\s*(?:years?|yrs?|jahre)\b",
            (text or "").lower(),
        )
    ]
    return max(values) if values else None


def _language_requirements(text: str) -> list[dict]:
    lower = (text or "").lower()
    requirements = []

    german_patterns = [
        (r"german.{0,20}\b(c1|c2)\b|\b(c1|c2)\b.{0,20}german", "German", "C1+"),
        (r"german.{0,20}\b(b2)\b|\bb2\b.{0,20}german", "German", "B2"),
        (r"(?:fluent|native|professional).{0,20}german|german.{0,20}(?:required|mandatory|must)", "German", "Required"),
        (r"deutsch.{0,20}\b(c1|c2)\b|\b(c1|c2)\b.{0,20}deutsch", "German", "C1+"),
        (r"deutsch.{0,20}\bb2\b|\bb2\b.{0,20}deutsch", "German", "B2"),
    ]
    for pattern, language, level in german_patterns:
        if re.search(pattern, lower):
            requirements.append({"language": language, "level": level, "required": True})
            break

    if re.search(r"(?:fluent|professional|business).{0,20}english|english.{0,20}(?:required|mandatory|must)", lower):
        requirements.append({"language": "English", "level": "Professional", "required": True})

    return requirements


def _cv_mentions_language(cv_text: str, language: str) -> bool:
    lower = (cv_text or "").lower()
    if language.lower() == "german":
        return "german" in lower or "deutsch" in lower
    return language.lower() in lower


def _location_score(location: str, remote: bool) -> tuple[int, str]:
    lower = (location or "").lower()
    germany_terms = (
        "germany", "deutschland", "berlin", "munich", "münchen", "hamburg",
        "frankfurt", "stuttgart", "dresden", "leipzig", "düsseldorf",
        "dusseldorf", "köln", "cologne", "hannover", "erfurt", "ilmenau",
        "karlsruhe", "aachen", "jena", "nuremberg", "nürnberg",
    )
    eu_remote_terms = ("europe", "eu", "emea", "cet", "cest")
    if any(term in lower for term in germany_terms):
        return 100, "Germany location"
    if remote and (not lower or "remote" in lower or any(term in lower for term in eu_remote_terms)):
        return 95, "Remote / Europe-compatible"
    return 55, "Location needs review"


def extract_job_requirements(
    title: str,
    description: str,
    location: str = "",
    remote: bool = False,
) -> dict:
    required_skills, preferred_skills = _skills_by_requirement(description)
    return {
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "role_families": classify_job_role(title, description),
        "years_required": _years_required(description),
        "languages": _language_requirements(description),
        "location": location,
        "remote": remote,
    }


def build_match_report(
    cv_text: str,
    title: str,
    description: str,
    location: str = "",
    remote: bool = False,
) -> dict:
    requirements = extract_job_requirements(title, description, location, remote)

    cv_skills = set(extract_skills(cv_text))
    required = set(requirements["required_skills"])
    preferred = set(requirements["preferred_skills"])

    matched_required = sorted(required & cv_skills)
    missing_required = sorted(required - cv_skills)
    matched_preferred = sorted(preferred & cv_skills)
    missing_preferred = sorted(preferred - cv_skills)

    if required:
        required_score = round(len(matched_required) / len(required) * 100)
    else:
        required_score = 70

    if preferred:
        preferred_score = round(len(matched_preferred) / len(preferred) * 100)
    else:
        preferred_score = 80

    cv_families = set(profile_role_families(cv_text))
    job_families = set(requirements["role_families"])
    role_overlap = sorted(cv_families & job_families)
    if role_overlap:
        role_score = 95
    elif job_families and cv_families:
        role_score = 45
    elif job_families:
        role_score = 55
    else:
        role_score = 25

    years_required = requirements["years_required"]
    cv_years = _years_in_cv(cv_text)
    if years_required is None:
        experience_score = 80
    elif cv_years is None:
        experience_score = 55
    elif cv_years >= years_required:
        experience_score = 100
    else:
        experience_score = max(25, round(cv_years / years_required * 100))

    language_requirements = requirements["languages"]
    missing_languages = [
        row for row in language_requirements
        if row.get("required") and not _cv_mentions_language(cv_text, row["language"])
    ]
    language_score = 100 if not missing_languages else 35

    location_score, location_reason = _location_score(location, remote)

    overall = round(
        role_score * 0.30
        + required_score * 0.30
        + preferred_score * 0.10
        + experience_score * 0.15
        + language_score * 0.10
        + location_score * 0.05
    )

    hard_blockers = []
    if role_score < 30:
        hard_blockers.append("Role family does not align with the current CV profile.")
    if required and required_score < 35:
        hard_blockers.append("Too many core technical requirements are missing.")
    if missing_languages:
        hard_blockers.append(
            "A required language is not clearly evidenced in the uploaded CV."
        )

    if hard_blockers:
        overall = min(overall, 59)

    reasons = []
    if role_overlap:
        reasons.append("Role family aligns: " + ", ".join(role_overlap))
    if matched_required:
        reasons.append("Matched core skills: " + ", ".join(matched_required[:8]))
    if missing_required:
        reasons.append("Missing core skills: " + ", ".join(missing_required[:6]))
    reasons.append(location_reason)

    readiness = "Strong" if overall >= 80 else "Good" if overall >= 65 else "Low"

    return {
        "overall_score": max(0, min(100, overall)),
        "readiness": readiness,
        "eligible_for_preparation": overall >= 70 and not hard_blockers,
        "score_breakdown": {
            "role_alignment": role_score,
            "required_skills": required_score,
            "preferred_skills": preferred_score,
            "experience": experience_score,
            "language": language_score,
            "location": location_score,
        },
        "requirements": requirements,
        "job_skills": sorted(required | preferred),
        "matched_skills": sorted((required | preferred) & cv_skills),
        "missing_skills": sorted((required | preferred) - cv_skills),
        "matched_required_skills": matched_required,
        "missing_required_skills": missing_required,
        "matched_preferred_skills": matched_preferred,
        "missing_preferred_skills": missing_preferred,
        "profile_role_families": sorted(cv_families),
        "job_role_families": sorted(job_families),
        "role_score": role_score,
        "skill_score": required_score,
        "experience_score": experience_score,
        "language_score": language_score,
        "location_score": location_score,
        "hard_blockers": hard_blockers,
        "reasons": reasons,
    }
