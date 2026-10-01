import os

import httpx


def _model_matches(installed_name: str, requested: str) -> bool:
    installed = (installed_name or "").lower()
    requested = (requested or "").lower()
    return installed == requested or installed.startswith(requested + ":")


async def assistant_status() -> dict:
    enabled = os.getenv("USE_OLLAMA", "false").lower() == "true"
    model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

    if not enabled:
        return {
            "mode": "rules",
            "state": "disabled",
            "ollama_enabled": False,
            "ollama_online": False,
            "model_ready": False,
            "model": model,
        }

    try:
        async with httpx.AsyncClient(timeout=4) as client:
            response = await client.get(f"{base_url}/api/tags")
            response.raise_for_status()
            payload = response.json()
        installed = [
            item.get("name") or item.get("model") or ""
            for item in payload.get("models", [])
        ]
        ready = any(_model_matches(name, model) for name in installed)
        return {
            "mode": "ollama" if ready else "rules",
            "state": "ready" if ready else "model_downloading",
            "ollama_enabled": True,
            "ollama_online": ready,
            "ollama_server_online": True,
            "model_ready": ready,
            "model": model,
            "installed_models": installed,
        }
    except Exception as exc:
        return {
            "mode": "rules",
            "state": "server_offline",
            "ollama_enabled": True,
            "ollama_online": False,
            "ollama_server_online": False,
            "model_ready": False,
            "model": model,
            "error": type(exc).__name__,
        }


async def answer(message: str, context: dict) -> dict:
    status = await assistant_status()
    if status["ollama_online"]:
        try:
            prompt = """You are the JobIntel AI Career Assistant.
Use the supplied user/job-market context as your source of truth.
Do not invent employers, scores, application outcomes or missing skills.
If the user asks about a job, explain fit using the context.
If information is not in context, say so and suggest the next action.
Be concise, practical and career-focused.

Context:
""" + str(context) + """

User question:
""" + message
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{os.getenv('OLLAMA_URL', 'http://localhost:11434')}/api/generate",
                    json={
                        "model": status["model"],
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.2},
                    },
                )
                response.raise_for_status()
                generated = response.json().get("response", "").strip()
                if generated:
                    return {
                        "answer": generated,
                        "mode": "ollama",
                        "model": status["model"],
                    }
        except Exception:
            pass

    m = message.lower()
    tracked = context.get("tracked_live_jobs", 0)
    skills = context.get("top_profile_skills") or []
    gaps = context.get("top_missing_skills") or []
    matches = context.get("top_matches") or []

    if any(term in m for term in ("xing", "stepstone", "scrape", "scraping")):
        text = (
            "For XING and StepStone, use an authorized integration or import individual jobs into JobIntel. "
            "For broader Germany coverage, prefer public feeds and direct employer ATS sources."
        )
    elif not context.get("cv_uploaded") and any(term in m for term in ("improve", "match", "cv", "ats")):
        text = f"I have {tracked} live jobs stored, but no CV profile. Upload your CV first so I can calculate real matches and gaps."
    elif any(term in m for term in ("improve", "learn", "gap")):
        text = (
            "Your strongest current gaps are " + ", ".join(gaps[:4]) + "."
            if gaps
            else "I do not see a repeated skill gap in your current CV-relevant job set."
        )
    elif any(term in m for term in ("match", "jobs", "apply")):
        rendered = "; ".join(
            f"{row['title']} at {row['company']} ({round(row['match'])}% match)"
            for row in matches[:5]
            if row.get("match") is not None
        )
        text = f"Your strongest current matches are: {rendered}." if rendered else "No scored matches are available yet."
    elif "skill" in m:
        text = (
            f"Your strongest CV skills currently detected are: {', '.join(skills[:8])}."
            if skills
            else "Upload your CV to rank your skills."
        )
    elif "interview" in m:
        text = "Prioritize your highest-match roles, review missing skills, and prepare project evidence plus system-design and role-specific examples."
    else:
        text = (
            f"I have {tracked} CV-relevant jobs and {context.get('applications', 0)} tracked applications. "
            "Ask me about top matches, ATS readiness, your strongest skills, skill gaps, applications or interview preparation."
        )

    return {
        "answer": text,
        "mode": "rules",
        "assistant_state": status.get("state"),
    }
