from types import SimpleNamespace

from app.cover_letter import build_cover_letter_docx, safe_filename


def test_safe_filename():
    assert safe_filename("Hamza / Backend Engineer: Cover Letter") == "Hamza_Backend_Engineer_Cover_Letter"


def test_cover_letter_docx_bytes():
    user = SimpleNamespace(display_name="Test User", email="test@example.com")
    job = SimpleNamespace(title="Backend Engineer", company="Example GmbH")
    content = build_cover_letter_docx(
        "Dear Hiring Team,\n\nI am applying for the Backend Engineer role.\n\nKind regards,\nTest User",
        user,
        job,
    )
    assert content[:2] == b"PK"
    assert len(content) > 1000


def test_role_specific_letter_uses_actual_cv_evidence_and_company(monkeypatch):
    import asyncio
    from app.cover_letter import generate_cover_letter_text, cover_letter_role_family
    monkeypatch.setenv("USE_OLLAMA", "false")
    cv = ("Built and maintained Python ETL pipelines for data extraction and validation. "
          "Designed SQL transformation workflows to serve client reporting requirements. "
          "Tested data ingestion using Python and Pandas.")
    job = SimpleNamespace(title="Data Engineer (m/f/d)", company="Example GmbH",
                          location="Berlin", description="Python SQL ETL")
    user = SimpleNamespace(display_name="Test Candidate", email="candidate@example.com")
    text, mode = asyncio.run(generate_cover_letter_text(
        cv, job, {"matched_required_skills":["python", "sql", "etl"]}, user))
    assert mode == "evidence-template"
    assert "Data Engineer (m/f/d)" in text
    assert "Example GmbH" in text
    assert "data acquisition" in text
    assert "Python" in text or "python" in text
    assert cover_letter_role_family("QA Automation Engineer") == "qa"
    assert cover_letter_role_family("Backend Python Engineer") == "backend"


def test_unverified_numeric_claims_fail_llm_guard():
    from app.cover_letter import _verify_generated_letter
    user=SimpleNamespace(display_name="Test User",email="user@example.com")
    job=SimpleNamespace(title="Backend Developer",company="Example GmbH",
                        description="Python REST API experience")
    draft=("I am applying for the Backend Developer position at Example GmbH. "
           "I have 999 years of professional software engineering experience. "*20+
           "Sincerely, Test User")
    assert not _verify_generated_letter(draft,"I have worked with Python and REST APIs",job,user)
