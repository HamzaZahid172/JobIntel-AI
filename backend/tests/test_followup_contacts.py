from datetime import date, datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.followup_contacts import (
    valid_contact, known_employer_domain, event_contacts, description_contacts,
    mailbox_contacts, normalize_candidates, discover_contact, _web_contact_candidates,
    _relevant_company_mail,
)
from app.models import Application, GmailConnection, GmailEvent, LiveJob


def test_no_reply_and_unknown_contact_addresses_rejected():
    assert valid_contact("Careers Team <jobs@trusteq.de>") == "jobs@trusteq.de"
    assert valid_contact("No-Reply <no-reply@trusteq.de>") is None
    assert valid_contact("recruiter@trusteq.de, other@example.com") is None
    assert valid_contact("support@trusteq.de") is None
    assert known_employer_domain("trusteq.de", "Trusteq GmbH")


def test_saved_application_email_is_suggested_but_not_invented():
    emails = [
        SimpleNamespace(sender="Recruiting Team <talent@trusteq.de>", outcome="Applied",
                        subject="Trusteq application received"),
        SimpleNamespace(sender="noreply@trusteq.de", outcome="Applied", subject="Confirmation"),
        SimpleNamespace(sender="jobs@trusteq.de", outcome="Rejected", subject="Rejection"),
    ]
    found = event_contacts(emails, "candidate@gmail.com", "Trusteq GmbH")
    assert len(found) == 1
    assert found[0]["email"] == "talent@trusteq.de"
    assert found[0]["confidence"] == "high"


def test_job_description_requires_hiring_context():
    app = SimpleNamespace(company="Acme GmbH", role="Python Engineer", url="https://example.com/job")
    job = SimpleNamespace(company="Acme GmbH", title="Python Engineer",
                          url="https://example.com/job", source="Arbeitnow",
                          description="For applications contact careers@acme.de. IT support: help@acme.de.")
    matches = description_contacts(app, [job])
    assert [m["email"] for m in matches] == ["careers@acme.de"]
    assert matches[0]["confidence"] == "review"


def test_same_company_role_matching_is_required_for_gmail_messages(monkeypatch):
    app = Application(id=1, user_id=1, company="Trusteq GmbH", role="Backend Python Engineer",
                      status="Applied", applied_date=date(2026, 10, 1))
    other = Application(id=2, user_id=1, company="Trusteq GmbH", role="Data Engineer",
                        status="Applied", applied_date=date(2026, 10, 1))
    conn = SimpleNamespace(access_token="token", token_expires_at=datetime(2027, 1, 1),
                           google_email="candidate@gmail.com", scope="https://www.googleapis.com/auth/gmail.readonly")
    class Response:
        def __init__(self, value): self.value=value
        def raise_for_status(self): pass
        def json(self): return self.value
    def mock_get(url, headers, params, timeout):
        assert headers["Authorization"] == "Bearer token"
        if url.endswith("/messages"):
            assert params["includeSpamTrash"] is True
            return Response({"messages":[{"id":"m1"},{"id":"m2"}]})
        if url.endswith("/m1"):
            return Response({"snippet": "Thank you for applying to Trusteq",
                             "internalDate": str(1791504000000),
                             "payload":{"headers":[
                                 {"name":"Subject","value":"Trusteq Backend Python Engineer application received"},
                                 {"name":"From","value":"noreply@trusteq.de"},
                                 {"name":"Reply-To","value":"Recruitment <talent@trusteq.de>"},
                             ]}})
        return Response({"snippet": "We received your Data Engineer application at Trusteq",
                         "internalDate": str(1791504000000),
                         "payload":{"headers":[
                             {"name":"Subject","value":"Trusteq Data Engineer application received"},
                             {"name":"From","value":"hr@trusteq.de"},
                         ]}})
    monkeypatch.setattr("app.followup_contacts.httpx.get",mock_get)
    results=mailbox_contacts(None,conn,app,[app,other])
    assert [x["email"] for x in results] == ["talent@trusteq.de"]
    assert results[0]["source"]=="gmail_reply_to"


