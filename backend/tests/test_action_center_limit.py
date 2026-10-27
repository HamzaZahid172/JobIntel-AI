from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.db import Base, get_db
from app.main import app
from app.models import CVProfile, LiveJob
import app.main as main


def test_action_center_limit_preserves_total_counts_and_bounds(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(CVProfile(user_id=1, filename="cv.pdf", text="Python software engineer", ats_score=80))
        for index in range(20):
            db.add(LiveJob(source="Manual", source_id=str(index), title=f"Python Engineer {index}",
                           company="Example", location="Germany", url=f"https://example.org/jobs/{index}"))
        db.commit()
        report = {"overall_score": 80, "role_score": 80, "matched_skills": ["python"],
                  "missing_skills": [], "job_role_families": [], "hard_blockers": []}
        monkeypatch.setattr(main, "cv_tracks_for_user", lambda db, user_id: {})
        monkeypatch.setattr(main, "match_details", lambda cv, job: dict(report))
        monkeypatch.setattr(main, "opportunity_assessment", lambda job, details: {
            "score": 80, "decision": "Review", "track": "Full-time / Other"})
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, display_name="Sam")
        app.dependency_overrides[get_db] = lambda: db
        try:
            client = TestClient(app)
            default = client.get("/api/action-center").json()
            expanded = client.get("/api/action-center?limit=100").json()
            assert len(default["opportunities"]) == 12
            assert len(expanded["opportunities"]) == 20
            assert default["review"] == expanded["review"] == 20
            assert client.get("/api/action-center?limit=101").status_code == 422
            assert client.get("/api/action-center?limit=0").status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_db, None)
