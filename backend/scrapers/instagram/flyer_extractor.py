"""Vision-LLM extractor: turn an IG post (caption + flyer image) into a
structured event dict.

Supports two providers via env var LLM_PROVIDER:
  * gemini    (default; cheapest; uses google-genai SDK if installed,
                falls back to direct REST call)
  * openai    (uses openai SDK if installed, falls back to REST)
  * disabled  (no LLM - we rely on caption regex only)

We try to extract: title, start_datetime, end_datetime, location.
Returns None if the post doesn't look like an event.

Cost ballpark (Gemini 2.0 Flash, May 2026): ~$0.0001 per image. Even at
30 organisers x 12 posts = 360 LLM calls per scrape run, that's ~4 cents.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

import httpx

from .backend import IGPost

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are extracting structured event data from an Instagram post that "
    "may be advertising an upcoming event. The image is usually an event "
    "flyer. Return strict JSON with these fields and nothing else:\n"
    "  is_event: bool (true only if this is an upcoming event announcement)\n"
    "  title: short event title (string)\n"
    "  start_datetime: ISO 8601 with timezone, or null if unknown\n"
    "  end_datetime: ISO 8601 with timezone, or null\n"
    "  location: venue + city, or null\n"
    "  organiser: organising body, or null\n"
    "  registration_url: URL if visible in caption or flyer, or null\n"
    "Rules:\n"
    "- All datetimes in Asia/Kuala_Lumpur (UTC+08:00) unless the flyer says "
    "otherwise\n"
    "- If the post is a recap of a past event, an anniversary post, a "
    "marketing reel without specific date, or holiday greeting, set "
    "is_event=false and leave other fields null\n"
    "- If is_event=true but you can't read the date from the flyer, set "
    "start_datetime=null - do NOT guess\n"
    "- Output JSON only, no prose, no markdown fences"
)


def _user_prompt(post: IGPost) -> str:
    return (
        f"Instagram caption:\n{post.caption[:2000]}\n\n"
        f"Username: {post.username}\n"
        f"Posted at: {post.posted_at.isoformat() if post.posted_at else 'unknown'}\n\n"
        f"Extract event data from this post and the attached flyer image."
    )


def extract_event(post: IGPost) -> Optional[dict]:
    """Try the configured LLM provider. Returns event dict or None.

    The dict shape is the standard event dict used by other scrapers
    (matches BaseScraper._create_event_dict output).
    """
    provider = (os.environ.get("LLM_PROVIDER") or "gemini").strip().lower()

    if provider == "disabled":
        return _caption_only_extract(post)

    try:
        if provider == "openai":
            raw = _call_openai(post)
        else:  # default to gemini
            raw = _call_gemini(post)
    except Exception as e:
        logger.warning(f"FlyerExtractor: LLM call failed for {post.post_url}: {e}")
        return _caption_only_extract(post)

    parsed = _parse_llm_json(raw)
    if not parsed or not parsed.get("is_event"):
        return None

    start_dt = _parse_iso_lenient(parsed.get("start_datetime"))
    if not start_dt:
        return None

    end_dt = _parse_iso_lenient(parsed.get("end_datetime"))
    title = (parsed.get("title") or "").strip()
    if not title or len(title) < 3:
        return None

    return {
        "title": title,
        "description": post.caption[:500],
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "location": parsed.get("location") or "Malaysia",
        "is_virtual": False,
        "organiser": parsed.get("organiser") or post.username,
        "source_platform": "instagram",
        "source_url": parsed.get("registration_url") or post.post_url,
        "categories": [],
        "image_url": post.image_url,
    }


# ---------------------------------------------------------------------------
# Caption-only fallback (no LLM)
# ---------------------------------------------------------------------------

_DATE_RE_DM = re.compile(
    r"\b(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})\b"
)
_DATE_RE_MD = re.compile(
    r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(20\d{2})\b"
)
_MONTHS = {
    "jan": 1, "january": 1, "januari": 1,
    "feb": 2, "february": 2, "februari": 2,
    "mac": 3, "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "mei": 5, "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7, "julai": 7,
    "ogos": 8, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oct": 10, "october": 10, "oktober": 10,
    "nov": 11, "november": 11,
    "dis": 12, "dec": 12, "december": 12, "disember": 12,
}


def _caption_only_extract(post: IGPost) -> Optional[dict]:
    """Last-resort extractor when no LLM is available. Looks for an
    explicit date in the caption. Skips post if no date or no signal."""
    if not post.has_event_signal():
        return None
    text = post.caption
    start_dt = None
    for m in _DATE_RE_DM.finditer(text):
        d, mo, y = m.groups()
        month = _MONTHS.get(mo.lower())
        if month:
            try:
                start_dt = datetime(int(y), month, int(d))
                break
            except ValueError:
                continue
    if start_dt is None:
        for m in _DATE_RE_MD.finditer(text):
            mo, d, y = m.groups()
            month = _MONTHS.get(mo.lower())
            if month:
                try:
                    start_dt = datetime(int(y), month, int(d))
                    break
                except ValueError:
                    continue
    if start_dt is None:
        return None

    # Title: first non-empty line of caption, capped
    first_line = next((l.strip() for l in text.split("\n") if l.strip()), "")
    title = first_line[:140] if first_line else f"Post by @{post.username}"

    return {
        "title": title,
        "description": text[:500],
        "start_datetime": start_dt,
        "end_datetime": None,
        "location": "Malaysia",
        "is_virtual": False,
        "organiser": post.username,
        "source_platform": "instagram",
        "source_url": post.post_url,
        "categories": [],
        "image_url": post.image_url,
    }


# ---------------------------------------------------------------------------
# Provider calls
# ---------------------------------------------------------------------------

def _call_gemini(post: IGPost) -> str:
    """Call Gemini 2.0 Flash via REST. Returns the model's text response."""
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    parts = [
        {"text": SYSTEM_PROMPT + "\n\n" + _user_prompt(post)},
    ]
    if post.image_url:
        # Gemini accepts inline image bytes OR a fileUri. Inline is simpler.
        try:
            img_bytes = httpx.get(post.image_url, timeout=20.0, follow_redirects=True).content
            import base64
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(img_bytes).decode(),
                }
            })
        except Exception as e:
            logger.debug(f"FlyerExtractor: image fetch failed: {e}")

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 600,
            "responseMimeType": "application/json",
        },
    }

    r = httpx.post(url, params={"key": api_key}, json=payload, timeout=60.0)
    r.raise_for_status()
    data = r.json()
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts_out = candidates[0].get("content", {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts_out)


def _call_openai(post: IGPost) -> str:
    """Call OpenAI's responses API with a vision-capable model."""
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    content = [{"type": "text", "text": _user_prompt(post)}]
    if post.image_url:
        content.append({
            "type": "image_url",
            "image_url": {"url": post.image_url},
        })

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 600,
    }

    r = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60.0,
    )
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------

def _parse_llm_json(raw: str) -> Optional[dict]:
    """LLMs sometimes wrap JSON in code fences. Strip and parse."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        # Strip ```json ... ```
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find a JSON object inside the text
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


def _parse_iso_lenient(s) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    s = s.strip().replace("Z", "+00:00")
    # Pad single-digit month/day if needed
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(.*)$", s)
    if m:
        y, mo, d, rest = m.groups()
        s = f"{y}-{int(mo):02d}-{int(d):02d}{rest}"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None
