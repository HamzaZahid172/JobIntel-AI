from datetime import datetime, date
from types import SimpleNamespace

from app.pre_application_review import job_role_family, pre_application_review


def test_three_cv_tracks_and_fallback():
    assert job_role_family("Senior QA Automation Engineer") == "qa"
    assert job_role_family("Python Data Engineer") == "data"
    assert job_role_family("Backend Python Engineer") == "backend"
    assert job_role_family("Business Analyst") == "general"


def test_review_never_claims_hiring_probability_or_work_permission():
    job = SimpleNamespace(title="QA Automation Engineer", posted_at=datetime(2026, 10, 12))
    cv = SimpleNamespace(filename="qa.pdf",
        text="Experience: Playwright QA automation. Skills: Python. Contact dev@example.com")
    report = {"overall_score": 95, "hard_blockers": [],
              "missing_required_skills": [], "location_score": 100}
    result = pre_application_review(job, cv, report, selected_role="qa",
                                    saved_cv=True, today=date(2026, 10, 14))
    assert result["technical_match_percent"] == 95
    assert "not probability" in result["score_meaning"]
    assert result["human_confirmation_required"]
    assert not result["employer_submission_verified"]
    assert any(x["code"] == "work_permission" for x in result["checks"])
    assert result["status"] == "Review before applying"


def test_wrong_cv_and_old_vacancy_are_explicitly_flagged():
    job = SimpleNamespace(title="Data Engineer", posted_at=datetime(2026, 1, 2))
    cv = SimpleNamespace(filename="general.pdf", text="Experience with Python")
    report = {"overall_score": 88, "hard_blockers": [],
              "missing_required_skills": ["Kafka"], "location_score": 45}
    result = pre_application_review(job, cv, report, selected_role="general",
                                    saved_cv=False, today=date(2026, 10, 14))
    codes = {row["code"] for row in result["checks"]}
    assert {"role_cv", "original_attachment", "skills_to_check",
            "location_unknown", "vacancy_open"} <= codes


def test_confirmed_language_blocker_keeps_application_not_recommended():
    job = SimpleNamespace(title="Backend Engineer", posted_at=None)
    cv = SimpleNamespace(filename="backend.pdf", text="Experience Python FastAPI dev@example.com")
    report = {"overall_score": 95, "hard_blockers": ["German C1 required; CV says A2"],
              "missing_required_skills": []}
    result = pre_application_review(job, cv, report, selected_role="backend",
                                    saved_cv=True)
    assert "blockers" in result["status"]
    assert result["technical_match_percent"] == 95
