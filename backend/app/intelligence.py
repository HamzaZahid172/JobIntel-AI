import re
from collections import Counter

SKILLS = [
    "python", "fastapi", "sql", "postgresql", "aws", "docker", "kubernetes", "kafka",
    "airflow", "terraform", "spark", "dbt", "react", "typescript", "javascript", "playwright",
    "selenium", "cypress", "pandas", "rest", "graphql", "java", "spring boot", "linux", "git"
]

ATS_SECTIONS = ["experience", "education", "skills", "projects"]

def extract_skills(text: str) -> list[str]:
    t = text.lower()
    return [s for s in SKILLS if re.search(rf"\b{re.escape(s)}\b", t)]

def ats_check(text: str) -> dict:
    lower = text.lower()
    skills = extract_skills(text)
    sections = sum(1 for s in ATS_SECTIONS if s in lower)
    contact_ok = bool(re.search(r"[\w.+'-]+@[\w.-]+\.\w+", text)) and bool(re.search(r"\+?\d[\d\s()\-]{7,}", text))
    length_ok = 350 <= len(text.split()) <= 1800
    bullets = len(re.findall(r"(?:^|\n)\s*[•\-*]", text))
    score = 35 + min(25, len(skills) * 2) + sections * 7 + (8 if contact_ok else 0) + (4 if length_ok else 0)
    score = min(100, score)
    suggestions = []
    if sections < 4: suggestions.append("Use clear Experience, Skills, Projects and Education headings.")
    if not contact_ok: suggestions.append("Keep a plain-text email and phone number in the header.")
    if len(skills) < 10: suggestions.append("Add more role-relevant technical keywords where they are truthful.")
    if bullets < 6: suggestions.append("Use concise achievement bullets with measurable impact.")
    if not length_ok: suggestions.append("Keep the CV concise and focused, ideally around 1–2 pages.")
    return {
        "score": score,
        "status": "ATS Ready" if score >= 80 else "Needs Improvement",
        "format_ok": True,
        "sections_complete": f"{sections}/4",
        "keyword_coverage": min(100, 45 + len(skills) * 4),
        "skills_detected": skills,
        "suggestions": suggestions or ["Strong baseline. Tailor keywords to each job description."],
    }

def match_cv_to_job(cv_text: str, job_description: str) -> dict:
    cv_skills = set(extract_skills(cv_text))
    job_skills = set(extract_skills(job_description))
    matched = sorted(cv_skills & job_skills)
    missing = sorted(job_skills - cv_skills)
    skill_score = round((len(matched) / max(1, len(job_skills))) * 100)
    experience_score = 90 if re.search(r"7\+?\s*years|senior", cv_text.lower()) else 70
    language_score = 82 if "german" in cv_text.lower() else 70
    overall = round(skill_score * .65 + experience_score * .25 + language_score * .10)
    readiness = "High" if overall >= 80 else "Medium" if overall >= 65 else "Developing"
    return {
        "overall_score": overall,
        "skill_score": skill_score,
        "experience_score": experience_score,
        "language_score": language_score,
        "matched_skills": matched,
        "missing_skills": missing,
        "readiness": readiness,
        "improvements": improvement_suggestions(missing),
    }

def improvement_suggestions(missing: list[str]) -> list[dict]:
    priority = ["kafka", "airflow", "terraform", "kubernetes", "aws", "dbt", "spark", "german"]
    ordered = sorted(missing, key=lambda x: priority.index(x) if x in priority else 999)
    out = []
    for skill in ordered[:4]:
        action = {
            "kafka": "Build a small event-streaming producer/consumer and add it to this project.",
            "airflow": "Create a daily DAG that validates and aggregates job-market data.",
            "terraform": "Define the local/cloud-ready infrastructure as code.",
            "kubernetes": "Deploy the API, frontend and worker to a local kind cluster.",
            "aws": "Deploy a small free-tier-compatible demo or document an AWS architecture.",
            "dbt": "Model clean job and skill marts using dbt Core.",
            "spark": "Add a batch transformation example for larger job datasets.",
        }.get(skill, f"Create a focused mini-project or feature that demonstrates {skill}.")
        out.append({"skill": skill.title(), "priority": "High Value", "action": action})
    return out

def aggregate_skills(job_skill_strings: list[str]) -> list[dict]:
    c = Counter()
    for value in job_skill_strings:
        c.update([s.strip().lower() for s in value.split(",") if s.strip()])
    return [{"skill": k.title(), "count": v} for k, v in c.most_common(8)]
