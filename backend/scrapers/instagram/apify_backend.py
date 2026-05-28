"""Apify backend - calls the apify/instagram-scraper actor.

Apify's run-sync-get-dataset-items endpoint blocks until the actor
finishes, then returns the dataset directly. For 1-2 profiles per call
this finishes in ~30-90 seconds, which is fine for our 8-hourly schedule.

Apify endpoint reference:
  POST https://api.apify.com/v2/acts/apify~instagram-scraper/run-sync-get-dataset-items
       (token passed via Authorization header, NOT the URL query string,
        so it doesn't end up in HTTP request logs)

Request body:
  {
    "directUrls": ["https://www.instagram.com/<username>/"],
    "resultsLimit": 12,
    "resultsType": "posts"
  }

Response: list of post objects with these fields we rely on:
  caption, displayUrl, url, timestamp, ownerUsername, shortCode
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import httpx

from .backend import IGBackend, IGPost

logger = logging.getLogger(__name__)

APIFY_ACTOR_ENDPOINT = (
    "https://api.apify.com/v2/acts/apify~instagram-scraper"
    "/run-sync-get-dataset-items"
)


class ApifyBackend(IGBackend):
    def __init__(self, token: str, timeout: float = 300.0):
        self._token = token
        self._timeout = timeout

    def fetch_profile_posts(self, username: str, limit: int = 12) -> list[IGPost]:
        try:
            response = httpx.post(
                APIFY_ACTOR_ENDPOINT,
                headers={"Authorization": f"Bearer {self._token}"},
                json={
                    "directUrls": [f"https://www.instagram.com/{username}/"],
                    "resultsLimit": limit,
                    "resultsType": "posts",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            items = response.json()
        except httpx.HTTPError as e:
            logger.warning(f"Apify: fetch failed for {username}: {e}")
            return []
        except ValueError as e:
            logger.warning(f"Apify: invalid JSON for {username}: {e}")
            return []

        if not isinstance(items, list):
            logger.warning(f"Apify: unexpected response shape for {username}: {type(items).__name__}")
            return []

        return [
            post
            for post in (self._to_post(item, username) for item in items)
            if post is not None
        ]

    @staticmethod
    def _to_post(item: dict, fallback_username: str) -> Optional[IGPost]:
        if not isinstance(item, dict):
            return None
        caption = item.get("caption") or ""
        image_url = item.get("displayUrl") or item.get("imageUrl") or ""
        post_url = item.get("url") or ""
        # Reconstruct URL from shortCode if 'url' is missing
        if not post_url:
            sc = item.get("shortCode") or ""
            if sc:
                post_url = f"https://www.instagram.com/p/{sc}/"
        timestamp_str = item.get("timestamp") or ""
        username = item.get("ownerUsername") or fallback_username

        # Apify returns ISO 8601 with Z suffix
        posted_at: Optional[datetime] = None
        if timestamp_str:
            try:
                posted_at = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except ValueError:
                posted_at = None

        if not post_url:
            return None
        return IGPost(
            post_url=post_url,
            caption=caption,
            image_url=image_url,
            posted_at=posted_at,
            username=username,
        )
