"""Pluggable Instagram backend interface.

A backend's only job is: given a username, return a list of recent
public posts. It does NOT extract events - that's done downstream by
the FlyerExtractor.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class IGPost:
    """A single Instagram post in a backend-agnostic shape."""
    post_url: str
    caption: str
    image_url: str
    posted_at: Optional[datetime]
    username: str

    def has_event_signal(self) -> bool:
        """Cheap heuristic: does this post look like it might be an event
        announcement? Used to short-circuit expensive LLM calls.

        Requires BOTH a content keyword (workshop, register, etc.) AND a
        date hint (year, day-month). A bare year alone isn't enough -
        otherwise 'Selamat Hari Raya 6 June 2026' would pass.
        """
        if not self.caption:
            return False
        text = self.caption.lower()

        content_markers = (
            # Format
            "seminar", "workshop", "webinar", "conference", "forum",
            "summit", "hackathon", "bootcamp", "training", "expo",
            "exhibition", "meetup", "networking", "launch", "showcase",
            "open day", "info session", "demo day", "masterclass",
            "roundtable", "fireside", "panel",
            "bengkel", "kursus", "majlis", "pelancaran",
            # Call to action
            "register", "rsvp", "sign up", "save the date",
            "daftar", "sertai", "jom hadir", "anda dijemput",
        )
        if not any(m in text for m in content_markers):
            return False

        # Date hint - any of: explicit year, "DD Month" pattern, or a
        # date-suggestive token. Cheap regex.
        import re as _re
        if _re.search(r"\b20\d{2}\b", text):
            return True
        if _re.search(
            r"\b\d{1,2}\s+(jan|feb|mac|apr|mei|may|jun|jul|julai|aug|ogos|sep|sept|okt|oct|nov|dis|dec)",
            text,
        ):
            return True
        if _re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text):
            return True
        return False


class IGBackend(ABC):
    """Abstract IG backend. Subclasses implement fetch_profile_posts."""

    @abstractmethod
    def fetch_profile_posts(self, username: str, limit: int = 12) -> list[IGPost]:
        """Return up to `limit` recent public posts for `username`.
        Returns [] on any error - the caller logs and continues."""
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__


class DisabledBackend(IGBackend):
    """No-op backend used when no IG provider is configured.

    Returns [] and logs once so it's clear why we're not getting events.
    """

    _logged = False

    def fetch_profile_posts(self, username: str, limit: int = 12) -> list[IGPost]:
        if not DisabledBackend._logged:
            logger.info(
                "IG backend disabled - set IG_BACKEND=apify (with APIFY_TOKEN) "
                "or IG_BACKEND=hikerapi (with HIKERAPI_KEY) to enable Instagram "
                "scraping."
            )
            DisabledBackend._logged = True
        return []


def make_backend() -> IGBackend:
    """Factory: pick the backend based on IG_BACKEND env var.

    The standard entry points (`backend/main.py` for the API server,
    `backend/orchestrator.py` for standalone scrape runs) load `.env` at
    import time, so by the time this factory runs, env vars are populated.

    Falls back to DisabledBackend if config is missing or the chosen
    provider's API key isn't set. Never raises - so the orchestrator
    can include this scraper unconditionally.
    """
    choice = (os.environ.get("IG_BACKEND") or "disabled").strip().lower()

    if choice == "apify":
        token = os.environ.get("APIFY_TOKEN", "").strip()
        if not token:
            logger.warning("IG_BACKEND=apify but APIFY_TOKEN is empty; using DisabledBackend")
            return DisabledBackend()
        from .apify_backend import ApifyBackend
        return ApifyBackend(token=token)

    if choice == "hikerapi":
        key = os.environ.get("HIKERAPI_KEY", "").strip()
        if not key:
            logger.warning("IG_BACKEND=hikerapi but HIKERAPI_KEY is empty; using DisabledBackend")
            return DisabledBackend()
        from .hikerapi_backend import HikerAPIBackend
        return HikerAPIBackend(key=key)

    if choice not in ("disabled", ""):
        logger.warning(f"Unknown IG_BACKEND={choice!r}; using DisabledBackend")
    return DisabledBackend()
