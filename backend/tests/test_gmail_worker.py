from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.gmail_worker import sync_due_connections
from app.models import GmailConnection


def test_background_sync_only_checks_connections_when_due(monkeypatch):
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now=datetime(2026,10,12,16,0)
    with Session(engine) as db:
        db.add(GmailConnection(
            user_id=1, google_email="new@example.com", access_token="t1",
            last_synced_at=None,
        ))
        db.add(GmailConnection(
            user_id=2, google_email="recent@example.com", access_token="t2",
            last_synced_at=now-timedelta(seconds=30),
        ))
        db.add(GmailConnection(
            user_id=3, google_email="old@example.com", access_token="t3",
            last_synced_at=now-timedelta(minutes=20),
        ))
        db.commit()

    calls=[]
    def fake_sync(db,user_id):
        calls.append(user_id)
        connection=db.query(GmailConnection).filter_by(user_id=user_id).one()
        connection.last_synced_at=now
        db.commit()
    monkeypatch.setattr("app.gmail_worker.SessionLocal",lambda:Session(engine))
    monkeypatch.setattr("app.gmail_worker.sync_active_applications_gmail",fake_sync)
    assert sync_due_connections(now,interval_seconds=120)==2
    assert calls==[1,3]
    assert sync_due_connections(now,interval_seconds=120)==0
    engine.dispose()


def test_background_failure_does_not_block_other_users(monkeypatch):
    engine=create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(GmailConnection(user_id=1, google_email="broken@example.com",access_token="a"))
        db.add(GmailConnection(user_id=2, google_email="working@example.com",access_token="b"))
        db.commit()
    calls=[]
    def fake_sync(db,user_id):
        calls.append(user_id)
        if user_id==1: raise RuntimeError("Google API unavailable")
        db.query(GmailConnection).filter_by(user_id=user_id).one().last_synced_at=datetime.utcnow()
        db.commit()
    monkeypatch.setattr("app.gmail_worker.SessionLocal",lambda:Session(engine))
    monkeypatch.setattr("app.gmail_worker.sync_active_applications_gmail",fake_sync)
    assert sync_due_connections(interval_seconds=120)==1
    assert calls==[1,2]
    engine.dispose()
