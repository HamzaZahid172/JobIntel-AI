"""CV-grounded interview practice. Not a prediction of hiring decisions."""
import re

from .intelligence import extract_skills


def question_bank(title: str, description: str, cv_text: str) -> list[dict]:
    relevant = sorted(set(extract_skills(description)) & set(extract_skills(cv_text)))
    role=(title or "").lower()
    technical = []
    if "qa" in role or "test" in role or "automation" in role:
        technical=[
            ("Walk through an automated regression test you designed and maintained.",
             ["test", "automation", "validation"]),
            ("How do you identify flaky tests and investigate a failed CI run?",
             ["testing", "debugging", "ci"]),
            ("Describe a difficult UI or API testing issue and how you resolved it.",
             ["api", "test", "debugging"]),
        ]
    elif "data" in role or "etl" in role:
        technical=[
            ("Explain a data acquisition or ETL pipeline you worked on.",
             ["data", "pipeline", "validation"]),
            ("How would you validate data quality and handle duplicate records?",
             ["data", "validation", "sql"]),
            ("How do you investigate a slow SQL query or failed ingestion?",
             ["sql", "data", "debugging"]),
        ]
    else:
        technical=[
            ("Describe a backend service or API you built and the architecture decisions you made.",
             ["api", "backend", "architecture"]),
            ("How do you test reliability and handle errors in a production service?",
             ["test", "errors", "reliability"]),
            ("Describe a difficult engineering problem, your contribution and measurable results.",
             ["design", "problem", "outcome"]),
        ]
    shared=[
        ("Why does this particular company and role interest you?",
         ["company", "role", "motivation"]),
        ("Tell me about a project you personally contributed to. What was your part?",
         ["project", "contribution", "result"]),
        ("Describe a technical disagreement and how you collaborated to resolve it.",
         ["collaboration", "decision", "result"]),
    ]
    result=[]
    for index,(question,keys) in enumerate([*technical,*shared]):
        result.append({
            "id": index, "question": question, "topic": "Technical" if index<3 else "Behavioral",
            "relevant_job_skills": relevant[:5], "coaching_prompts": keys,
            "instructions": "Give a real example with context, your exact contribution and outcome. Do not invent experience.",
        })
    return result


def answer_feedback(question: dict, response: str, cv_text: str) -> dict:
    text=(response or "").strip()
    if not 20<=len(text)<=6000:
        raise ValueError("Answer must contain 20–6000 characters.")
    words=re.findall(r"\b[\w\-]+\b",text.lower())
    relevant=[skill for skill in question.get("relevant_job_skills",[])
              if re.search(r"\b"+re.escape(skill.lower())+r"\b", text.lower())]
    contains_result=bool(re.search(
        r"\b(result|outcome|reduced|improved|delivered|achieved|measured|saved|tested|fixed|because)\b",
        text.lower()))
    mentions_contribution=bool(re.search(
        r"\b(i|my|personally|we)\s+(implemented|built|tested|designed|worked|automated|developed|led|used|created|fixed|investigated)\b",
        text.lower()))
    tips=[]
    if len(words)<55:
        tips.append("Add a concrete example: context, the specific task, your action and result.")
    if not mentions_contribution:
        tips.append("Explain your personal contribution clearly; avoid only describing the team.")
    if not contains_result:
        tips.append("Include a truthful outcome or explain what changed and how you verified it.")
    if question.get("relevant_job_skills") and not relevant:
        tips.append("Where appropriate, connect your answer to a required job skill you actually know.")
    if not tips:
        tips.append("Strong structure; practice saying this answer naturally and ensure every claim is accurate.")
    return {
        "feedback":tips,
        "word_count":len(words),
        "job_skills_mentioned":relevant,
        "personal_contribution_clear":mentions_contribution,
        "outcome_described":contains_result,
        "disclaimer":"Coaching feedback, not an employer score. Verify every example against your experience.",
    }
