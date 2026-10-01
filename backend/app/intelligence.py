import re
from collections import Counter

SKILLS = [
    "python", "typescript", "javascript", "java", "sql", "fastapi", "node.js",
    "postgresql", "mysql", "aws", "azure", "gcp", "docker", "kubernetes",
    "kafka", "airflow", "terraform", "spark", "dbt", "react", "playwright",
    "selenium", "cypress", "webdriverio", "puppeteer", "pandas", "rest",
    "graphql", "spring boot", "linux", "git", "github actions", "gitlab ci",
    "jenkins", "prometheus", "grafana", "redis", "mongodb", "microservices",
    "pytest", "etl", "web scraping", "data pipelines", "data validation",
    "api testing", "e2e testing", "pdf parsing", "ci/cd",
]

PROGRAMMING_SKILLS = {"python", "typescript", "javascript", "java", "sql"}
PRIMARY_SKILL_BOOST = {
    "python": 12,
    "typescript": 11,
    "javascript": 10,
    "java": 6,
    "sql": 6,
    "playwright": 7,
    "fastapi": 6,
    "node.js": 6,
    "cypress": 5,
    "selenium": 5,
    "webdriverio": 5,
    "puppeteer": 5,
    "rest": 5,
    "docker": 4,
    "aws": 4,
    "kubernetes": 4,
}

ROLE_FAMILIES = {
    "software_backend": (
        "software engineer", "software developer", "backend", "back-end",
        "application engineer", "python developer", "python engineer",
        "node developer", "node.js", "api engineer", "microservices",
    ),
    "automation_qa": (
        "qa engineer", "quality engineer", "test engineer", "automation engineer",
        "test automation", "sdet", "software test", "qa automation",
    ),
    "data_engineering": (
        "data engineer", "data engineering", "data platform", "analytics engineer",
        "etl", "data integration", "data infrastructure", "data pipeline",
    ),
    "ai_ml": (
        "ai engineer", "artificial intelligence", "machine learning engineer",
        "ml engineer", "genai", "generative ai", "llm engineer",
    ),
    "frontend_fullstack": (
        "frontend", "front-end", "fullstack", "full stack", "react developer",
        "javascript developer", "typescript developer", "web developer",
    ),
    "devops_platform": (
        "devops", "platform engineer", "cloud engineer", "site reliability",
        "sre", "infrastructure engineer", "systems engineer", "system engineer",
    ),
}

NON_TARGET_TITLE_TERMS = (
    "account manager", "account executive", "sales", "marketing", "recruiter",
    "talent acquisition", "product manager", "project manager", "finance manager",
    "fraud analyst", "risk analyst", "business development", "customer success",
    "operations manager", "store manager",
)

ATS_SECTIONS = ["experience", "education", "skills", "projects"]


def _skill_pattern(skill: str) -> str:
    # Use word-character boundaries only. Treating "." as a forbidden boundary
    # caused skills at sentence endings (for example "Airflow.") to be missed.
    return rf"(?<!\w){re.escape(skill)}(?!\w)"


def extract_skills(text: str) -> list[str]:
    lower = text.lower()
    return [skill for skill in SKILLS if re.search(_skill_pattern(skill), lower)]


def skill_counts(text: str) -> Counter:
    lower = text.lower()
    counts = Counter()
    for skill in SKILLS:
        count = len(re.findall(_skill_pattern(skill), lower))
        if count:
            counts[skill] = count
    return counts


def profile_role_families(cv_text: str) -> list[str]:
    lower = cv_text.lower()
    families = []
    for family, terms in ROLE_FAMILIES.items():
        if any(term in lower for term in terms):
            families.append(family)

    skills = set(extract_skills(cv_text))
    if {"python", "fastapi", "node.js", "rest", "microservices"} & skills:
        families.append("software_backend")
    if {"playwright", "selenium", "cypress", "webdriverio", "api testing"} & skills:
        families.append("automation_qa")
    if {"etl", "pandas", "data pipelines", "web scraping", "data validation"} & skills:
        families.append("data_engineering")
    if {"react", "javascript", "typescript"} & skills:
        families.append("frontend_fullstack")
    if {"docker", "kubernetes", "aws", "terraform"} & skills:
        families.append("devops_platform")

    return list(dict.fromkeys(families))


def classify_job_role(title: str, description: str = "") -> list[str]:
    title_l = (title or "").lower()
    description_l = (description or "").lower()
    families = []

    for family, terms in ROLE_FAMILIES.items():
        title_hit = any(term in title_l for term in terms)
        description_hit = any(term in description_l[:3500] for term in terms)
        if title_hit or (family in {"data_engineering", "ai_ml"} and description_hit):
            families.append(family)

    return list(dict.fromkeys(families))


