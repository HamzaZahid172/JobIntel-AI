from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.main import candidate_job_records, cv_tracks_for_user, resolve_job_cv
from app.models import CVProfile, CandidateDocument


def test_role_specific_cv_selected_even_if_general_cv_is_newer():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        general = CVProfile(user_id=1, filename="general.pdf",
            text="General developer Python REST", ats_score=85,
            uploaded_at=datetime(2026, 10, 14))
        qa = CVProfile(user_id=1, filename="qa.pdf",
            text="QA engineer Playwright Cypress", ats_score=90,
            uploaded_at=datetime(2026, 10, 10))
        other = CVProfile(user_id=2, filename="private.pdf", text="Private",
                          ats_score=98)
        db.add_all([general, qa, other])
        db.flush()
        db.add(CandidateDocument(
            user_id=1, kind="cv", role_family="qa", filename="qa.pdf",
            mime_type="application/pdf", storage_key="testkey", sha256="0"*64,
            size_bytes=500, cv_profile_id=qa.id, default_document=True,
        ))
        db.commit()
        job = SimpleNamespace(title="QA Automation Engineer")
        chosen, family, saved = resolve_job_cv(db, 1, job)
        assert chosen.id == qa.id
        assert family == "qa" and saved is True
        assert cv_tracks_for_user(db, 1)["qa"].id == qa.id

        explicit, family, saved = resolve_job_cv(db, 1, job, general.id)
        assert explicit.id == general.id and not saved
        private, _, _ = resolve_job_cv(db, 1, job, other.id)
        assert private is None


def test_matching_uses_per_role_cv_rather_than_latest_profile(monkeypatch):
    import app.main as main
    general = SimpleNamespace(id=1, filename="general.pdf", text="Python data")
    qa = SimpleNamespace(id=2, filename="qa.pdf", text="QA Playwright")
    job = SimpleNamespace(source="Ashby", source_id="1",
        url="https://company.example/jobs/qa", title="QA Automation Engineer",
        posted_at=datetime(2026, 10, 14))
    monkeypatch.setattr(main, "rank_cv_skills",
        lambda text, limit=10: [{"skill": "python"}])
    def report(cv, job):
        return {"job_skills":["python"], "job_role_families":[],
            "matched_skills":["python","api"], "hard_blockers":[],
            "overall_score":83, "role_score":75}
    monkeypatch.setattr(main, "match_details", report)
    matched = candidate_job_records(general, [job], cv_tracks={"qa":qa})
    assert len(matched) == 1
    assert matched[0][1]["cv_used_id"] == 2
    assert matched[0][1]["cv_used_filename"] == "qa.pdf"
