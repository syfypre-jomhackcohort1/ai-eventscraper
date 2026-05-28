"""Peatix scraper using Playwright.

Peatix's HTML is JS-rendered; httpx alone gets back a 15KB shell with
no event content. We render `peatix.com/search?country=MY` with
Chromium and read the event cards directly.

Each card link's innerText reads like:
  'MAY 31\nSun, 1:00 PM\nAt Stickerrific C-31-G ... Jaya One Jalan ...'
  'JUN 20\nSat, 2:00 PM\nAt FabCafe Kuala Lumpur 19, Jalan PJS 11/14...'
  'OCT 25\nMon, 2:00 PM (3,355 days)\nOnline event\nC&D Health Talk\n...'

Format breakdown:
  Line 1: month + day  (e.g. 'MAY 31')
  Line 2: weekday + time, optionally + '(N days)' indicating future
  Line 3+: venue line starting with 'At ' OR 'Online event' OR title
  Last line: title or organiser

We parse permissively and rely on the orchestrator to drop past events
and out-of-region rows.

Env: set DISABLE_PLAYWRIGHT=1 to no-op this scraper. Useful on hosts with
<1 GB RAM (Render Free etc.) where Chromium would OOM the dyno.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Optional

from .base import BaseScraper

logger = logging.getLogger(__name__)


SEARCH_URLS = [
    "https://peatix.com/search?country=MY",
    "https://peatix.com/search?q=kuala+lumpur",
    "https://peatix.com/search?q=selangor",
]

ENG_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10,
    "NOVEMBER": 11, "DECEMBER": 12,
}

# 'MAY 31'  or  'JUN 20'
DATE_LINE_RE = re.compile(r"^([A-Z]{3,9})\s+(\d{1,2})$")
# 'Sun, 1:00 PM'  or  'Mon, 12:00 AM (4,412 days)'
TIME_LINE_RE = re.compile(
    r"^[A-Za-z]+,\s*(\d{1,2})(?::(\d{2}))?\s*[\u202f ]*([APap][Mm])"
)


class PeatixScraper(BaseScraper):
    """Scrape Peatix Malaysia events via Playwright-rendered search."""

    def __init__(self):
        super().__init__("Peatix", "https://peatix.com", delay=2.0)

    def scrape(self) -> list[dict]:
        if os.environ.get("DISABLE_PLAYWRIGHT", "").strip() in ("1", "true", "yes"):
            logger.info("Peatix: DISABLE_PLAYWRIGHT set, skipping.")
            return []

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning(
                "Peatix: playwright not installed, skipping. "
                "Run: pip install playwright && python -m playwright install chromium"
            )
            return []

        events = []
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                logger.error(f"Peatix: failed to launch Chromium: {e}")
                return []
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 1400},
                locale="en-US",
            )
            page = ctx.new_page()
            seen_urls = set()
            for url in SEARCH_URLS:
                try:
                    found = self._scrape_search_page(page, url, seen_urls)
                    events.extend(found)
                    logger.info(f"Peatix {url}: {len(found)} events")
                except Exception as e:
                    logger.warning(f"Peatix {url}: error {e}")
            browser.close()

        events = self._deduplicate(events)
        logger.info(f"Peatix total: {len(events)} unique events")
        return events

    def _scrape_search_page(self, page, url: str, seen_urls: set) -> list[dict]:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        for _ in range(3):
            page.evaluate("window.scrollBy(0, 1000)")
            page.wait_for_timeout(1500)

        cards = page.eval_on_selector_all(
            'a[href*="/event/"]',
            "els => els.map(e => ({href: e.href, text: e.innerText}))",
        )
        events = []
        for card in cards:
            href = card.get("href", "")
            # Strip tracking params for canonical URL + dedup key
            canonical = href.split("?", 1)[0]
            if not canonical or canonical in seen_urls:
                continue
            seen_urls.add(canonical)

            text = card.get("text") or ""
            event = self._parse_card(text, canonical)
            if event:
                events.append(event)
        return events

    def _parse_card(self, text: str, canonical_url: str) -> Optional[dict]:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) < 3:
            return None

        # Line 1: month + day
        m = DATE_LINE_RE.match(lines[0])
        if not m:
            return None
        month_str, day_str = m.groups()
        month = ENG_MONTHS.get(month_str.upper())
        if not month:
            return None
        day = int(day_str)

        # Line 2: time (we use it + assume current/next year)
        hour, minute = 0, 0
        time_match = TIME_LINE_RE.match(lines[1])
        if time_match:
            h, mn, ampm = time_match.groups()
            hour = int(h)
            minute = int(mn) if mn else 0
            if ampm.upper() == "PM" and hour != 12:
                hour += 12
            elif ampm.upper() == "AM" and hour == 12:
                hour = 0

        # Year inference: if the parsed date is more than 30 days ago,
        # assume next year. (Peatix's '(N days)' marker indicates future
        # but parsing it is fragile; this rule is more reliable.)
        now = datetime.now()
        try:
            candidate = datetime(now.year, month, day, hour, minute)
        except ValueError:
            return None
        if (now - candidate).days > 30:
            try:
                candidate = datetime(now.year + 1, month, day, hour, minute)
            except ValueError:
                return None
        start_dt = candidate

        # Venue line: first line starting with 'At ' or equal to 'Online event'
        location = "Kuala Lumpur"
        venue_idx = None
        for i in range(2, len(lines)):
            if lines[i].lower() == "online event":
                location = "Online"
                venue_idx = i
                break
            if lines[i].startswith("At "):
                location = lines[i][3:].strip()
                venue_idx = i
                break

        # Title: line after the venue, then strip trailing 'By <organiser>'
        title = ""
        organiser = ""
        if venue_idx is not None and venue_idx + 1 < len(lines):
            title = lines[venue_idx + 1]
            # Subsequent line(s) may be organiser
            if venue_idx + 2 < len(lines):
                organiser_line = lines[venue_idx + 2]
                if organiser_line.lower().startswith("by "):
                    organiser = organiser_line[3:].strip()
        if not title:
            # Fall back to last line
            title = lines[-1]
        if not title or len(title) < 4:
            return None

        return self._create_event_dict(
            title=title,
            description=text[:500],
            start_datetime=start_dt,
            end_datetime=None,
            location=location,
            organiser=organiser,
            source_url=canonical_url,
            categories=[],
            image_url="",
        )

    @staticmethod
    def _deduplicate(events: list[dict]) -> list[dict]:
        seen = set()
        unique = []
        for ev in events:
            key = (ev["title"].lower().strip(), ev.get("start_datetime"))
            if key not in seen:
                seen.add(key)
                unique.append(ev)
        return unique
