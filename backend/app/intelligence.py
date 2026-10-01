import re
from collections import Counter

SKILLS = [
    "python", "fastapi", "sql", "postgresql", "mysql", "aws", "azure", "gcp",
    "docker", "kubernetes", "kafka", "airflow", "terraform", "spark", "dbt",
    "react", "typescript", "javascript", "node.js", "playwright", "selenium",
    "cypress", "webdriverio", "puppeteer", "pandas", "rest", "graphql", "java",
    "spring boot", "linux", "git", "github actions", "gitlab ci", "jenkins",
    "prometheus", "grafana", "redis", "mongodb", "microservices", "pytest",
]

ATS_SECTIONS = ["experience", "education", "skills", "projects"]


def extract_skills(text: str) -> list[str]:
    t = text.lower()
    found = []
    for skill in SKILLS:
        pattern = rf"(?<![\w.]){re.escape(skill)}(?![\w.])"
        if re.search(pattern, t):
            found.append(skill)
    return found


def ats_check(text: str) -> dict:
    lower = text.lower()
    skills = extract_skills(text)
    sections = sum(1 for s in ATS_SECTIONS if s in lower)
    contact_ok = bool(re.search(r"[\w.+'-]+@[\w.-]+\.\w+", text)) and bool(
        re.search(r"\+?\d[\d\s()\-]{7,}", text)
    )
    length_ok = 350 <= len(text.split()) <= 1800
    bullets = len(re.findall(r"(?:^|\n)\s*[•\-*]", text))
    score = 35 + min(25, len(skills) * 2) + sections * 7 + (8 if contact_ok else 0) + (4 if length_ok else 0)
    score = min(100, score)

    suggestions = []
    if sections < 4:
        suggestions.append("Use clear Experience, Skills, Projects and Education headings.")
    if not contact_ok:
        suggestions.append("Keep a plain-text email and phone number in the header.")
    if len(skills) < 10:
        suggestions.append("Add more role-relevant technical keywords where they are truthful.")
    if bullets < 6:
        suggestions.append("Use concise achievement bullets with measurable impact.")
    if not length_ok:
        suggestions.append("Keep the CV concise and focused, ideally around 1–2 pages.")

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

    if job_skills:
        skill_score = round((len(matched) / len(job_skills)) * 100)
    else:
        skill_score = 50

    cv_lower = cv_text.lower()
    experience_score = 90 if re.search(r"7\+?\s*years|senior", cv_lower) else 70
    language_score = 82 if "german" in cv_lower else 70
    overall = round(skill_score * 0.70 + experience_score * 0.20 + language_score * 0.10)
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
    priority = ["kafka", "airflow", "terraform", "kubernetes", "aws", "dbt", "spark", "gcp", "azure"]
    ordered = sorted(set(missing), key=lambda x: priority.index(x) if x in priority else 999)
    out = []
    for skill in ordered[:5]:
        action = {
            "kafka": "Build a small event-streaming producer/consumer and add it to JobIntel.",
            "airflow": "Create a daily DAG that validates and aggregates job-market data.",
            "terraform": "Define the local/cloud-ready infrastructure as code.",
            "kubernetes": "Deploy the API, frontend and worker to a local kind cluster.",
            "aws": "Add a documented AWS deployment architecture and one hands-on deployment.",
            "gcp": "Add a small GCP deployment example or architecture.",
            "azure": "Add a small Azure deployment example or architecture.",
            "dbt": "Model clean job and skill marts using dbt Core.",
            "spark": "Add a batch transformation example for larger job datasets.",
        }.get(skill, f"Create a focused feature that demonstrates {skill}.")
        out.append({"skill": skill.title(), "priority": "High Value", "action": action})
    return out


def aggregate_skills(job_skill_strings: list[str]) -> list[dict]:
    counter = Counter()
    for value in job_skill_strings:
        counter.update([s.strip().lower() for s in value.split(",") if s.strip()])
    return [{"skill": skill.title(), "count": count} for skill, count in counter.most_common(10)]
