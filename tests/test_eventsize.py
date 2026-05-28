"""Eventsize scraper regression tests for the card-parsing approach.

Locks in:
- Card date format '28 May, 2:00 PM' parses to a naive datetime
- Year inference rolls forward when the parsed month is well in the past
- Slug normalisation strips '/p/N/' and trailing slashes
- Garbage strings return None
"""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from backend.scrapers.eventsize import EventsizeScraper


parse = EventsizeScraper._parse_card_date


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def test_card_date_morning_in_future():
    """'28 December, 9:00 AM' on May 27 of same year stays in current year."""
    fake_now = datetime(2026, 5, 27, 12, 0)
    with patch("backend.scrapers.eventsize.datetime") as dt:
        dt.now.return_value = fake_now
        dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = parse("28 December, 9:00 AM")
    assert result == datetime(2026, 12, 28, 9, 0)


def test_card_date_afternoon_pm():
    fake_now = datetime(2026, 5, 27, 12, 0)
    with patch("backend.scrapers.eventsize.datetime") as dt:
        dt.now.return_value = fake_now
        dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = parse("11 June, 2:15 PM")
    assert result == datetime(2026, 6, 11, 14, 15)


def test_card_date_noon_handled():
    fake_now = datetime(2026, 5, 27, 12, 0)
    with patch("backend.scrapers.eventsize.datetime") as dt:
        dt.now.return_value = fake_now
        dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = parse("15 July, 12:00 PM")
    assert result.hour == 12


def test_card_date_midnight_handled():
    fake_now = datetime(2026, 5, 27, 12, 0)
    with patch("backend.scrapers.eventsize.datetime") as dt:
        dt.now.return_value = fake_now
        dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = parse("15 July, 12:00 AM")
    assert result.hour == 0


def test_card_date_no_minute():
    """Some cards drop the minutes: '20 July, 9 AM'."""
    fake_now = datetime(2026, 5, 27, 12, 0)
    with patch("backend.scrapers.eventsize.datetime") as dt:
        dt.now.return_value = fake_now
        dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        result = parse("20 July, 9 AM")
    assert result == datetime(2026, 7, 20, 9, 0)


def test_card_date_rolls_to_next_year_when_far_in_past():
    """A month that's already 30+ days behind today rolls forward."""
    fake_now = datetime(2026, 5, 27, 12, 0)
    with patch("backend.scrapers.eventsize.datetime") as dt:
        dt.now.return_value = fake_now
        dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        # January is well in the past in late May
        result = parse("15 January, 9:00 AM")
    assert result == datetime(2027, 1, 15, 9, 0)


def test_card_date_does_not_roll_for_recent_past():
    """A date that's only a few days in the past stays this year - the user
    might still be looking at last week's calendar view."""
    fake_now = datetime(2026, 5, 27, 12, 0)
    with patch("backend.scrapers.eventsize.datetime") as dt:
        dt.now.return_value = fake_now
        dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        # May 1 is 26 days in the past, under the 30-day threshold
        result = parse("1 May, 9:00 AM")
    assert result.year == 2026


def test_card_date_garbage_returns_none():
    assert parse("") is None
    assert parse("not a date") is None
    assert parse("FEATURED") is None
    assert parse("WORQ Subang") is None
    # Wrong month name
    assert parse("28 Smarch, 2:00 PM") is None


# ---------------------------------------------------------------------------
# Slug normalisation
# ---------------------------------------------------------------------------

def test_slug_strips_pagination_suffix():
    norm = EventsizeScraper._normalise_slug
    assert norm("event/scaling-in-a-changing-world-workshop-2/p/1/") == "scaling-in-a-changing-world-workshop-2"


def test_slug_keeps_id_prefix():
    norm = EventsizeScraper._normalise_slug
    assert norm("event/1779455172516-e3-institute-open-day-2026") == "1779455172516-e3-institute-open-day-2026"


def test_slug_rejects_extra_path_segments():
    """A href with extra path segments (not /p/N/) is suspect; reject."""
    norm = EventsizeScraper._normalise_slug
    assert norm("event/something/extra/path") == ""


def test_slug_strips_trailing_slash():
    norm = EventsizeScraper._normalise_slug
    assert norm("event/python-bootcamp-june2026/") == "python-bootcamp-june2026"
