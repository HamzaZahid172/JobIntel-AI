from datetime import date, datetime
from sqlalchemy import String, Integer, Date, DateTime, Text, Float
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(160))
    location: Mapped[str] = mapped_column(String(160), default="Germany")
    work_mode: Mapped[str] = mapped_column(String(40), default="Hybrid")
    url: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[str] = mapped_column(Text, default="")
    match_score: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Application(Base):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(160), default="Germany")
    url: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(40), default="Applied")
    cv_version: Mapped[str] = mapped_column(String(100), default="Data Engineer CV v3")
    match_score: Mapped[float] = mapped_column(Float, default=0)
    applied_date: Mapped[date] = mapped_column(Date, default=date.today)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
