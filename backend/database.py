"""SQLAlchemy database setup and models."""
import hashlib
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Text
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Event(Base):
    __tablename__ = "events"

    id = Column(String(64), primary_key=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    start_datetime = Column(DateTime, nullable=False)
    end_datetime = Column(DateTime)
    location = Column(String(500))
    is_virtual = Column(Boolean, default=False)
    organiser = Column(String(300))
    source_platform = Column(String(50), nullable=False)
    source_url = Column(String(1000))
    categories = Column(String(200))
    image_url = Column(String(1000))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def generate_id(title: str, date: datetime, source: str = "") -> str:
        """SHA256 of normalised title + date (no time, no source).

        Source is intentionally excluded so the same event from two
        platforms (e.g. Luma + Facebook Events) collides at the DB layer.
        Time is excluded so a 7pm → 7:30pm reschedule does not create a
        duplicate. The `source` arg is kept for backward-compat callers
        but ignored.
        """
        import re
        norm_title = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", title.lower())).strip()
        date_only = date.date() if hasattr(date, "date") else date
        raw = f"{norm_title}|{date_only.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:64]


engine = create_engine("sqlite:///./kv_events.db", echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()