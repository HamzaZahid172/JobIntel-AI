from datetime import date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.gmail_sync import classify_message, match_application, sync_gmail
from app.models import Application, GmailConnection


def test_generic_unfortunately_does_not_reject():
    assert classify_message("Office update", "Unfortunately the office is closed.") is None


def test_ambiguous_employer_email_is_not_matched():
    applications = [
        Application(id=1, user_id=1, company="Example GmbH", role="Backend Python Engineer"),
        Application(id=2, user_id=1, company="Example GmbH", role="Data Engineer"),
    ]
    assert match_application(
        applications, "An update on your application", "careers@example.com",
        "Unfortunately, we have decided not to move forward.",
    ) is None


def test_trash_search_paginates_and_updates_only_matching_application(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.utcnow()
    with Session(engine) as db:
        db.add(GmailConnection(
            user_id=1, google_email="user@example.com", access_token="token",
            refresh_token="refresh", token_expires_at=now+timedelta(hours=1),
        ))
        app = Application(
            user_id=1, company="Example GmbH", role="Backend Python Engineer",
            status="Applied", applied_date=date.today()-timedelta(days=2),
        )
        db.add(app)
        db.commit()
        db.refresh(app)
        calls = []

        class Resp:
            status_code = 200
            def __init__(self, data):
                self.data = data
            def json(self):
                return self.data
            def raise_for_status(self):
                pass

        def fake_get(url, headers, params, timeout):
            calls.append((url, params))
            if url.endswith("/messages"):
                assert params["includeSpamTrash"] is True
                assert "-in:spam" in params["q"]
                if "pageToken" in params:
                    assert params["pageToken"] == "next"
                    return Resp({"messages": [{"id": "m2"}]})
                return Resp({"messages": [{"id": "m1"}], "nextPageToken": "next"})
            if url.endswith("/messages/m1"):
                return Resp({"snippet": "No news", "payload": {"headers": [
                    {"name": "Subject", "value": "Office update"},
                    {"name": "From", "value": "info@other.test"},
                ]}})
            assert url.endswith("/messages/m2")
            return Resp({
                "snippet": "We have decided not to move forward with your application.",
                "internalDate": str(int(now.timestamp()*1000)),
                "payload": {"headers": [
                    {"name": "Subject", "value": "Example GmbH Backend Python Engineer application update"},
                    {"name": "From", "value": "jobs@example.com"},
                ]},
            })

        monkeypatch.setattr("app.gmail_sync.httpx.get", fake_get)
        result = sync_gmail(db, 1)
        db.refresh(app)
        assert result["listed"] == 2
        assert result["updated"] == 1
        assert app.status == "Rejected"
        list_calls = [call for call in calls if call[0].endswith("/messages")]
        assert len(list_calls) == 3  # two general pages plus employer-specific search
        assert sum("pageToken" in params for _, params in list_calls) == 1
        assert sum('"Example GmbH"' in params["q"] for _, params in list_calls) == 1
        # Second run must not duplicate the already saved Gmail event.
        result2 = sync_gmail(db, 1)
        assert result2["updated"] == 0
    engine.dispose()


def test_sync_all_batches_company_queries_and_updates_each_matching_application(monkeypatch):
    from app.gmail_sync import sync_active_applications_gmail
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.utcnow()
    with Session(engine) as db:
        db.add(GmailConnection(
            user_id=17, google_email="user@example.com", access_token="token",
            refresh_token="refresh", token_expires_at=now + timedelta(hours=1),
        ))
        apps = [
            Application(user_id=17, company=f"Company{i} Labs",
                        role="Backend Engineer", status="Applied",
                        applied_date=date.today()-timedelta(days=2))
            for i in range(7)
        ]
        db.add_all(apps)
        db.commit()

        class Response:
            status_code=200
            def __init__(self, value): self.value=value
            def json(self): return self.value
            def raise_for_status(self): pass

        listed_queries=[]
        def fake_get(url, headers, params, timeout):
            if url.endswith("/messages"):
                q=params["q"]
                listed_queries.append(q)
                ids=[{"id":f"reply-{i}"} for i in range(7) if f'"Company{i} Labs"' in q]
                return Response({"messages":ids})
            message_id=url.rsplit("/",1)[-1]
            i=int(message_id.split("-")[1])
            return Response({
                "snippet":"We have decided not to move forward with your application.",
                "internalDate":str(int(now.timestamp()*1000)),
                "payload":{"headers":[
                    {"name":"Subject","value":f"Company{i} Labs Backend Engineer application update"},
                    {"name":"From","value":f"jobs@company{i}.example"},
                ]},
            })

        monkeypatch.setattr("app.gmail_sync.httpx.get",fake_get)
        outcome=sync_active_applications_gmail(db,17)
        assert len(listed_queries)==2, "7 companies should need only 2 batched list calls"
        assert outcome["employers_searched"]==7
        assert outcome["employers_skipped"]==0
        assert outcome["updated"]==7
        assert all(db.get(Application,app.id).status=="Rejected" for app in apps)
    engine.dispose()