def is_target_technical_role(title: str, description: str = "") -> bool:
    title_l = (title or "").lower()
    families = classify_job_role(title, description)
    if any(term in title_l for term in NON_TARGET_TITLE_TERMS) and not families:
        return False
    return bool(families)


def rank_cv_skills(cv_text: str, job_skill_strings: list[str] | None = None, limit: int = 10) -> list[dict]:
    counts = skill_counts(cv_text)
    market = Counter()

    for value in job_skill_strings or []:
        market.update([s.strip().lower() for s in value.split(",") if s.strip()])

    ranked = []
    for skill, count in counts.items():
        score = count * 3 + PRIMARY_SKILL_BOOST.get(skill, 0)
        if skill in PROGRAMMING_SKILLS:
            score += 5
        ranked.append({
            "skill": skill,
            "cv_count": count,
            "market_count": market.get(skill, 0),
            "_score": score,
        })

    ranked.sort(key=lambda item: (item["_score"], item["cv_count"], item["market_count"]), reverse=True)
    for item in ranked:
        item.pop("_score", None)
    return ranked[:limit]


def ats_check(text: str) -> dict:
    lower = text.lower()
    skills = extract_skills(text)
    sections = sum(1 for section in ATS_SECTIONS if section in lower)
    contact_ok = bool(re.search(r"[\w.+'-]+@[\w.-]+\.\w+", text)) and bool(
        re.search(r"\+?\d[\d\s()\-]{7,}", text)
    )
    word_count = len(text.split())
    length_ok = 350 <= word_count <= 1800
    bullets = len(re.findall(r"(?:^|\n)\s*[•\-*]", text))
    quantified = len(re.findall(r"\b\d+(?:[.,]\d+)?%?\+?\b", text))

    raw = 0
    raw += 20 if word_count >= 250 else 10
    raw += sections * 5
    raw += 10 if contact_ok else 0
    raw += 10 if length_ok else 4
    raw += min(15, len(skills))
    raw += min(15, bullets * 2)
    raw += min(10, quantified * 2)

    # Generic ATS-readiness is intentionally capped below 100 because no universal
    # ATS can certify a CV as perfect. Job-specific matching is reported separately.
    score = min(95, raw)

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
    if quantified < 3:
        suggestions.append("Add measurable impact to more experience bullets.")

    return {
        "score": score,
        "status": "ATS Ready" if score >= 80 else "Needs Improvement",
        "score_type": "Generic ATS Readiness",
        "format_ok": True,
        "sections_complete": f"{sections}/4",
        "keyword_coverage": min(95, 45 + len(skills) * 3),
        "skills_detected": skills,
        "top_skills": rank_cv_skills(text, limit=10),
        "role_families": profile_role_families(text),
        "suggestions": suggestions or ["Strong ATS baseline. Tailor keywords to each target job."],
    }


def match_cv_to_job(cv_text: str, job_description: str, job_title: str = "") -> dict:
    cv_skills = set(extract_skills(cv_text))
    job_skills = set(extract_skills(job_description))
    matched = sorted(cv_skills & job_skills)
    missing = sorted(job_skills - cv_skills)

    if job_skills:
        coverage = len(matched) / len(job_skills)
        reliability = min(1.0, len(job_skills) / 4)
        skill_score = round(coverage * 100 * reliability + min(len(matched), 3) * 4)
        skill_score = min(100, skill_score)
    else:
        skill_score = 35

    cv_families = set(profile_role_families(cv_text))
    job_families = set(classify_job_role(job_title, job_description))
    overlap = cv_families & job_families

    if overlap:
        role_score = 95
    elif job_families and cv_families:
        role_score = 45
    elif job_families:
        role_score = 55
    else:
        role_score = 20

    title_lower = (job_title or "").lower()
    if any(term in title_lower for term in NON_TARGET_TITLE_TERMS) and not overlap:
        role_score = 5

    cv_lower = cv_text.lower()
    experience_score = 90 if re.search(r"7\+?\s*years|senior", cv_lower) else 72
    language_score = 78
    if "german" in job_description.lower():
        language_score = 72 if "german" in cv_lower else 45

    overall = round(
        skill_score * 0.45
        + role_score * 0.30
        + experience_score * 0.15
        + language_score * 0.10
    )

    if role_score < 30:
        overall = min(overall, 45)
    if len(job_skills) <= 1:
        overall = min(overall, 68)
    if not matched and job_skills:
        overall = min(overall, 55)

    readiness = "Strong" if overall >= 80 else "Good" if overall >= 65 else "Low"

    return {
        "overall_score": overall,
        "skill_score": skill_score,
        "role_score": role_score,
        "experience_score": experience_score,
        "language_score": language_score,
        "matched_skills": matched,
        "missing_skills": missing,
        "job_skills": sorted(job_skills),
        "profile_role_families": sorted(cv_families),
        "job_role_families": sorted(job_families),
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
