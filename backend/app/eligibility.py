"""Explainable application eligibility, separate from ATS keyword overlap.

A job description is not a hiring decision. Mark unverified information as
unknown rather than guessing the user's employment permission or language.
"""
import re

LEVELS = {"a1":1,"a2":2,"b1":3,"b2":4,"c1":5,"c2":6}
TARGET_ROLES = (
    "intern", "internship", "praktikum", "werkstudent", "working student",
    "student assistant", "python", "backend", "software engineer", "data engineer",
    "automation", "qa engineer", "sdet", "ai engineer", "machine learning"
)


def assess_eligibility(cv: str, title: str, description: str, location: str = "",
                       profile: dict | None = None) -> dict:
    text = (description or "").lower()
    title_l = (title or "").lower()
    profile = profile or {}
    language_text = (profile.get("languages") or "") + " " + (cv or "")
    findings = []
    blockers = []
    unknowns = []

    explicit = re.search(
        r"(?:german|deutsch).{0,40}?\b(a1|a2|b1|b2|c1|c2)\b|"
        r"\b(a1|a2|b1|b2|c1|c2)\b.{0,35}?(?:german|deutsch)", text
    )
    required = (explicit.group(1) or explicit.group(2)) if explicit else None
    if not required and re.search(
        r"(?:fluent|native|professional|business).{0,20}(?:german|deutsch)|"
        r"(?:german|deutsch).{0,25}(?:fluent|required|mandatory)",text
    ):
        required = "b2"
    if required:
        cv_level = re.search(r"(?:german|deutsch)\s*[:\-–,]?\s*(a1|a2|b1|b2|c1|c2)", language_text.lower())
        level = cv_level.group(1) if cv_level else None
        if level is None:
            unknowns.append("Required German level is not verified.")
        elif LEVELS[level] < LEVELS[required]:
            blockers.append(f"German {required.upper()} required; verified CV/profile states {level.upper()}.")
        else:
            findings.append(f"German language requirement verified at {level.upper()}.")

    target_type = ("Working Student" if re.search(r"werkstudent|working.student|student.assistant",title_l)
                   else "Internship" if re.search(r"\bintern\b|internship|praktikum",title_l)
                   else "Full-time / Other")
    seniority = ("Senior/Staff" if re.search(r"\b(staff|principal|lead|head of|director|senior|sr\.)\b",title_l)
                 else "Entry/Mid or unspecified")
    if re.search(r"\b(staff|principal|director|head of)\b",title_l):
        findings.append("High-seniority role: confirm level-specific professional experience before applying.")
    if re.search(r"\bmanual(?:\s+only)?\s+(?:qa|test|tester|testing)\b|"
                 r"\b(?:manual tester|manual testing)\b",title_l):
        blockers.append("Manual-only testing is outside the selected automation target.")
    if not any(term in title_l for term in TARGET_ROLES):
        findings.append("Review role family manually; job title is outside the core target vocabulary.")
    if re.search(r"\b(?:must have|require[ds]?)\s+(?:an?\s+)?(?:unrestricted|existing)\s+"
                 r"(?:work permit|right to work|authorization to work)\b", text):
        unknowns.append("Employer requires verified work authorization; confirm in the employer form.")
    if re.search(r"\b(?:must be|must currently be|based in|reside in)\s+(?:the\s+)?"
                 r"(?:united states|usa|us only|uk only)\b",text):
        blockers.append("Location requirement appears outside Germany/EU target.")
    if target_type == "Working Student" and not re.search(
        r"\b(?:student|enrolled|matriculated|immatrikuliert|university)\b", cv.lower()
    ):
        unknowns.append("Current student enrollment is not verified in this CV.")
    status = "Blocked" if blockers else "Review needed" if unknowns else "No confirmed blockers"
    return {
        "status":status, "employment_type":target_type, "seniority":seniority,
        "hard_blockers":blockers, "needs_confirmation":unknowns, "notes":findings,
        "disclaimer":"Eligibility assessment uses only provided evidence, not an employer decision."
    }
