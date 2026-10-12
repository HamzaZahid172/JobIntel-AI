"""Regression: OMMAX rejection is below Gmail snippet but visible in full body."""
import base64
from datetime import date, datetime
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.gmail_sync import _message_body_text, classify_message, sync_gmail, sync_application_gmail, sync_active_applications_gmail
from app.models import Application, GmailConnection, GmailEvent


SUBJECT = "Your application at OMMAX"
FULL_EMAIL = (
    "Dear Hamza Zahid,\n"
    "Thank you for your interest in joining OMMAX and for your patience while we reviewed your application.\n"
    "We truly appreciate the time and effort you put into your application.\n"
    "After careful consideration, we regret to inform you that we won’t be moving forward with your application.\n"
    "Your qualifications are beyond question, but your experience does not match the requirements.\n"
    "Best regards, OMMAX People & Culture Team"
)


def encoded(value):
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def test_full_body_identifies_ommax_rejection_beyond_preview():
    snippet = FULL_EMAIL[:130]
    assert classify_message(SUBJECT, snippet) is None  # actual old failure
    email = {"payload": {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": encoded(FULL_EMAIL)}},
            {"mimeType": "text/html", "body": {"data": encoded("<b>Ignored duplicate</b>")}},
        ],
    }}
    assert "regret to inform" in _message_body_text(email)
    assert classify_message(SUBJECT, snippet + " " + _message_body_text(email)) == "Rejected"


def test_html_only_nested_mime_rejection_is_readable():
    message = {"payload": {
        "mimeType": "multipart/mixed",
        "parts": [{"mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/html", "body": {
                "data": encoded("<html><body><p>Dear Applicant</p><p>We won’t be moving forward with your application.</p></body></html>")
            }}
        ]}],
    }}
    body = _message_body_text(message)
    assert "moving forward" in body
    assert classify_message("Your application", body) == "Rejected"


