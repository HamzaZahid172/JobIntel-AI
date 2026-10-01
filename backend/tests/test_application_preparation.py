from types import SimpleNamespace

from app.application_preparation import (
    build_application_package_payload,
    build_screening_drafts,
    build_validation,
)


def _job():
    return SimpleNamespace(
        id=1,
        title="Backend Software Engineer",
        company="Example GmbH",
        location="Berlin, Germany",
        source="Ashby",
        url="https://example.com/job",
    )


def _user():
    return SimpleNamespace(display_name="Test User", email="test@example.com")


def _cv():
    return SimpleNamespace(
        id=3,
        filename="cv.pdf",
        text="Senior Software Engineer 7+ years Python FastAPI Docker REST.",
    )


def _match():
    return {
        "overall_score": 86,
        "role_score": 95,
        "matched_required_skills": ["python", "fastapi", "docker", "rest"],
        "matched_skills": ["python", "fastapi", "docker", "rest"],
        "hard_blockers": [],
        "requirements": {"languages": []},
        "score_breakdown": {
            "role_alignment": 95,
            "required_skills": 90,
            "preferred_skills": 80,
            "experience": 100,
            "language": 100,
            "location": 100,
        },
    }


def test_application_preparation_requires_user_specific_answers():
    answers = build_screening_drafts(_cv().text, _job(), _match(), _user())
    status = {row["key"]: row["status"] for row in answers}
    assert status["why_role"] == "draft"
    assert status["work_authorization"] == "needs_user_input"
    assert status["salary_expectation"] == "needs_user_input"
    assert status["availability"] == "needs_user_input"


def test_application_package_stays_needs_review_until_user_fields_complete():
    payload = build_application_package_payload(
        job=_job(),
        cv=_cv(),
        user=_user(),
        match_report=_match(),
        cover_letter_text="Dear Hiring Team...",
        cover_letter_generator="template",
        minimum_match=70,
    )
    assert payload["validation"]["passed"] is True
    assert payload["status"] == "Needs Review"
    assert "work_authorization" in payload["unresolved_fields"]


def test_validation_rejects_below_threshold():
    match = _match()
    match["overall_score"] = 62
    validation = build_validation(match, 70)
    assert validation["passed"] is False
