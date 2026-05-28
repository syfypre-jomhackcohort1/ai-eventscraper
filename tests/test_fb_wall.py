"""Regression tests for FacebookWallScraper post parsing.

The Playwright rendering itself is integration-tested by running live;
these tests lock in the pure-function pieces: date extraction, post-body
extraction, event-keyword detection.
"""
from datetime import datetime

import pytest

from backend.scrapers.fb_wall import (
    FacebookWallScraper,
    EVENT_KEYWORDS,
)


extract_date = FacebookWallScraper._extract_date
extract_body = FacebookWallScraper._extract_post_body


# ---------------------------------------------------------------------------
# Date extraction
# ---------------------------------------------------------------------------

def test_dd_month_yyyy_english():
    assert extract_date("Join us 18 June 2026 at WORQ KL") == datetime(2026, 6, 18)


def test_dd_month_yyyy_short_form():
    assert extract_date("Workshop on 5 Jul 2026") == datetime(2026, 7, 5)


def test_dd_month_yyyy_malay():
    """'25 Mei 2026' should parse - many KL agencies post in Malay."""
    assert extract_date("Pelancaran pada 25 Mei 2026") == datetime(2026, 5, 25)


def test_month_dd_yyyy_english():
    assert extract_date("Conference June 18, 2026") == datetime(2026, 6, 18)


def test_dd_slash_mm_yyyy():
    assert extract_date("Save the date: 18/06/2026") == datetime(2026, 6, 18)


def test_no_year_returns_none():
    """'Throughout June and July' has no year, must not be mis-parsed."""
    assert extract_date("Throughout June and July, INSKEN programmes are open") is None


def test_no_date_returns_none():
    assert extract_date("Selamat Hari Raya from INSKEN team") is None


def test_invalid_date_returns_none():
    """31 February doesn't exist - parser should return None."""
    assert extract_date("Event on 31 February 2026") is None


# ---------------------------------------------------------------------------
# Post body extraction (FB renders posts with prelude + reactions noise)
# ---------------------------------------------------------------------------

def test_strips_prelude_and_reactions():
    raw = (
        "Institut Keusahawanan Negara | \xa0 | 12h | \xa0 |  ·  | "
        "Workshop AI for Founders 18 June 2026 at WORQ KL Sentral. "
        "Daftar sekarang… See more | All reactions: | 25 | 1 | 2 | Like | Comment"
    )
    body = extract_body(raw)
    assert "Workshop AI for Founders" in body
    assert "All reactions" not in body
    assert "See more" not in body


def test_handles_no_reactions_section():
    """Some posts have no reactions yet - body extraction should still work."""
    raw = (
        "MDEC | \xa0 | 1h | \xa0 |  ·  | "
        "Cyber Awareness Seminar 20 July 2026 at MDEC HQ"
    )
    body = extract_body(raw)
    assert "Cyber Awareness Seminar" in body


# ---------------------------------------------------------------------------
# Combined: parse_post end-to-end
# ---------------------------------------------------------------------------

def _scraper():
    s = FacebookWallScraper.__new__(FacebookWallScraper)
    s.name = "FacebookWall"
    s.base_url = "https://web.facebook.com"
    s.delay = 1.0
    s.last_request_time = 0.0
    s.pages = []
    return s


def test_parse_post_keeps_event_with_date():
    s = _scraper()
    raw = (
        "MDEC | 2h |  ·  | "
        "Workshop on AI for Founders, 18 June 2026, WORQ KL Sentral. Daftar sekarang. "
        "All reactions: | 5 | Like"
    )
    event = s._parse_post(raw, "MDEC", "https://web.facebook.com/MyMDEC")
    assert event is not None
    assert event["start_datetime"] == datetime(2026, 6, 18)
    assert "MDEC" in event["title"]
    assert "Workshop on AI for Founders" in event["title"]


def test_parse_post_drops_event_without_date():
    s = _scraper()
    raw = (
        "INSKEN | 3d |  ·  | "
        "Sepanjang Jun dan Julai, pelbagai program keusahawanan INSKEN kembali dibuka… "
        "All reactions: | 7"
    )
    # No specific date - should be dropped
    assert s._parse_post(raw, "INSKEN", "https://web.facebook.com/inskenofficial") is None


def test_parse_post_drops_post_without_event_keyword():
    s = _scraper()
    raw = (
        "INSKEN | 1d |  ·  | "
        "Salam Aidiladha daripada warga INSKEN pada 6 Jun 2026 "
        "All reactions: | 11"
    )
    # No event keyword - just a holiday greeting
    assert s._parse_post(raw, "INSKEN", "https://web.facebook.com/inskenofficial") is None


def test_parse_post_drops_short_text():
    s = _scraper()
    raw = "MDEC | 1h |  ·  | Workshop"
    assert s._parse_post(raw, "MDEC", "https://web.facebook.com/MyMDEC") is None


def test_event_keywords_include_malay_terms():
    """We expect event keywords to cover both English and Malay - this is
    a guardrail in case someone strips Malay terms in the future."""
    must_have = [
        # Format
        "seminar", "workshop", "bengkel", "kursus",
        # Call-to-action
        "daftar", "sertai", "register", "rsvp",
        # Invitation language Aiman cares about
        "jom hadir", "hadir beramai-ramai", "visit us",
        "you're invited", "anda dijemput", "save the date",
    ]
    missing = [k for k in must_have if k not in EVENT_KEYWORDS]
    assert not missing, f"Event keywords missing: {missing}"


def test_parse_post_accepts_jom_hadir_phrasing():
    """Common Malay invitation phrasing without 'daftar' must still trigger."""
    s = _scraper()
    raw = (
        "MCMC | 5h |  ·  | "
        "Pameran Inovasi Teknologi MCMC pada 18 Jun 2026 di Cyberjaya. "
        "Jom hadir beramai-ramai bersama keluarga. "
        "All reactions: | 12"
    )
    event = s._parse_post(raw, "MCMC", "https://web.facebook.com/MCMCgovmy")
    assert event is not None
    assert event["start_datetime"] == datetime(2026, 6, 18)


def test_parse_post_accepts_visit_us_phrasing():
    s = _scraper()
    raw = (
        "MDEC | 2h |  ·  | "
        "Open day at MDEC HQ on 25 July 2026. Visit us for a tour. "
        "All reactions: | 4"
    )
    event = s._parse_post(raw, "MDEC", "https://web.facebook.com/MyMDEC")
    assert event is not None
    assert event["start_datetime"] == datetime(2026, 7, 25)


def test_parse_post_accepts_save_the_date():
    s = _scraper()
    raw = (
        "INSKEN | 1d |  ·  | "
        "Save the date: SME Founders Roundtable on 30 August 2026. "
        "All reactions: | 9"
    )
    event = s._parse_post(raw, "INSKEN", "https://web.facebook.com/inskenofficial")
    assert event is not None
    assert event["start_datetime"] == datetime(2026, 8, 30)
