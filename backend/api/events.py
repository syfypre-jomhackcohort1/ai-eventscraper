"""API endpoints for events."""
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from backend.database import get_db, Event
from backend.models import EventResponse, RefreshResponse, SourceStatus, CategoryInfo

logger = logging.getLogger(__name__)
router = APIRouter()

# filters.yaml is the single source of truth for topics. Loaded once at module
# import; restart the server to pick up edits.
FILTERS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "filters.yaml"

# Cheap rate limiter for /api/refresh: each scrape costs Apify credits and
# touches every external source, so we don't want anyone hammering it.
# Single-process in-memory limit; good enough for a free-tier deploy.
_LAST_REFRESH_TS = 0.0
_REFRESH_COOLDOWN_SEC = 600  # 10 minutes


def _load_categories() -> list[CategoryInfo]:
    """Load topic definitions from filters.yaml. Returns empty list on any
    failure - frontend handles empty state gracefully."""
    try:
        with open(FILTERS_PATH) as f:
            config = yaml.safe_load(f) or {}
        topics = config.get("topics", {}) or {}
        return [
            CategoryInfo(
                name=name,
                color=cfg.get("color", "#6B7280"),
                keywords=cfg.get("keywords", []),
            )
            for name, cfg in topics.items()
        ]
    except (OSError, yaml.YAMLError) as e:
        logger.error(f"Failed to load categories from {FILTERS_PATH}: {e}")
        return []


@router.get("/events", response_model=list[EventResponse])
def get_events(
    month: Optional[str] = Query(None, description="Month in YYYY-MM format"),
    category: Optional[str] = Query(None, description="Filter by category"),
    location: Optional[str] = Query(None, description="Filter by location"),
    db: Session = Depends(get_db),
):
    """Get all events with optional filters.

    Events from curated venue sources (KLCC, MITEC, WTC etc.) are always
    shown - those venues are pre-vetted, so even an "Other"-tagged event
    there is worth surfacing. Events from open platforms (Eventbrite,
    Meetup, Luma...) tagged only as "Other" are hidden because the topic
    filter is the only thing keeping noise out for those.
    """
    query = db.query(Event)

    # Hide 'Other'-only events from open platforms. Curated venue sources
    # bypass this filter - they are already trusted.
    CURATED_SOURCES = ("venues", "govagency", "insken", "kuskop", "instagram")
    query = query.filter(
        (Event.source_platform.in_(CURATED_SOURCES))
        | (
            (Event.categories != "Other")
            & (Event.categories != "")
            & (Event.categories.isnot(None))
        )
    )

    if month:
        try:
            year, mon = map(int, month.split("-"))
            start = datetime(year, mon, 1)
            if mon == 12:
                end = datetime(year + 1, 1, 1)
            else:
                end = datetime(year, mon + 1, 1)
            query = query.filter(
                and_(Event.start_datetime >= start, Event.start_datetime < end)
            )
        except ValueError:
            pass

    if category:
        query = query.filter(Event.categories.contains(category))

    if location:
        query = query.filter(Event.location.ilike(f"%{location}%"))

    events = query.order_by(Event.start_datetime).all()
    return events


@router.get("/events/{event_id}", response_model=EventResponse)
def get_event(event_id: str, db: Session = Depends(get_db)):
    """Get single event by ID."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("/refresh", response_model=RefreshResponse)
def refresh_events():
    """Trigger manual re-scrape of all sources.

    Rate-limited to once every 10 minutes per process. Each scrape costs
    Apify credits and hits every external source - we don't want this
    endpoint to be a free DoS amplifier once the app is public.
    """
    import threading
    from backend.orchestrator import run_scrape

    global _LAST_REFRESH_TS
    now = time.time()
    if now - _LAST_REFRESH_TS < _REFRESH_COOLDOWN_SEC:
        wait_sec = int(_REFRESH_COOLDOWN_SEC - (now - _LAST_REFRESH_TS))
        raise HTTPException(
            status_code=429,
            detail=f"Refresh recently triggered. Please wait {wait_sec}s.",
        )
    _LAST_REFRESH_TS = now

    def _run():
        run_scrape()

    threading.Thread(target=_run, daemon=True).start()
    return RefreshResponse(
        status="success",
        message="Refresh initiated — scraping in background",
        events_scraped=0,
    )


@router.get("/sources", response_model=list[SourceStatus])
def get_sources(db: Session = Depends(get_db)):
    """List active sources with current event counts.

    The set is read from the DB so it reflects what's actually running,
    not a hardcoded list that drifts from reality.
    """
    rows = (
        db.query(Event.source_platform, func.count(Event.id))
        .group_by(Event.source_platform)
        .all()
    )
    return [
        SourceStatus(name=src, platform=src, event_count=count, enabled=True)
        for src, count in rows
        if src
    ]


@router.get("/categories", response_model=list[CategoryInfo])
def get_categories():
    """Get available filter categories with colors.

    Reads from config/filters.yaml so YAML is the single source of truth.
    """
    return _load_categories()