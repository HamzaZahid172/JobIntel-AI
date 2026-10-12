"""Local encrypted per-user document vault; key and ciphertext survive Docker restarts.

Do NOT put the key in Git or re-create it on restart. The persistent vault
volume must be backed up together with the PostgreSQL volume.
"""
import hashlib
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import CandidateDocument

KINDS = {"cv", "experience", "cover"}
ROLES = {"general", "qa", "data", "backend"}
MIME = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword", ".txt": "text/plain"}
MAX_FILE_BYTES = 8 * 1024 * 1024


def vault_dir() -> Path:
    path = Path(os.getenv("JOBINTEL_DOCUMENT_DIR", "/data/documents"))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _cipher() -> Fernet:
    override = os.getenv("JOBINTEL_DOCUMENT_KEY")
    if override:
        return Fernet(override.encode("ascii"))
    root = vault_dir()
    key_file = root / ".vault-key"
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "wb") as handle:
            handle.write(Fernet.generate_key())
    return Fernet(key_file.read_bytes())


def _safe_name(filename: str) -> str:
    cleaned = re.sub(r"[^\w. ()-]", "_", Path(filename or "attachment.pdf").name)[:150]
    return cleaned or "attachment.pdf"


def _validate(filename: str, raw: bytes) -> tuple[str, str]:
    filename = _safe_name(filename)
    extension = Path(filename).suffix.lower()
    if extension not in MIME or not raw or len(raw) > MAX_FILE_BYTES:
        raise HTTPException(400, "Upload a PDF, DOC, DOCX or TXT file up to 8 MB.")
    if extension == ".pdf" and not raw.startswith(b"%PDF"):
        raise HTTPException(400, "Invalid PDF file content.")
    if extension == ".docx" and not raw.startswith(b"PK"):
        raise HTTPException(400, "Invalid DOCX file content.")
    return filename, MIME[extension]


def store_document(db: Session, user_id: int, filename: str, raw: bytes,
                   kind: str = "cv", role_family: str = "general",
                   make_default: bool = True) -> CandidateDocument:
    if kind not in KINDS or role_family not in ROLES:
        raise HTTPException(400, "Unsupported document kind or CV role family.")
    filename, mime = _validate(filename, raw)
    sha = hashlib.sha256(raw).hexdigest()
    found = db.query(CandidateDocument).filter(
        CandidateDocument.user_id == user_id, CandidateDocument.sha256 == sha,
        CandidateDocument.kind == kind, CandidateDocument.role_family == role_family
    ).first()
    if found:
        if make_default:
            for other in db.query(CandidateDocument).filter(
                    CandidateDocument.user_id == user_id, CandidateDocument.kind == kind,
                    CandidateDocument.role_family == role_family):
                other.default_document = other.id == found.id
            db.commit()
        return found
    token = secrets.token_hex(24)
    destination = vault_dir() / token
    payload = _cipher().encrypt(raw)
    with destination.open("xb") as file:
        os.chmod(destination, 0o600)
        file.write(payload)
    if make_default:
        db.query(CandidateDocument).filter(
            CandidateDocument.user_id == user_id, CandidateDocument.kind == kind,
            CandidateDocument.role_family == role_family,
        ).update({"default_document": False})
    row = CandidateDocument(
        user_id=user_id, kind=kind, role_family=role_family, filename=filename,
        mime_type=mime, storage_key=token, sha256=sha,
        size_bytes=len(raw), default_document=make_default)
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise
    return row


def read_document(row: CandidateDocument) -> bytes:
    path = vault_dir() / row.storage_key
    try:
        raw = _cipher().decrypt(path.read_bytes())
    except (InvalidToken, FileNotFoundError) as exc:
        raise HTTPException(503, "Saved file cannot be decrypted. Restore the original vault key and backup.") from exc
    if hashlib.sha256(raw).hexdigest() != row.sha256:
        raise HTTPException(503, "Saved file checksum does not match.")
    return raw


def public_document(row: CandidateDocument) -> dict:
    return {
        "id": row.id, "kind": row.kind, "role_family": row.role_family,
        "filename": row.filename, "mime_type": row.mime_type,
        "size_bytes": row.size_bytes, "default_document": row.default_document,
        "created_at": row.created_at.isoformat(),
    }


def choose_document(db: Session, user_id: int, kind: str,
                    role_family: str = "general") -> CandidateDocument | None:
    documents = db.query(CandidateDocument).filter(
        CandidateDocument.user_id == user_id, CandidateDocument.kind == kind
    ).order_by(CandidateDocument.default_document.desc(),
               CandidateDocument.created_at.desc()).all()
    # Never swap job-specific documents for an unrelated role silently.
    return next((d for d in documents if d.role_family == role_family), None) or next(
        (d for d in documents if d.role_family == "general"), None
    )
