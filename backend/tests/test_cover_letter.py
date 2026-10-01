from types import SimpleNamespace

from app.cover_letter import build_cover_letter_docx, safe_filename


def test_safe_filename():
    assert safe_filename("Hamza / Backend Engineer: Cover Letter") == "Hamza_Backend_Engineer_Cover_Letter"


def test_cover_letter_docx_bytes():
    user = SimpleNamespace(display_name="Test User", email="test@example.com")
    job = SimpleNamespace(title="Backend Engineer", company="Example GmbH")
    content = build_cover_letter_docx(
        "Dear Hiring Team,\n\nI am applying for the Backend Engineer role.\n\nKind regards,\nTest User",
        user,
        job,
    )
    assert content[:2] == b"PK"
    assert len(content) > 1000
