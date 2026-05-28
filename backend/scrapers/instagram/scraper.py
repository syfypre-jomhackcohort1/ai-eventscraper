"""Top-level Instagram scraper.

For each tracked profile:
  1. Backend (Apify / HikerAPI / Disabled) returns recent IG posts
  2. FlyerExtractor (Gemini / OpenAI / caption-only) extracts events
  3. Resulting events are returned to the orchestrator like any other source

Profiles configured in config/sources.yaml under `ig_profiles`.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ..base import BaseScraper
from .backend import IGBackend, IGPost, make_backend
from .flyer_extractor import extract_event

logger = logging.getLogger(__name__)


class InstagramScraper(BaseScraper):
    def __init__(self):
        super().__init__("Instagram", "https://www.instagram.com", delay=1.0)
        self.backend: IGBackend = make_backend()
        self.profiles = self._load_profiles()

    def _load_profiles(self) -> list[str]:
        config_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "config" / "sources.yaml"
        )
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
            entries = config.get("ig_profiles", []) or []
            return [
                e["username"].strip().lstrip("@")
                for e in entries
                if isinstance(e, dict) and e.get("username")
            ]
        except (OSError, yaml.YAMLError) as e:
            logger.error(f"Instagram: failed to load profiles config: {e}")
            return []

    def scrape(self) -> list[dict]:
        if not self.profiles:
            logger.info("Instagram: no profiles configured, skipping.")
            return []

        from .backend import DisabledBackend
        if isinstance(self.backend, DisabledBackend):
            # Backend is disabled - skip silently (factory already logged once).
            return []

        events = []
        for username in self.profiles:
            try:
                posts = self.backend.fetch_profile_posts(username, limit=12)
            except Exception as e:
                logger.warning(f"Instagram {username}: backend failed: {e}")
                continue
            logger.info(f"Instagram {username}: backend returned {len(posts)} posts")

            kept = 0
            for post in posts:
                # Cheap pre-filter: caption must look event-shaped before
                # we burn an LLM call.
                if not post.has_event_signal():
                    continue
                event = extract_event(post)
                if event:
                    events.append(event)
                    kept += 1
            logger.info(f"Instagram {username}: {kept} events after extraction")

        events = self._deduplicate(events)
        logger.info(f"Instagram total: {len(events)} unique events")
        return events

    @staticmethod
    def _deduplicate(events: list[dict]) -> list[dict]:
        seen = set()
        unique = []
        for ev in events:
            key = (ev.get("title", "").lower().strip(), str(ev.get("start_datetime", "")))
            if key not in seen:
                seen.add(key)
                unique.append(ev)
        return unique
