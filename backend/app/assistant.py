import os
import httpx

async def answer(message: str, context: dict) -> str:
    if os.getenv("USE_OLLAMA", "false").lower() == "true":
        try:
            prompt = f"You are JobIntel AI. Be concise and actionable. Context: {context}\nQuestion: {message}"
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(f"{os.getenv('OLLAMA_URL','http://localhost:11434')}/api/generate", json={
                    "model": os.getenv("OLLAMA_MODEL", "llama3.2:3b"), "prompt": prompt, "stream": False
                })
                r.raise_for_status()
                return r.json().get("response", "")
        except Exception:
            pass
    m = message.lower()
    if "improve" in m or "learn" in m:
        return "Focus first on Kafka, Airflow and Terraform, then strengthen German toward B1. Build each skill into JobIntel so the learning becomes portfolio evidence."
    if "ats" in m or "cv" in m:
        return "Use the ATS Readiness view for structure and parsing, then tailor a separate CV version to each role using the job-specific match and missing-keyword report."
    if "interview" in m:
        return "Prioritize jobs above your current match threshold, close the top skill gaps, and prepare system-design plus role-specific questions before the interview."
    return "I can help with CV improvement, ATS readiness, skill gaps, job matching, application follow-ups and interview preparation."
