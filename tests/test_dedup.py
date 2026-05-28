"""Regression tests for the timezone + dedup fix.

The bug we're locking down: Solana Network State (Spring 2026) appeared
on May 25 AND May 26 on Aiman's calendar because Luma returned a
tz-aware UTC datetime (2026-05-25T16:30:00+00:00 == 2026-05-26 00:30 MYT)
while another scraper returned a naive datetime treated as MYT.

Different string forms of "the same moment" survived dedup, then produced
different SHA hashes in Event.generate_id, yielding two DB rows.
"""
from datetime import datetime, timezone

import pytest

from backend.database import Event
from backend.filters import FilterEngine
from backend.timezone import normalize_event_times, to_myt_naive


# ---------------------------------------------------------------------------
# to_myt_naive
# ---------------------------------------------------------------------------

def test_utc_aware_converts_to_myt_naive():
    """A UTC-aware datetime becomes naive MYT (UTC+8)."""
    utc = datetime(2026, 5, 25, 16, 30, tzinfo=timezone.utc)
    result = to_myt_naive(utc)
    assert result.tzinfo is None
    assert result == datetime(2026, 5, 26, 0, 30)


def test_naive_passthrough():
    """Naive datetimes are assumed to already be MYT and pass through."""
    naive = datetime(2026, 5, 26, 0, 30)
    assert to_myt_naive(naive) == naive
    assert to_myt_naive(naive).tzinfo is None


def test_none_passthrough():
    assert to_myt_naive(None) is None


def test_normalize_event_times_handles_both_fields():
    event = {
        "title": "Test",
        "start_datetime": datetime(2026, 5, 25, 16, 30, tzinfo=timezone.utc),
        "end_datetime": datetime(2026, 5, 25, 18, 30, tzinfo=timezone.utc),
    }
    normalize_event_times(event)
    assert event["start_datetime"] == datetime(2026, 5, 26, 0, 30)
    assert event["end_datetime"] == datetime(2026, 5, 26, 2, 30)
    assert event["start_datetime"].tzinfo is None


# ---------------------------------------------------------------------------
# Solana regression: the actual production bug
# ---------------------------------------------------------------------------

def _solana_from_luma() -> dict:
    """Luma representation: tz-aware UTC, evening of the 25th UTC."""
    return {
        "title": "Solana Network State [Spring 2026] Demo Day presented by AppWorks and Jelawang Capital",
        "start_datetime": datetime(2026, 5, 25, 16, 30, tzinfo=timezone.utc),
        "source_platform": "luma",
        "categories": ["Blockchain"],
        "location": "Kuala Lumpur",
    }


def _solana_from_eventsize() -> dict:
    """Eventsize representation: naive datetime, organiser-local MYT clock."""
    return {
        "title": "Solana Network State [Spring 2026] Demo Day presented by AppWorks and Jelawang Capital",
        "start_datetime": datetime(2026, 5, 26, 0, 30),
        "source_platform": "eventsize",
        "categories": ["Blockchain"],
        "location": "Kuala Lumpur",
    }


def test_solana_event_dedups_after_tz_normalisation():
    """Two scrapers find the same event, different tz reps. After normalize +
    dedup, exactly one event survives, on May 26 MYT."""
    luma = _solana_from_luma()
    eventsize = _solana_from_eventsize()

    # Step 1: normalise (what orchestrator does immediately after scrape)
    events = [normalize_event_times(luma), normalize_event_times(eventsize)]

    # Both should now sit on 2026-05-26 MYT
    assert events[0]["start_datetime"].date() == events[1]["start_datetime"].date()
    assert events[0]["start_datetime"] == datetime(2026, 5, 26, 0, 30)

    # Step 2: dedup
    unique = FilterEngine().deduplicate(events)
    assert len(unique) == 1
    assert unique[0]["start_datetime"].date() == datetime(2026, 5, 26).date()


def test_solana_event_generates_same_db_id_from_both_scrapers():
    """Same event, same date, two scrapers - must hash to the same DB id."""
    luma = normalize_event_times(_solana_from_luma())
    eventsize = normalize_event_times(_solana_from_eventsize())

    luma_id = Event.generate_id(luma["title"], luma["start_datetime"])
    eventsize_id = Event.generate_id(eventsize["title"], eventsize["start_datetime"])

    assert luma_id == eventsize_id


# ---------------------------------------------------------------------------
# Other dedup behaviours we promised in DESIGN.md
# ---------------------------------------------------------------------------

def test_dedup_ignores_time_within_same_day():
    """Organiser pushes start from 19:00 to 19:30 - still one event."""
    e1 = {"title": "AI Hackathon", "start_datetime": datetime(2026, 6, 1, 19, 0)}
    e2 = {"title": "AI Hackathon", "start_datetime": datetime(2026, 6, 1, 19, 30)}
    unique = FilterEngine().deduplicate([e1, e2])
    assert len(unique) == 1


def test_dedup_keeps_different_days():
    """Same title, different dates - both kept (recurring event)."""
    e1 = {"title": "Meetup KL", "start_datetime": datetime(2026, 6, 1, 19, 0)}
    e2 = {"title": "Meetup KL", "start_datetime": datetime(2026, 6, 8, 19, 0)}
    unique = FilterEngine().deduplicate([e1, e2])
    assert len(unique) == 2


def test_dedup_normalises_punctuation_and_case():
    """'AI Summit, KL!' and 'ai summit kl' are the same event."""
    e1 = {"title": "AI Summit, KL!", "start_datetime": datetime(2026, 6, 1, 19, 0)}
    e2 = {"title": "ai summit kl", "start_datetime": datetime(2026, 6, 1, 19, 0)}
    unique = FilterEngine().deduplicate([e1, e2])
    assert len(unique) == 1


def test_dedup_does_NOT_strip_year_suffix():
    """'Conference 2026' and 'Conference 2027' must NOT merge - different events."""
    e1 = {"title": "Conference 2026", "start_datetime": datetime(2026, 6, 1)}
    e2 = {"title": "Conference 2027", "start_datetime": datetime(2026, 6, 1)}
    unique = FilterEngine().deduplicate([e1, e2])
    assert len(unique) == 2


def test_dedup_skips_events_without_dates():
    """An event with no start_datetime is dropped (cannot dedup safely)."""
    e1 = {"title": "No date here", "start_datetime": None}
    e2 = {"title": "Has a date", "start_datetime": datetime(2026, 6, 1)}
    unique = FilterEngine().deduplicate([e1, e2])
    assert len(unique) == 1
    assert unique[0]["title"] == "Has a date"


def test_generate_id_ignores_source_argument():
    """Event.generate_id keeps `source` arg for back-compat but must ignore it."""
    dt = datetime(2026, 5, 26, 0, 30)
    id_no_source = Event.generate_id("Event Title", dt)
    id_with_source_a = Event.generate_id("Event Title", dt, "luma")
    id_with_source_b = Event.generate_id("Event Title", dt, "facebook")
    assert id_no_source == id_with_source_a == id_with_source_b
