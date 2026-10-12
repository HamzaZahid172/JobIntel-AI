from datetime import date
from types import SimpleNamespace

import pytest

from app.interview_practice import answer_feedback, question_bank
from app.conversion_analytics import application_analytics, role_family


def test_practice_questions_are_role_specific_and_deterministic():
    cv="Python FastAPI Cypress SQL API testing experience"
    data=question_bank("Data Engineer", "Python SQL data pipelines", cv)
    qa=question_bank("QA Automation Engineer","Cypress API testing", cv)
    assert len(data)==6
    assert len(qa)==6
    assert "ETL" in data[0]["question"]
    assert "regression" in qa[0]["question"]
    assert all(q["instructions"].startswith("Give a real example") for q in qa)
    assert any("python" in (x.lower() for x in data[0]["relevant_job_skills"]) for x in ["python"])


def test_feedback_tracks_structure_not_fake_hiring_probability():
    question=question_bank("Backend Python Engineer","Python FastAPI", "Python FastAPI")[0]
    result=answer_feedback(question,
        "I built a Python API for a specific project, tested its error paths and verified the results "
        "after reviewing failures with colleagues in our team.", "Python FastAPI")
    assert result["word_count"]>=20
    assert result["personal_contribution_clear"]
    assert result["outcome_described"]
    assert "probability" not in str(result).lower()
    with pytest.raises(ValueError):
        answer_feedback(question,"short", "Python")


def test_conversion_counts_by_role_and_cv_with_small_sample_warning():
    def app(role,status,version,url=""):
        return SimpleNamespace(role=role,status=status,cv_version=version,url=url)
    apps=[
        app("QA Automation Engineer","Rejected","QA","https://jobs.ashbyhq.com/a"),
        app("Backend Developer","Interview","Backend","https://jobs.ashbyhq.com/b"),
        app("Data Engineer","Applied","Data","https://boards.greenhouse.io/c"),
    ]
    results=application_analytics(apps)
    assert results["overall"]["applications"]==3
    assert results["overall"]["interviews_or_later"]==1
    assert results["overall"]["rejected"]==1
    assert results["overall"]["sample_warning"] is True
    assert results["by_cv_version"]["QA"]["rejected"]==1
    assert role_family("QA Automation Engineer")=="QA Automation"
    assert results["by_source"]["jobs.ashbyhq.com"]["applications"]==2
