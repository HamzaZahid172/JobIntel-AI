import logging
import os
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./jobintel.sqlite3")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
logger = logging.getLogger("jobintel.database")


class Base(DeclarativeBase):
    pass


def wait_for_database(max_attempts: int = 30, delay_seconds: float = 2.0) -> None:
    """Wait for PostgreSQL/Docker DNS to become available before app startup.

    Docker Desktop can briefly report a healthy database while its embedded DNS
    is still settling. Retrying here prevents a transient name-resolution error
    from terminating the API container.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info("Database connection established.")
            return
        except OperationalError:
            if attempt == max_attempts:
                logger.exception("Database did not become available after %s attempts.", max_attempts)
                raise
            logger.warning(
                "Database unavailable (attempt %s/%s). Retrying in %.1fs...",
                attempt,
                max_attempts,
                delay_seconds,
            )
            time.sleep(delay_seconds)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
