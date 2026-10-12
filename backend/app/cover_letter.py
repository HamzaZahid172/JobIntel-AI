import os
import re
from datetime import date
from io import BytesIO

import httpx
from docx import Document
from docx.shared import Pt

from .intelligence import profile_role_families, rank_cv_skills


def cover_letter_role_family(title: str) -> str:
    value = title.lower()
    if any(term in value for term in ("test", "qa ", "quality assurance", "sdet", "automation engineer")):
        return "qa"
    if any(term in value for term in ("data engineer", "etl", "analytics engineer", "data infrastructure")):
        return "data"
    if any(term in value for term in ("backend", "fullstack", "full stack", "python", "ai engineer", "ml engineer")):
        return "backend"
    return "general"


def _cv_evidence(cv_text: str, skills: list[str], limit: int = 2) -> list[str]:
    """Quote facts from the submitted CV; never manufacture a numeric achievement."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", cv_text or "")
    selected = []
    for sentence in sentences:
        sentence = re.sub(r"\s+", " ", sentence).strip(" •-*")
        if not (35 <= len(sentence) <= 260):
            continue
        if "@" in sentence or "http" in sentence.lower():
            continue
        lower = sentence.lower()
        if any(skill.lower() in lower for skill in skills) and any(
            verb in lower for verb in (
                "built", "developed", "automated", "implemented", "worked",
                "managed", "created", "designed", "improved", "reduced",
                "tested", "experience", "pipeline", "project"
            )
        ):
            if sentence not in selected:
                selected.append(sentence)
        if len(selected) >= limit:
            break
    return selected


def _verify_generated_letter(text: str, cv_text: str, job, user) -> bool:
    """Minimum guardrail: role/company/name and every numeric claim must be grounded."""
    if len(text.split()) < 140 or job.company.lower() not in text.lower() or (
        job.title.lower() not in text.lower()
    ) or user.display_name.lower() not in text.lower():
        return False
    factual_source = cv_text + " " + (job.description or "")
    source_numbers = set(re.findall(r"\b\d{2,}\b", factual_source))
    proposed_numbers = set(re.findall(r"\b\d{2,}\b", text))
    return proposed_numbers <= source_numbers


async def generate_cover_letter_text(cv_text: str, job, match: dict, user) -> tuple[str, str]:
    matched = match.get("matched_required_skills") or match.get("matched_skills") or []
    cv_skills = [row["skill"] for row in rank_cv_skills(cv_text, limit=12)]
    verified = [skill for skill in matched if skill.lower() in cv_text.lower()]
    family = cover_letter_role_family(job.title)
    themes = {
        "qa": "reliable test automation, regression coverage and practical quality engineering",
        "data": "data acquisition, transformation, validation and maintainable data pipelines",
        "backend": "maintainable backend services, API integration and reliable software delivery",
        "general": "reliable engineering, collaborative delivery and solving practical technical problems",
    }
    evidence = _cv_evidence(cv_text, verified or cv_skills, limit=3)
    if os.getenv("USE_OLLAMA", "false").lower() == "true":
        try:
            prompt = f"""Draft a professional, tailored cover letter in English, 180-280 words.
Use ONLY evidence present in the CV below. No invented metrics, company history,
commercial experience, credentials, language levels or work authorization.
Personal projects must be called personal projects, never professional employment.
Do not claim any missing skill. Mention exact job title, company and candidate name.
Tone: precise, natural, experienced, no marketing clichés, no placeholders.
Relevant requirement evidence: {', '.join(verified[:8])}
Verbatim CV evidence: {evidence}
Emphasis: {themes[family]}

Candidate: {user.display_name}, {user.email}
Target: {job.title} at {job.company}
CV:
{cv_text[:11000]}
Job description:
{(job.description or '')[:9000]}
"""
            async with httpx.AsyncClient(timeout=65) as client:
                response = await client.post(
                    f"{os.getenv('OLLAMA_URL', 'http://localhost:11434')}/api/generate",
                    json={"model": os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
                          "prompt": prompt, "stream": False,
                          "options": {"temperature": 0.2}},
                )
                response.raise_for_status()
                draft = response.json().get("response", "").strip()
                if _verify_generated_letter(draft, cv_text, job, user):
                    return draft, "ollama-reviewed"
        except (httpx.HTTPError, ValueError, KeyError):
            pass

    # Deterministic evidence-only fallback when local AI is unavailable.
    strengths = ", ".join(verified[:5] or cv_skills[:5])
    evidence_text = ""
    if evidence:
        evidence_text = (
            "\n\nOne directly relevant detail from my CV is: "
            + " ".join(evidence[:2])
        )
    text = (
        f"Dear Hiring Team at {job.company},\n\n"
        f"I would like to apply for the {job.title} position. "
        f"The opportunity is relevant to my background in {themes[family]}. "
        f"I am particularly interested in contributing to the responsibilities "
        f"described for this role.\n\n"
        f"My documented technical experience includes {strengths or 'software development and technical problem solving'}. "
        "I aim to make engineering work dependable, understandable and useful "
        "to the people who rely on it."
        + evidence_text +
        f"\n\nFor the {job.title} role, I would focus on the areas where my "
        "existing experience aligns with your requirements, while being "
        "transparent about technologies I would need to learn. "
        f"I would welcome a conversation about how I could contribute to {job.company}.\n\n"
        "Thank you for your time and consideration.\n\n"
        f"Kind regards,\n{user.display_name}\n{user.email}"
    )
    return text, "evidence-template"


def build_cover_letter_docx(text: str, user, job) -> bytes:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(10.5)

    doc.add_paragraph(user.display_name)
    doc.add_paragraph(user.email)
    doc.add_paragraph(date.today().strftime("%d %B %Y"))
    doc.add_paragraph()
    heading = doc.add_paragraph()
    run = heading.add_run(f"Application for {job.title} at {job.company}")
    run.bold = True

    for block in re.split(r"\n\s*\n", text.strip()):
        paragraph = doc.add_paragraph(block.strip())
        paragraph.paragraph_format.space_after = Pt(8)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")[:80] or "cover_letter"