def test_sync_rejects_ommax_and_preserves_history(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        app = Application(
            user_id=4, company="Ommax", role="Intern AI & Data Engineering (m/f/d)",
            status="Applied", applied_date=date(2026, 10, 9),
        )
        db.add(app)
        db.add(GmailConnection(
            user_id=4, google_email="candidate@example.com",
            access_token="token", refresh_token="refresh",
            token_expires_at=datetime(2027, 1, 1),
        ))
        db.commit()
        class Response:
            status_code=200
            def __init__(self, payload): self.payload=payload
            def raise_for_status(self): pass
            def json(self): return self.payload

        calls=[]
        def fake_get(url, headers, params, timeout):
            calls.append(url)
            if url.endswith("/messages"):
                return Response({"messages":[{"id":"ommax-new-rejection"}]})
            assert url.endswith("/messages/ommax-new-rejection")
            assert ("format","full") in params
            return Response({
                "snippet": FULL_EMAIL[:130],
                "internalDate": str(int(datetime(2026, 10, 12, 15, 58).timestamp()*1000)),
                "payload": {
                    "mimeType": "text/plain",
                    "body": {"data": encoded(FULL_EMAIL)},
                    "headers": [
                        {"name":"Subject","value":SUBJECT},
                        {"name":"From","value":"Sophie Steib <join@ommax.com>"},
                    ]
                }
            })
        monkeypatch.setattr("app.gmail_sync.httpx.get",fake_get)
        result=sync_gmail(db,4,days=7)
        assert result["matched"]==1
        assert result["updated"]==1
        assert result["outcomes"]=={"Rejected":1}
        db.refresh(app)
        assert app.status=="Rejected"
        assert "Gmail signal: Rejected" in app.notes
        event=db.query(GmailEvent).filter_by(user_id=4).one()
        assert event.application_id==app.id
        assert event.outcome=="Rejected"
        second=sync_gmail(db,4,days=7)
        assert second["updated"]==0
        assert db.query(GmailEvent).count()==1
    engine.dispose()


def test_company_targeted_search_finds_ommax_outside_general_mailbox_limit(monkeypatch):
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        app=Application(user_id=7,company="Ommax",
            role="Intern AI & Data Engineering (m/f/d)",status="Applied",
            applied_date=date(2026,10,9))
        db.add(app)
        db.add(GmailConnection(user_id=7,google_email="candidate@example.com",
            access_token="token",refresh_token="refresh",
            token_expires_at=datetime(2027,1,1)))
        db.commit()
        class Resp:
            status_code=200
            def __init__(self,value): self.value=value
            def raise_for_status(self): pass
            def json(self): return self.value
        queries=[]
        def fake_get(url, headers, params, timeout):
            if url.endswith("/messages"):
                queries.append(params["q"])
                if '"Ommax"' in params["q"]:
                    return Resp({"messages":[{"id":"ommax-rejection"}]})
                return Resp({"messages":[{"id":"unrelated"}]})
            message_id=url.rsplit("/",1)[-1]
            if message_id=="unrelated":
                return Resp({"snippet":"Monthly newsletter",
                    "payload":{"headers":[{"name":"Subject","value":"Other newsletter"},
                                          {"name":"From","value":"info@other.example"}]}})
            return Resp({"snippet":"Thank you for your patience",
                "internalDate":str(int(datetime(2026,10,12,15,58).timestamp()*1000)),
                "payload":{"mimeType":"text/plain","body":{"data":encoded(FULL_EMAIL)},
                    "headers":[{"name":"Subject","value":SUBJECT},
                               {"name":"From","value":"Sophie Steib <join@ommax.com>"}]}})
        monkeypatch.setattr("app.gmail_sync.httpx.get",fake_get)
        result=sync_gmail(db,7,days=7,max_results=1)
        db.refresh(app)
        assert app.status=="Rejected"
        assert result["listed"]==1
        assert result["targeted_listed"]==1
        assert result["updated"]==1
        assert any('"Ommax"' in query for query in queries)
    engine.dispose()



def test_ommax_individual_sync_sets_rejected_and_reconciles_cached_event(monkeypatch):
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        app=Application(user_id=9,company="Ommax",
            role="Intern AI & Data Engineering (m/f/d)",status="Applied",
            applied_date=date(2026,10,9))
        db.add(app)
        db.add(GmailConnection(user_id=9,google_email="candidate@example.com",
            access_token="token",refresh_token="refresh",
            token_expires_at=datetime(2027,1,1)))
        db.commit()
        db.refresh(app)
        class Resp:
            status_code=200
            def __init__(self,value):self.value=value
            def raise_for_status(self):pass
            def json(self):return self.value
        queries=[]
        def fake_get(url,headers,params,timeout):
            if url.endswith("/messages"):
                queries.append(params["q"])
                assert '"Ommax"' in params["q"]
                return Resp({"messages":[{"id":"message-ommax"}]})
            assert url.endswith("/messages/message-ommax")
            return Resp({
                "snippet":"Thank you for your patience",
                "internalDate":str(int(datetime(2026,10,12,17,0).timestamp()*1000)),
                "payload":{"mimeType":"text/plain",
                    "body":{"data":encoded(FULL_EMAIL)},
                    "headers":[{"name":"Subject","value":SUBJECT},
                               {"name":"From","value":"Sophie Steib <join@ommax.com>"}]}})
        monkeypatch.setattr("app.gmail_sync.httpx.get",fake_get)
        result=sync_application_gmail(db,9,app.id)
        db.refresh(app)
        assert app.status=="Rejected"
        assert result["targeted_listed"]==1
        assert result["gmail_account"]=="candidate@example.com"
        assert result["updated"]==1
        assert len(queries)==1
        # Simulate an old status that was reset manually even though the
        # matching Gmail event was already stored.
        app.status="Applied"
        db.commit()
        replay=sync_application_gmail(db,9,app.id)
        db.refresh(app)
        assert app.status=="Rejected"
        assert replay["already_processed"]==1
        assert replay["updated"]==1
        assert db.query(GmailEvent).count()==1
    engine.dispose()


def test_page_refresh_uses_only_targeted_employer_queries(monkeypatch):
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        app=Application(user_id=44,company="Ommax",
            role="Intern AI & Data Engineering (m/f/d)",status="Applied",
            applied_date=date(2026,10,9))
        db.add(app)
        db.add(GmailConnection(user_id=44,google_email="candidate@example.com",
            access_token="token",refresh_token="refresh",
            token_expires_at=datetime(2027,1,1)))
        db.commit()
        db.refresh(app)
        queries=[]
        class Resp:
            status_code=200
            def __init__(self,value):self.value=value
            def raise_for_status(self):pass
            def json(self):return self.value
        def mock_get(url,headers,params,timeout):
            if url.endswith("/messages"):
                queries.append(params["q"])
                assert '"Ommax"' in params["q"], "Page-load refresh must not scan unrelated mail"
                return Resp({"messages":[{"id":"ommax-page-load"}]})
            assert url.endswith("/messages/ommax-page-load")
            return Resp({
                "snippet": FULL_EMAIL[:110],
                "internalDate":str(int(datetime(2026,10,12,17,0).timestamp()*1000)),
                "payload":{"mimeType":"text/plain",
                    "body":{"data":encoded(FULL_EMAIL)},
                    "headers":[{"name":"Subject","value":SUBJECT},
                               {"name":"From","value":"Sophie Steib <join@ommax.com>"}]}})
        monkeypatch.setattr("app.gmail_sync.httpx.get",mock_get)
        out=sync_active_applications_gmail(db,44)
        db.refresh(app)
        assert app.status=="Rejected"
        assert out["targeted_only"] is True
        assert out["updated"]==1
        assert out["outcomes"]["Rejected"]==1
        assert len(queries)==1
        # Already matched rejection remains idempotent on the next page refresh.
        again=sync_active_applications_gmail(db,44)
        assert again["updated"]==0
        assert db.query(GmailEvent).count()==1
    engine.dispose()
