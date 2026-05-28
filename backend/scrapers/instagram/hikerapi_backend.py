"""HikerAPI backend - direct IG profile + recent media calls.

HikerAPI documents a v1 endpoint at:
  GET https://api.hikerapi.com/v1/user/by/username?username=<u>

That returns a user object with `pk` (numeric user id). Then:
  GET https://api.hikerapi.com/v1/user/medias?user_id=<pk>&amount=12

Returns a list of media items with caption, image, timestamp, code (slug).

Auth: header `x-access-key: <HIKERAPI_KEY>`.

Per-request cost: ~$0.0006. Two calls per profile (resolve username + fetch
media), so ~$0.0012 per profile fetch.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from .backend import IGBackend, IGPost

logger = logging.getLogger(__name__)

API_BASE = "https://api.hikerapi.com/v1"


class HikerAPIBackend(IGBackend):
    def __init__(self, key: str, timeout: float = 30.0):
        self._key = key
        self._timeout = timeout

    def _headers(self) -> dict:
        return {"x-access-key": self._key, "Accept": "application/json"}

    def fetch_profile_posts(self, username: str, limit: int = 12) -> list[IGPost]:
        try:
            user = self._fetch_user(username)
            if not user or not user.get("pk"):
                logger.warning(f"HikerAPI: user not resolved for {username}")
                return []
            media = self._fetch_media(user["pk"], amount=limit)
        except httpx.HTTPError as e:
            logger.warning(f"HikerAPI: fetch failed for {username}: {e}")
            return []
        except ValueError as e:
            logger.warning(f"HikerAPI: invalid JSON for {username}: {e}")
            return []

        return [
            post
            for post in (self._to_post(m, username) for m in media or [])
            if post is not None
        ]

    def _fetch_user(self, username: str) -> Optional[dict]:
        r = httpx.get(
            f"{API_BASE}/user/by/username",
            params={"username": username},
            headers=self._headers(),
            timeout=self._timeout,
        )
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else None

    def _fetch_media(self, user_id, amount: int) -> list[dict]:
        r = httpx.get(
            f"{API_BASE}/user/medias",
            params={"user_id": user_id, "amount": amount},
            headers=self._headers(),
            timeout=self._timeout,
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        # Some HikerAPI responses wrap the list
        if isinstance(data, dict):
            for key in ("items", "results", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    @staticmethod
    def _to_post(item: dict, fallback_username: str) -> Optional[IGPost]:
        if not isinstance(item, dict):
            return None

        # caption can be in 'caption.text' or just 'caption_text'
        caption = ""
        cap = item.get("caption")
        if isinstance(cap, dict):
            caption = cap.get("text") or ""
        elif isinstance(cap, str):
            caption = cap
        if not caption:
            caption = item.get("caption_text") or ""

        # Image URL: prefer the largest 'image_versions2' candidate
        image_url = ""
        ivs = item.get("image_versions2") or {}
        if isinstance(ivs, dict):
            candidates = ivs.get("candidates") or []
            if isinstance(candidates, list) and candidates:
                largest = max(
                    candidates,
                    key=lambda c: (c.get("width", 0) if isinstance(c, dict) else 0),
                )
                if isinstance(largest, dict):
                    image_url = largest.get("url") or ""
        if not image_url:
            image_url = item.get("thumbnail_url") or item.get("display_url") or ""

        # Post URL: HikerAPI gives 'code' slug, build the canonical URL
        code = item.get("code") or item.get("shortcode") or ""
        post_url = f"https://www.instagram.com/p/{code}/" if code else (item.get("url") or "")

        # Username: prefer the user object embedded
        owner = item.get("user") or {}
        username = owner.get("username") if isinstance(owner, dict) else None
        username = username or fallback_username

        # Timestamp: HikerAPI uses 'taken_at' as unix seconds
        posted_at: Optional[datetime] = None
        ts = item.get("taken_at")
        if isinstance(ts, (int, float)):
            posted_at = datetime.fromtimestamp(ts, tz=timezone.utc)
        elif isinstance(ts, str):
            try:
                posted_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
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
