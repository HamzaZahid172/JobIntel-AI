import os

import httpx


async def answer(message: str, context: dict) -> str:
    if os.getenv("USE_OLLAMA", "false").lower() == "true":
        try:
            prompt = (
                "You are JobIntel AI. Use only the supplied career context where possible. "
                "Be concise, transparent and actionable. "
                f"Context: {context}\nQuestion: {message}"
            )
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{os.getenv('OLLAMA_URL', 'http://localhost:11434')}/api/generate",
                    json={
                        "model": os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
                        "prompt": prompt,
                        "stream": False,
                    },
                )
                response.raise_for_status()
                return response.json().get("response", "")
        except Exception:
            pass

    m = message.lower()
    cv_uploaded = context.get("cv_uploaded", False)
    tracked = context.get("tracked_live_jobs", 0)
    gaps = context.get("top_missing_skills") or []
    matches = context.get("top_matches") or []

    if not cv_uploaded and ("improve" in m or "match" in m or "cv" in m or "ats" in m):
        return (
            f"I currently have {tracked} live jobs stored, but no CV profile. "
            "Upload your CV from ATS CV Check first; I can then calculate real gaps and matches."
        )

    if "improve" in m or "learn" in m or "gap" in m:
        if gaps:
            return (
                "Your strongest current market gaps are "
                + ", ".join(gaps[:4])
                + ". Prioritize the first one, build a small portfolio feature with it, "
                  "then refresh the market and compare your match scores again."
            )
        return "I do not see a strong repeated skill gap in the currently tracked jobs."

    if "match" in m or "jobs" in m:
        if matches:
            rendered = "; ".join(
                f"{row['title']} at {row['company']} ({round(row['match'])}% match)"
                for row in matches[:3] if row.get("match") is not None
            )
            return f"Your strongest current matches are: {rendered}." if rendered else "Upload your CV to score the current jobs."
        return "No current jobs are stored yet. Use Refresh Current Jobs first."

    if "ats" in m or "cv" in m:
        return (
            "ATS Readiness checks parseability, standard sections, contact readability and skill keywords. "
            "Then JobIntel separately compares your CV with each live job description."
        )

    if "interview" in m:
        return (
            "Use your highest current match roles first. Review their missing skills and job description, "
            "then prepare project evidence, system-design questions and role-specific examples."
        )

    return (
        f"I currently have {tracked} live relevant jobs and {context.get('applications', 0)} tracked applications. "
        "Ask me about your strongest matches, CV/ATS readiness, market skill gaps or interview preparation."
    )
