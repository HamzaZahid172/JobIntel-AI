from types import SimpleNamespace
from datetime import datetime

from app.ats_simulator import ats_review
from app.job_acquisition import opportunity_assessment


def test_ats_simulation_identifies_missing_required_skills_without_pretending_certification():
    cv = ("Experience building Python APIs and SQL workflows with FastAPI. "
          "Skills: Python, SQL, FastAPI. Education: Bachelor's in computer science. "
          "Email: engineer@example.com.")
    details = {
        "overall_score": 75,
        "requirements": {"required_skills": ["Python", "FastAPI", "Kafka"],
                         "preferred_skills": ["Docker"]},
        "matched_required_skills": ["Python", "FastAPI"],
        "hard_blockers": []
    }
    result = ats_review(cv, details)
    assert result["pass_guarantee"] is False
    assert result["required_skill_coverage"] == 67
    assert "Kafka" in result["required_skills_missing"]
    assert "Python" in result["required_skills_found"]
    assert result["cv_parse_checks"]["contact_email"]


def test_product_manager_cannot_get_apply_now_from_keyword_overlap():
    job = SimpleNamespace(
        title="Technical Product Manager", source="Arbeitnow", job_types="Full-time",
        posted_at=datetime.utcnow()
    )
    report = {"overall_score": 97, "role_score": 98, "hard_blockers": []}
    result = opportunity_assessment(job, report)
    assert result["decision"] == "Skip"
    assert result["score"] <= 34
