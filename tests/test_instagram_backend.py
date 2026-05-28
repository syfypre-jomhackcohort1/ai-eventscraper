"""Backend factory tests: env-driven provider selection, no real HTTP."""
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from backend.scrapers.instagram.backend import (
    DisabledBackend,
    IGPost,
    make_backend,
)
from backend.scrapers.instagram.apify_backend import ApifyBackend
from backend.scrapers.instagram.hikerapi_backend import HikerAPIBackend


# ---------------------------------------------------------------------------
# Factory selection
# ---------------------------------------------------------------------------

def test_make_backend_defaults_to_disabled():
    with patch.dict(os.environ, {}, clear=True):
        b = make_backend()
        assert isinstance(b, DisabledBackend)


def test_make_backend_apify_without_token_falls_back():
    with patch.dict(os.environ, {"IG_BACKEND": "apify", "APIFY_TOKEN": ""}, clear=True):
        b = make_backend()
        assert isinstance(b, DisabledBackend)


def test_make_backend_apify_with_token():
    with patch.dict(os.environ, {"IG_BACKEND": "apify", "APIFY_TOKEN": "tok"}, clear=True):
        b = make_backend()
        assert isinstance(b, ApifyBackend)


def test_make_backend_hikerapi_with_key():
    with patch.dict(os.environ, {"IG_BACKEND": "hikerapi", "HIKERAPI_KEY": "k"}, clear=True):
        b = make_backend()
        assert isinstance(b, HikerAPIBackend)


def test_make_backend_unknown_falls_back_to_disabled():
    with patch.dict(os.environ, {"IG_BACKEND": "octoparse"}, clear=True):
        b = make_backend()
        assert isinstance(b, DisabledBackend)


def test_disabled_backend_returns_empty():
    b = DisabledBackend()
    assert b.fetch_profile_posts("any") == []


# ---------------------------------------------------------------------------
# IGPost event-signal heuristic
# ---------------------------------------------------------------------------

def test_post_with_event_keyword_passes():
    p = IGPost(
        post_url="https://www.instagram.com/p/X/",
        caption="Workshop on AI for Founders 18 June 2026 at WORQ KL Sentral. Register now.",
        image_url="https://img/x.jpg",
        posted_at=None,
        username="u",
    )
    assert p.has_event_signal()


def test_post_with_no_signal_skipped():
    p = IGPost(
        post_url="https://www.instagram.com/p/X/",
        caption="Selamat Hari Raya Aidiladha to all our followers",
        image_url="",
        posted_at=None,
        username="u",
    )
    assert not p.has_event_signal()


def test_post_with_year_only_passes():
    """A 2026 mention alone is enough to keep the post in the LLM funnel."""
    p = IGPost(
        post_url="https://www.instagram.com/p/X/",
        caption="Save the date for 18 June 2026!",
        image_url="",
        posted_at=None,
        username="u",
    )
    assert p.has_event_signal()


# ---------------------------------------------------------------------------
# Apify response parsing
# ---------------------------------------------------------------------------

def test_apify_to_post_handles_typical_payload():
    item = {
        "url": "https://www.instagram.com/p/abc/",
        "caption": "Workshop on 18 June 2026",
        "displayUrl": "https://scontent.cdninstagram.com/x.jpg",
        "timestamp": "2026-05-13T10:00:00.000Z",
        "ownerUsername": "asb.hive",
    }
    post = ApifyBackend._to_post(item, "fallback")
    assert post is not None
    assert post.username == "asb.hive"
    assert post.posted_at == datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    assert "18 June 2026" in post.caption


def test_apify_to_post_returns_none_without_url():
    assert ApifyBackend._to_post({"caption": "no url"}, "u") is None


def test_apify_to_post_returns_none_for_non_dict():
    assert ApifyBackend._to_post("garbage", "u") is None


# ---------------------------------------------------------------------------
# HikerAPI response parsing
# ---------------------------------------------------------------------------

def test_hikerapi_to_post_handles_typical_payload():
    item = {
        "code": "abc",
        "caption": {"text": "Workshop on 18 June 2026"},
        "image_versions2": {"candidates": [
            {"width": 1080, "height": 1080, "url": "https://big.jpg"},
            {"width": 240, "height": 240, "url": "https://small.jpg"},
        ]},
        "taken_at": 1747094400,  # unix seconds
        "user": {"username": "asb.hive"},
    }
    post = HikerAPIBackend._to_post(item, "fallback")
    assert post is not None
    assert post.post_url == "https://www.instagram.com/p/abc/"
    assert post.image_url == "https://big.jpg"
    assert post.username == "asb.hive"
    assert "18 June 2026" in post.caption


def test_hikerapi_to_post_caption_text_form():
    """Some HikerAPI variants use 'caption_text' instead of nested object."""
    item = {
        "code": "abc",
        "caption_text": "fallback caption",
        "taken_at": 1747094400,
    }
    post = HikerAPIBackend._to_post(item, "u")
    assert post.caption == "fallback caption"
