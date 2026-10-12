"""Background Gmail polling for local JobIntel installations.

Checks connected mailboxes while the Docker backend is running (even if the
dashboard tab is closed). Gmail push notifications would require Cloud Pub/Sub;
bounded polling avoids additional paid/service configuration for local use.
"""
import logging
import os
import threading
from datetime import datetime, timedelta

from .db import SessionLocal
from .gmail_sync import sync_gmail
from .models import GmailConnection

logger = logging.getLogger("jobintel.gmail_worker")
_DEFAULT_INTERVAL = 120


def sync_due_connections(now: datetime | None = None, interval_seconds: int = _DEFAULT_INTERVAL) -> int:
    """One bounded pass; each Gmail account has its own last_synced_at."""
    now = now or datetime.utcnow()
    interval_seconds = max(60, interval_seconds)
    db = SessionLocal()
    attempted = 0
    try:
        connections = db.query(GmailConnection).all()
        for connection in connections:
            if connection.last_synced_at and now - connection.last_synced_at < timedelta(seconds=interval_seconds):
                continue
            try:
                # First connection catches prior mail; routine sync focuses on
                # recent mail and processes up to 100 message IDs (cached events
                # are skipped).
                days = 45 if connection.last_synced_at is None else 7
                sync_gmail(db, connection.user_id, days=days, max_results=100)
                attempted += 1
            except Exception:
                db.rollback()
                logger.exception("Background Gmail check failed for user %s", connection.user_id)
    finally:
        db.close()
    return attempted


def start_gmail_worker(interval_seconds: int | None = None) -> tuple[threading.Event, threading.Thread]:
    seconds = max(60, int(interval_seconds or os.getenv("GMAIL_AUTO_SYNC_INTERVAL_SECONDS", str(_DEFAULT_INTERVAL))))
    stop = threading.Event()

    def run() -> None:
        # Allow the API to finish starting before first Gmail API requests.
        if stop.wait(10):
            return
        while not stop.is_set():
            try:
                sync_due_connections(interval_seconds=seconds)
            except Exception:
                logger.exception("Unexpected Gmail poller error; retrying.")
            stop.wait(seconds)

    thread = threading.Thread(target=run, name="jobintel-gmail-sync", daemon=True)
    thread.start()
    return stop, thread
