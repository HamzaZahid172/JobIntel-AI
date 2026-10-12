import hashlib
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.document_vault import store_document, read_document, choose_document, public_document
from app.models import CandidateDocument


def test_encrypted_document_saved_once_and_can_be_reused(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBINTEL_DOCUMENT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBINTEL_DOCUMENT_KEY", raising=False)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    raw = b"%PDF-1.4\nTest CV original bytes"
    with Session(engine) as db:
        first = store_document(db, 1, "candidate.pdf", raw, "cv", "data", cv_profile_id=7)
        again = store_document(db, 1, "candidate.pdf", raw, "cv", "data", cv_profile_id=7)
        assert first.id == again.id
        assert public_document(first)["cv_profile_id"] == 7
        assert read_document(first) == raw
        assert raw not in (tmp_path / first.storage_key).read_bytes()
        assert (tmp_path / ".vault-key").exists()
        assert choose_document(db, 1, "cv", "data").id == first.id
        assert choose_document(db, 2, "cv", "data") is None
        assert db.query(CandidateDocument).count() == 1
    engine.dispose()


def test_vault_defaults_are_per_kind_and_family(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBINTEL_DOCUMENT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBINTEL_DOCUMENT_KEY", raising=False)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        cv1 = store_document(db, 1, "a.pdf", b"%PDF-alpha", "cv", "qa")
        cv2 = store_document(db, 1, "b.pdf", b"%PDF-beta", "cv", "qa")
        exp = store_document(db, 1, "experience.pdf", b"%PDF-letter", "experience")
        db.refresh(cv1)
        assert not cv1.default_document
        assert cv2.default_document
        assert choose_document(db, 1, "cv", "qa").id == cv2.id
        assert choose_document(db, 1, "experience", "backend").id == exp.id
        assert choose_document(db, 1, "cv", "backend") is None
    engine.dispose()


def test_vault_rejects_invalid_content_and_detects_tampering(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBINTEL_DOCUMENT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBINTEL_DOCUMENT_KEY", raising=False)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        with pytest.raises(HTTPException):
            store_document(db, 1, "../fake.pdf", b"not a PDF", "cv")
        row = store_document(db, 1, "cv.pdf", b"%PDF-good", "cv")
        (tmp_path / row.storage_key).write_bytes(b"corrupted")
        with pytest.raises(HTTPException) as err:
            read_document(row)
        assert err.value.status_code == 503
    engine.dispose()


def test_unsupported_kind_or_role_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBINTEL_DOCUMENT_DIR", str(tmp_path))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        with pytest.raises(HTTPException):
            store_document(db, 1, "cv.pdf", b"%PDF-data", "cv", "other")
        with pytest.raises(HTTPException):
            store_document(db, 1, "cv.pdf", b"%PDF-data", "unknown", "general")
    engine.dispose()
