from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.job_acquisition import (
    cv_tailoring_draft,
    followup_draft,
    followup_due,
    opportunity_assessment,
)
from app.models import Application
from app.sources import fetch_remotive, remotive_germany_eligible


def test_opportunity_score_prefers_fresh_eligible_employer_job():
    job = SimpleNamespace(
        id=7, title="Backend Python Engineer", company="Example",
        source="Greenhouse", job_types="", posted_at=datetime.utcnow(),
    )
    report = {"overall_score": 88, "role_score": 90, "hard_blockers": []}
    result = opportunity_assessment(job, report)
    assert result["decision"] == "Apply Now"
    assert result["direct_employer"]
    assert result["score"] >= 80


def test_opportunity_hard_blocker_forces_skip():
    job = SimpleNamespace(
        id=7, title="Backend Python Engineer", source="Greenhouse",
        job_types="", posted_at=datetime.utcnow(),
    )
    result = opportunity_assessment(
        job, {"overall_score": 98, "role_score": 90, "hard_blockers": ["German C1 required"]}
    )
    assert result["decision"] == "Skip"
    assert result["score"] < 40


def test_followup_only_after_seven_days_and_not_repeated_too_soon():
    app = Application(
        id=2, company="Acme", role="Data Engineer", status="Applied",
        applied_date=date.today() - timedelta(days=8), notes="",
    )
    assert followup_due(app)
    draft = followup_draft(app, "Candidate Name")
    assert "Data Engineer" in draft["body"]
    assert draft["requires_approval"]
    app.notes = "Follow-up sent: " + date.today().isoformat()
    assert not followup_due(app)
    app.status = "Rejected"
    assert not followup_due(app)


def test_cv_tailoring_only_uses_evidenced_skills():
    job = SimpleNamespace(id=1, title="Backend Engineer", company="Example")
    report = {
        "matched_required_skills": ["Python", "FastAPI"],
        "missing_required_skills": ["Kafka"],
    }
    result = cv_tailoring_draft(
        "Developed Python services using FastAPI for API integrations.\nWorked with SQL databases.",
        job, report,
    )
    assert "Python" in result["suggested_summary"]
    assert "Kafka" not in result["suggested_summary"]
    assert "Kafka" in result["missing_skills_do_not_claim"]
    assert result["review_required"]


def test_remotive_germany_eligibility_is_not_usa_only():
    assert remotive_germany_eligible("Germany")
    assert remotive_germany_eligible("Worldwide")
    assert remotive_germany_eligible("Europe")
    assert not remotive_germany_eligible("USA only")


def test_remotive_api_normalizes_and_attributes_source():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"jobs": [
                {"id": 11, "title": "Backend Python Engineer", "company_name": "Example",
                 "candidate_required_location": "Germany", "url": "https://remotive.com/remote-jobs/software-dev/backend-python-11",
                 "description": "<p>Python FastAPI</p>", "job_type": "full_time", "publication_date": "2026-10-01T12:00:00"},
                {"id": 12, "title": "Backend Python Engineer", "company_name": "USA",
                 "candidate_required_location": "USA only", "url": "https://remotive.com/remote-jobs/software-dev/backend-python-12",
                 "description": "<p>Python FastAPI</p>", "job_type": "full_time"},
            ]}

    class Client:
        def get(self, url, params=None):
            assert url == "https://remotive.com/api/remote-jobs"
            return Response()

    jobs = fetch_remotive(Client())
    assert len(jobs) == 1
    assert jobs[0]["source"] == "Remotive"
    assert "remotive.com" in jobs[0]["url"]
