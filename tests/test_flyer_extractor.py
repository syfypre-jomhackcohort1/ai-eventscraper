"""Flyer extractor tests: pure-function pieces (no LLM calls)."""
import os
from datetime import datetime
from unittest.mock import patch

import pytest

from backend.scrapers.instagram.backend import IGPost
from backend.scrapers.instagram.flyer_extractor import (
    _caption_only_extract,
    _parse_iso_lenient,
    _parse_llm_json,
    extract_event,
)


# ---------------------------------------------------------------------------
# JSON parsing - LLMs sometimes wrap output in code fences
# ---------------------------------------------------------------------------

def test_parse_plain_json():
    assert _parse_llm_json('{"is_event": true}') == {"is_event": True}


def test_parse_fenced_json():
    raw = '```json\n{"is_event": true, "title": "Hi"}\n```'
    assert _parse_llm_json(raw) == {"is_event": True, "title": "Hi"}


def test_parse_garbled_with_object_inside():
    raw = "Here is your data: {\"is_event\": false} cheers"
    assert _parse_llm_json(raw) == {"is_event": False}


def test_parse_empty_returns_none():
    assert _parse_llm_json("") is None
    assert _parse_llm_json("not json at all") is None


# ---------------------------------------------------------------------------
# ISO date parsing
# ---------------------------------------------------------------------------

def test_iso_with_z():
    dt = _parse_iso_lenient("2026-06-18T10:00:00Z")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 6 and dt.day == 18


def test_iso_pads_single_digits():
    dt = _parse_iso_lenient("2026-6-8T09:00:00+08:00")
    assert dt is not None
    assert dt.month == 6 and dt.day == 8


def test_iso_garbage_returns_none():
    assert _parse_iso_lenient("") is None
    assert _parse_iso_lenient(None) is None
    assert _parse_iso_lenient("not a date") is None


# ---------------------------------------------------------------------------
# Caption-only fallback
# ---------------------------------------------------------------------------

def test_caption_only_extracts_dd_month_yyyy():
    p = IGPost(
        post_url="https://www.instagram.com/p/X/",
        caption="ASBhive Masterclass on 18 June 2026 at Demo Lab 2",
        image_url="",
        posted_at=None,
        username="asb.hive",
    )
    event = _caption_only_extract(p)
    assert event is not None
    assert event["start_datetime"] == datetime(2026, 6, 18)
    assert event["organiser"] == "asb.hive"


def test_caption_only_extracts_month_dd_yyyy():
    p = IGPost(
        post_url="https://www.instagram.com/p/X/",
        caption="Workshop June 18, 2026",
        image_url="",
        posted_at=None,
        username="u",
    )
    event = _caption_only_extract(p)
    assert event is not None
    assert event["start_datetime"] == datetime(2026, 6, 18)


def test_caption_only_skips_no_date():
    p = IGPost(
        post_url="https://www.instagram.com/p/X/",
        caption="Workshop coming soon, stay tuned",
        image_url="",
        posted_at=None,
        username="u",
    )
    assert _caption_only_extract(p) is None


def test_caption_only_skips_no_event_signal():
    p = IGPost(
        post_url="https://www.instagram.com/p/X/",
        caption="Selamat Hari Raya 6 June 2026",
        image_url="",
        posted_at=None,
        username="u",
    )
    # Has a date but no event keyword - should be skipped
    assert _caption_only_extract(p) is None


# ---------------------------------------------------------------------------
# extract_event integration with LLM_PROVIDER=disabled (uses caption-only)
# ---------------------------------------------------------------------------

def test_extract_event_disabled_provider_uses_caption_path():
    p = IGPost(
        post_url="https://www.instagram.com/p/X/",
        caption="Workshop on 18 June 2026 at WORQ KL Sentral",
        image_url="",
        posted_at=None,
        username="u",
    )
    with patch.dict(os.environ, {"LLM_PROVIDER": "disabled"}, clear=False):
        event = extract_event(p)
    assert event is not None
    assert event["source_platform"] == "instagram"


def test_extract_event_falls_back_when_llm_raises():
    """If the LLM call raises, we should fall back to caption-only."""
    p = IGPost(
        post_url="https://www.instagram.com/p/X/",
        caption="Workshop on 18 June 2026",
        image_url="",
        posted_at=None,
        username="u",
    )
    # Force the gemini call to fail by clearing the API key
    with patch.dict(os.environ, {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": ""}, clear=False):
        event = extract_event(p)
    # Still gets the event via caption-only fallback
    assert event is not None
    assert event["start_datetime"] == datetime(2026, 6, 18)
