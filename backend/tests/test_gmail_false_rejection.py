"""False-rejection safeguards: Workwise application confirmation != rejection."""
import base64
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.gmail_sync import (
    classify_message, rejection_evidence, sync_active_applications_gmail,
)
from app.models import Application, GmailConnection, GmailEvent


WORKWISE_CONFIRMATION = (
    "Dear Applicant, Thanks for applying for the QA Engineer role with us at Workwise. "
    "Your application has been successfully submitted. "
    "If your application seems like a good fit for the position, we will contact you soon. "
    "Due to the high volume of applications, we'll appreciate your patience as we carefully "
    "consider your qualifications. We aim to respond to all applicants, so please stay tuned "
    "for further updates. Please note: Do not reply to this email."
)
OMMAX_REJECTION = (
    "Dear applicant, Thank you for your interest in OMMAX. "
    "After careful consideration, we regret to inform you that we won’t be moving forward "
    "with your application. Your skills and previous experience do not match our requirements."
)


def encode(content: str) -> str:
    return base64.urlsafe_b64encode(content.encode()).decode().rstrip("=")


def test_workwise_confirmation_and_hiring_policy_are_not_rejection():
    assert classify_message("Thank you for applying to Workwise", WORKWISE_CONFIRMATION) == "Applied"
    assert rejection_evidence("Thank you for applying to Workwise", WORKWISE_CONFIRMATION) is None
    assert classify_message("Update on your application | Workwise",
        "Other candidates may be considered. Unfortunately, if your application "
        "is not selected, we will notify you.") is None
    assert classify_message("Workwise update", "Leider nicht alle Bewerbungen können "
        "direkt berücksichtigt werden.") is None
    assert classify_message("Workwise update", "If we will not be moving forward "
        "with your application, we will let you know.") is None


def test_genuine_explicit_rejection_is_still_detected():
    assert classify_message("Your application at OMMAX", OMMAX_REJECTION) == "Rejected"
    assert rejection_evidence("Your application at OMMAX", OMMAX_REJECTION)
    assert classify_message("Application update", "We have decided not to move forward "
        "with your application.") == "Rejected"
    assert classify_message("Absage Ihrer Bewerbung", "Vielen Dank für Ihr Interesse.") == "Rejected"


def test_legacy_false_rejection_is_rechecked_and_restored(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        now = datetime.utcnow()
        app = Application(
            user_id=47, company="Workwise", role="QA Engineer", status="Rejected",
            applied_date=date.today() - timedelta(days=10),
            notes="Interview preparation\nGmail signal: Rejected — Update on your application | Workwise"
        )
        db.add(app)
        db.add(GmailConnection(
            user_id=47, google_email="applicant@example.com", access_token="token",
            refresh_token="refresh", token_expires_at=now+timedelta(days=1)
        ))
        db.commit()
        db.refresh(app)
        db.add(GmailEvent(
            user_id=47, application_id=app.id,
            gmail_message_id="wrong-workwise-signal",
            outcome="Rejected", subject="Update on your application | Workwise",
            sender="no-reply@eu.greenhouse-mail.io",
            snippet=WORKWISE_CONFIRMATION[:100],
            received_at=now-timedelta(days=5),
        ))
        db.commit()

        class Response:
            status_code = 200
            def __init__(self, data): self.data=data
            def json(self): return self.data
            def raise_for_status(self): pass

        calls=[]
        def get(url, headers, params, timeout):
            calls.append(url)
            if url.endswith("/messages"):
                return Response({"messages":[]})
            assert url.endswith("/messages/wrong-workwise-signal")
            return Response({"snippet":WORKWISE_CONFIRMATION[:120],
                "payload":{"mimeType":"text/plain",
                    "body":{"data":encode(WORKWISE_CONFIRMATION)},
                    "headers":[
                        {"name":"Subject","value":"Update on your application | Workwise"},
                        {"name":"From","value":"no-reply@eu.greenhouse-mail.io"},
                    ]}})
        monkeypatch.setattr("app.gmail_sync.httpx.get", get)
        result=sync_active_applications_gmail(db,47)
        db.refresh(app)
        assert result["corrected_false_rejections"]==1
        assert result["updated"]==1
        assert app.status=="Applied"
        assert app.notes=="Interview preparation"
        event=db.query(GmailEvent).filter_by(user_id=47).one()
        assert event.outcome=="Applied"
        assert event.subject=="Update on your application | Workwise"
        assert "wrong-workwise-signal" in " ".join(calls)

        again=sync_active_applications_gmail(db,47)
        assert again["corrected_false_rejections"]==0
        assert app.status=="Applied"
        assert db.query(GmailEvent).count()==1
    engine.dispose()


def test_genuine_rejection_not_rolled_back_when_another_signal_is_false(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        now = datetime.utcnow()
        app=Application(user_id=88,company="Workwise",role="QA Engineer",
            status="Rejected",applied_date=date.today()-timedelta(days=10))
        db.add(app)
        db.add(GmailConnection(user_id=88,google_email="applicant@example.com",
            access_token="token",token_expires_at=now+timedelta(days=1)))
        db.commit()
        db.refresh(app)
        for message_id in ("false", "real"):
            db.add(GmailEvent(
                user_id=88,application_id=app.id,gmail_message_id=message_id,
                outcome="Rejected",subject="Workwise application update",
                sender="jobs@workwise.com",snippet="",
                received_at=now-timedelta(days=2)
            ))
        db.commit()
        class Response:
            status_code=200
            def __init__(self,body):self.body=body
            def raise_for_status(self):pass
            def json(self):
                return {"snippet":self.body[:100],"payload":{
                    "mimeType":"text/plain","body":{"data":encode(self.body)},
                    "headers":[
                        {"name":"Subject","value":"Workwise application update"},
                        {"name":"From","value":"jobs@workwise.com"},
                    ]
                }}
        class Listing:
            status_code=200
            def raise_for_status(self):pass
            def json(self):return {"messages":[]}
        def get(url,headers,params,timeout):
            if url.endswith("/messages"):return Listing()
            if url.endswith("/false"):return Response(WORKWISE_CONFIRMATION)
            if url.endswith("/real"):
                return Response("We have decided not to move forward with your QA Engineer "
                                "application at Workwise.")
            assert False, url
        monkeypatch.setattr("app.gmail_sync.httpx.get",get)
        result=sync_active_applications_gmail(db,88)
        db.refresh(app)
        assert result["corrected_false_rejections"]==1
        assert app.status=="Rejected"
        events=db.query(GmailEvent).filter_by(user_id=88).all()
        assert sorted([e.outcome for e in events])==["Applied","Rejected"]
    engine.dispose()
