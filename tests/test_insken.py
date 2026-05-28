"""INSKEN scraper regression tests for date parsing and card structure."""
from datetime import datetime

import pytest

from backend.scrapers.orgs.insken import InskenScraper


parse_range = InskenScraper._parse_date_range


def test_basic_range_english_month():
    assert parse_range("3 - 5 Jun 2026") == (datetime(2026, 6, 3), datetime(2026, 6, 5))


def test_range_malay_month():
    assert parse_range("13 - 14 Mei 2026") == (datetime(2026, 5, 13), datetime(2026, 5, 14))


def test_range_with_em_dash():
    assert parse_range("9 – 11 Jun 2026") == (datetime(2026, 6, 9), datetime(2026, 6, 11))


def test_range_with_full_month_name():
    assert parse_range("19 - 21 June 2026") == (datetime(2026, 6, 19), datetime(2026, 6, 21))


def test_range_invalid_returns_none():
    assert parse_range("not a date") is None
    assert parse_range("") is None


def test_range_unknown_month_returns_none():
    assert parse_range("3 - 5 Smarch 2026") is None


def test_range_backwards_returns_none():
    """End before start -> reject (parser-fragments bug pattern)."""
    assert parse_range("5 - 3 Jun 2026") is None