def test_no_contact_found_results_in_no_auto_recipient_and_google_research_link(monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        app=Application(user_id=7, company="Yoursquares", role="QA Automation Engineer",
                        status="Applied", applied_date=date(2026, 10, 1))
        db.add(app)
        db.commit()
        result=discover_contact(db,7,app)
        assert result["candidates"] == []
        assert result["recommended"] is None
        assert "google.com/search" in result["web_search_url"]
        assert result["public_search_enabled"] is False
    engine.dispose()


def test_optional_public_web_search_checks_company_domain_and_real_email(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY","test-key")
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"web":{"results":[
            {"url":"https://trusteq.de/careers","title":"Trusteq careers",
             "description":"For applications email recruiting@trusteq.de"},
            {"url":"https://untrusted-jobs.com/trusteq","title":"Trusteq careers",
             "description":"For applications email recruiting@trusteq.de"},
            {"url":"https://trusteq.de/marketing","title":"Trusteq news",
             "description":"contact sales@trusteq.de"},
        ]}}
    def mock_get(url,headers,params,timeout):
        assert "api.search.brave.com" in url
        assert headers["X-Subscription-Token"] == "test-key"
        return Response()
    monkeypatch.setattr("app.followup_contacts.httpx.get", mock_get)
    rows=_web_contact_candidates("Trusteq GmbH")
    assert len(rows)==1
    assert rows[0]["email"]=="recruiting@trusteq.de"
    assert rows[0]["confidence"]=="review"


def test_unique_employer_domain_email_can_match_generic_application_subject():
    app = Application(id=1, user_id=1, company="Trusteq GmbH",
                      role="Backend Python Engineer", status="Applied")
    meta = {"subject": "Update about your application",
            "from": "Recruiting Team <talent@trusteq.de>", "reply-to": ""}
    assert _relevant_company_mail(app, [app], meta, "")
    assert not _relevant_company_mail(app, [app], {"subject": "Monthly newsletter", "from": "talent@trusteq.de"}, "")
    assert not _relevant_company_mail(app, [app], {"subject": "Your application", "from": "someone@unrelated.org"}, "")


def test_generic_subject_never_selects_ambiguous_same_employer_role():
    app = Application(id=1, user_id=1, company="Trusteq GmbH",
                      role="Backend Python Engineer", status="Applied")
    other = Application(id=2, user_id=1, company="Trusteq GmbH",
                        role="Data Engineer", status="Applied")
    assert not _relevant_company_mail(app, [app, other],
        {"subject": "Your application update", "from": "talent@trusteq.de"}, "")


def test_generic_subject_from_verified_employer_finds_real_reply_to(monkeypatch):
    app = Application(id=11, user_id=1, company="Trusteq GmbH",
                      role="Backend Python Engineer", status="Applied",
                      applied_date=date(2026, 10, 1))
    conn = SimpleNamespace(access_token="token", token_expires_at=datetime(2027, 1, 1),
                           google_email="candidate@gmail.com")
    class Response:
        def __init__(self, obj): self.obj=obj
        def raise_for_status(self): pass
        def json(self): return self.obj
    def fake_get(url, headers, params, timeout):
        if url.endswith("/messages"):
            return Response({"messages":[{"id":"m1"}]})
        return Response({"snippet":"Your application has been received",
                         "internalDate":str(1791504000000),
                         "payload":{"headers":[
                             {"name":"Subject","value":"Your application update"},
                             {"name":"From","value":"Recruitment <talent@trusteq.de>"},
                             {"name":"Reply-To","value":"hiring@trusteq.de"},
                         ]}})
    monkeypatch.setattr("app.followup_contacts.httpx.get", fake_get)
    contacts=mailbox_contacts(None,conn,app,[app])
    assert contacts[0]["email"]=="hiring@trusteq.de"
    assert contacts[0]["source"]=="gmail_reply_to"
