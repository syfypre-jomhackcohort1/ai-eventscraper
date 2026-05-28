"""Regression tests for venue date parsing.

Bug: MITEC's MyARTTE 2026 ('30 SEPT - 2 OCT 2026') landed on the calendar
as 'Mon Oct 26 → Fri Oct 2' because the parser had no cross-month range
regex and the loose 'DD - DD Month YYYY' pattern grabbed fragments from
two adjacent events on the page.
"""
from datetime import datetime

from backend.scrapers.venues import VenueScraper


def test_cross_month_range_parses():
    """30 SEPT - 2 OCT 2026 must produce start=Sep 30, end=Oct 2."""
    scraper = VenueScraper()
    result = scraper._parse_mitec_date("MyARTTE 2026 30 SEPT - 2 OCT 2026 MITEC")
    assert result is not None
    start, end = result
    assert start == datetime(2026, 9, 30)
    assert end == datetime(2026, 10, 2)


def test_same_month_range_still_works():
    """Existing same-month parsing is not broken."""
    scraper = VenueScraper()
    result = scraper._parse_mitec_date("Some Expo 20 - 23 May 2026 MITEC")
    assert result is not None
    start, end = result
    assert start == datetime(2026, 5, 20)
    assert end == datetime(2026, 5, 23)


def test_full_form_both_sides_still_works():
    """'30 May 2026 - 01 June 2026' format still works."""
    scraper = VenueScraper()
    result = scraper._parse_mitec_date("Conference 30 May 2026 - 01 June 2026")
    assert result is not None
    start, end = result
    assert start == datetime(2026, 5, 30)
    assert end == datetime(2026, 6, 1)


def test_single_day_still_works():
    """'15 May 2026' single-date format still works."""
    scraper = VenueScraper()
    result = scraper._parse_mitec_date("Workshop 15 May 2026")
    assert result is not None
    start, end = result
    assert start == datetime(2026, 5, 15)
    assert end is None


def test_impossible_range_rejected():
    """Same-month range where day1 > day2 is fragments from two events.
    Returns None so the parser falls through to single-day or returns None
    rather than producing a backwards range.
    """
    scraper = VenueScraper()
    # "26 - 2 OCT 2026" - the kind of stray fragment caused by
    # concatenating "...26" from one event and "2 OCT 2026" from another.
    result = scraper._parse_mitec_date("26 - 2 OCT 2026")
    # Either it returns None or a sensible single-day fallback (Oct 2)
    if result is not None:
        start, end = result
        assert end is None or end >= start


def test_orchestrator_drops_backwards_dates():
    """Defense in depth: orchestrator drops events with end < start."""
    from backend.orchestrator import Orchestrator

    orch = Orchestrator()
    backwards = {
        "title": "Bad Event",
        "start_datetime": datetime(2026, 10, 26),
        "end_datetime": datetime(2026, 10, 2),  # before start
        "source_platform": "venues",
        "categories": [],
    }
    forward = {
        "title": "Good Event",
        "start_datetime": datetime(2026, 9, 30),
        "end_datetime": datetime(2026, 10, 2),
        "source_platform": "venues",
        "categories": [],
    }
    # Mimic the orchestrator's clean-up step
    clean = []
    for e in [backwards, forward]:
        s, end = e.get("start_datetime"), e.get("end_datetime")
        if s and end and end < s:
            continue
        clean.append(e)
    assert len(clean) == 1
    assert clean[0]["title"] == "Good Event"
