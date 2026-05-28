"""KUSKOP scraper regression tests."""
from datetime import datetime

import pytest

from backend.scrapers.orgs.kuskop import KuskopScraper


parse = KuskopScraper._parse_date


def test_dash_separated_malay_month():
    assert parse("27-Apr-2026") == datetime(2026, 4, 27)


def test_dash_separated_malay_mei():
    """'Mei' is Malay for May - must parse correctly."""
    assert parse("28-Mei-2026") == datetime(2026, 5, 28)


def test_dash_separated_dis():
    """'Dis' is Malay for December."""
    assert parse("15-Dis-2026") == datetime(2026, 12, 15)


def test_space_separated():
    assert parse("27 April 2026") == datetime(2026, 4, 27)


def test_inside_longer_text():
    assert parse("Date: 27-Apr-2026 9:00 pagi") == datetime(2026, 4, 27)


def test_garbage_returns_none():
    assert parse("") is None
    assert parse("not a date") is None
    assert parse("99-Smarch-2026") is None
