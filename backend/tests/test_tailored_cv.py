import base64
from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.main import export_tailored_cv
from app.models import CVProfile, LiveJob
from app.schemas import TailoredCVExport
from app.tailored_cv import build_tailored_cv_text


def test_cv_highlights_are_grounded_and_original_text_is_retained():
    original = ("Sam Example\nsam@example.com\n\nPROFESSIONAL EXPERIENCE\n"
                "Built Python APIs at Example from 2020 to 2024.\n"
                "EDUCATION\nBSc Computer Science")
    draft = {"matched_skills": ["Python", "Kafka"],
             "cv_evidence": ["Built Python APIs at Example from 2020 to 2024.",
                             "Led a team of 50 people."]}
    result = build_tailored_cv_text(original, draft)
    assert "Job-related terms mentioned in CV: Python" in result
    assert "Kafka" not in result
    assert "team of 50" not in result
    assert "Built Python APIs at Example from 2020 to 2024." in result
    assert result.replace("\n\nROLE-RELEVANT HIGHLIGHTS\nJob-related terms mentioned in CV: Python\n"
                          "• Built Python APIs at Example from 2020 to 2024.\n\n", "") == original
    assert build_tailored_cv_text(original, {"matched_skills": [], "cv_evidence": []}) == original


def test_export_contains_edits_and_rejects_another_users_cv():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        job = LiveJob(source="Manual", source_id="1", title="Python Engineer",
                      company="Example GmbH", url="https://example.org/jobs/1")
        own = CVProfile(user_id=1, filename="own.pdf", text="My Python CV", ats_score=50)
        private = CVProfile(user_id=2, filename="private.pdf", text="Other person's CV", ats_score=50)
        db.add_all([job, own, private]); db.commit()
        text = "Sam Example\nPROFILE\nEdited Python developer summary."
        user = SimpleNamespace(id=1, display_name="Sam Example")
        data = export_tailored_cv(job.id, TailoredCVExport(cv_id=own.id, text=text), user, db)
        document = Document(BytesIO(base64.b64decode(data["content_base64"])))
        assert "\n".join(p.text for p in document.paragraphs) == text
        assert data["filename"].endswith("_CV.docx")
        with pytest.raises(HTTPException) as error:
            export_tailored_cv(job.id, TailoredCVExport(cv_id=private.id, text=text), user, db)
        assert error.value.status_code == 400
