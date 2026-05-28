"""Timezone normalisation for events.

Single chokepoint: every event flowing through the orchestrator is converted
to Asia/Kuala_Lumpur and stripped of tzinfo before filtering, dedup, and
storage. Mixed tz-aware (Luma) and naive (Eventsize, govagency) datetimes
were producing duplicate rows because their string representations differed.
"""
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

MYT = ZoneInfo("Asia/Kuala_Lumpur")


def to_myt_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert any datetime to naive Asia/Kuala_Lumpur local time.

    - Naive datetime → returned unchanged (assumed already MYT).
    - tz-aware datetime → converted to MYT, then tzinfo stripped.
    - None → None (callers handle).

    The naive-passthrough is deliberate: scrapers like govagency.py parse
    "15 May 2026" with no tz hint, and event organisers list local time.
    Treating those as MYT is the correct default for this product.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(MYT).replace(tzinfo=None)


def normalize_event_times(event: dict) -> dict:
    """Apply to_myt_naive to start_datetime and end_datetime in place."""
    if "start_datetime" in event:
        event["start_datetime"] = to_myt_naive(event["start_datetime"])
    if "end_datetime" in event:
        event["end_datetime"] = to_myt_naive(event["end_datetime"])
    return event
