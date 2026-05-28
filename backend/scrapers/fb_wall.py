"""Facebook Page wall scraper - rendered with Playwright.

Decision (2026-05-27): Agencies have largely abandoned the FB Events tab
in favour of regular Page posts. We render each tracked agency's wall in
Chromium and extract the last ~15 posts. Posts that contain BOTH an
event-keyword (seminar, workshop, daftar, etc.) AND a parseable date are
saved as events.

Tradeoffs:
  + Works for the channel agencies actually use today
  + Simple Playwright workflow, no FB API key needed
  - Requires Chromium installed (~150 MB)
  - 30 sec per page; with 17 pages = 8.5 min per scrape run
  - Many posts are anniversary celebrations / reels / video posts that
    won't have a date - those are silently dropped
  - Posts with implicit dates ("throughout June and July") are dropped;
    only explicit DD Month YYYY style dates survive
"""
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .base import BaseScraper

logger = logging.getLogger(__name__)


# Posts must contain at least one of these to be considered event-shaped.
# Mix English + Malay because many KL agency pages post in Malay.
# Three families of signal:
#   1) Event-format words: seminar, workshop, hackathon, expo, etc.
#   2) Call-to-action verbs: register, daftar, join, sertai, RSVP, hadir
#   3) Invitation phrases: jom hadir, jemputan, save the date, visit us
EVENT_KEYWORDS = [
    # Format words (English)
    "seminar", "workshop", "webinar", "conference", "forum", "summit",
    "hackathon", "bootcamp", "training", "programme", "program",
    "symposium", "expo", "exhibition", "meetup", "networking", "launch",
    "open day", "info session", "demo day", "pitch day", "town hall",
    "townhall", "showcase", "convention", "festival", "roadshow",
    "masterclass", "fireside", "ama", "panel discussion",
    # Format words (Malay)
    "bengkel", "kursus", "latihan", "persidangan", "pelancaran",
    "dialog", "majlis", "pameran", "sambutan", "perasmian",
    # Call-to-action (English)
    "register", "rsvp", "sign up", "join us", "join our",
    "save the date", "mark your calendar", "don't miss",
    "limited seats", "free admission", "free entry",
    "tickets now", "tickets available", "book now",
    # Call-to-action (Malay)
    "daftar", "daftar sekarang", "sertai", "sertailah",
    "jom hadir", "jom sertai", "jom join",
    "hadir beramai-ramai", "beramai-ramai",
    "jemputan", "jemput", "tempahan",
    "tarikh tutup", "kuota terhad",
    # Invitation / visiting (English)
    "visit us", "come visit", "see you at", "see you there",
    "you're invited", "you are invited", "all welcome",
    "open to public", "open to the public", "public invited",
    # Invitation / visiting (Malay)
    "jumpa di", "jumpa anda di", "terbuka kepada umum",
    "terbuka kepada awam", "anda dijemput",
    # Generic upcoming markers
    "upcoming", "akan datang", "tidak lama lagi",
]

# Date patterns we accept. We REQUIRE an explicit year so we don't
# accidentally parse "5 June" as 5 June this year when it might be
# next year.
ENG_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
MALAY_MONTHS = {
    "januari": 1, "februari": 2, "mac": 3, "april": 4, "mei": 5,
    "jun": 6, "julai": 7, "ogos": 8, "september": 9, "oktober": 10,
    "november": 11, "disember": 12,
}
ALL_MONTHS = {**MALAY_MONTHS, **ENG_MONTHS}


class FacebookWallScraper(BaseScraper):
    """Scrape Page-wall posts from tracked agency Facebook pages.

    Pages list is in config/sources.yaml under fb_pages.
    """

    def __init__(self):
        super().__init__("FacebookWall", "https://web.facebook.com", delay=1.0)
        self.pages = self._load_pages()

    def _load_pages(self) -> list[dict]:
        """Load tracked Facebook pages from config/sources.yaml."""
        config_path = Path(__file__).resolve().parent.parent.parent / "config" / "sources.yaml"
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
            return config.get("fb_pages", []) or []
        except (OSError, yaml.YAMLError) as e:
            logger.error(f"FacebookWall: failed to load pages config: {e}")
            return []

    def scrape(self) -> list[dict]:
        if not self.pages:
            logger.info("FacebookWall: no pages configured, skipping.")
            return []

        # Lazy import - playwright is a heavy dep
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning(
                "FacebookWall: playwright not installed, skipping. "
                "Run: pip install playwright && python -m playwright install chromium"
            )
            return []

        events = []
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:
                logger.error(
                    f"FacebookWall: failed to launch Chromium ({e}). "
                    "Run: python -m playwright install chromium"
                )
                return []
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 1400},
                locale="en-US",
            )
            page = ctx.new_page()

            for entry in self.pages:
                name = entry.get("name", "")
                url = entry.get("url", "")
                if not url:
                    continue
                try:
                    page_events = self._scrape_one_page(page, name, url)
                    events.extend(page_events)
                    if page_events:
                        logger.info(f"FacebookWall {name}: {len(page_events)} event posts")
                    else:
                        logger.info(f"FacebookWall {name}: 0 event posts")
                except Exception as e:
                    logger.warning(f"FacebookWall {name}: error {e}")

            browser.close()

        events = self._deduplicate(events)
        logger.info(f"FacebookWall total: {len(events)} unique events")
        return events

    # ------------------------------------------------------------------
    # Per-page rendering
    # ------------------------------------------------------------------

    def _scrape_one_page(self, page, name: str, url: str) -> list[dict]:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(7000)

        # Dismiss the login modal if it appears
        try:
            page.locator("[aria-label='Close']").first.click(timeout=2500)
            page.wait_for_timeout(800)
        except Exception:
            pass

        # Scroll a few times so lazy-loaded posts surface
        for _ in range(5):
            page.evaluate("window.scrollBy(0, 1200)")
            page.wait_for_timeout(1500)

        articles = page.query_selector_all("[role='article']")
        events = []
        seen_titles = set()
        for article in articles[:20]:
            try:
                text = article.inner_text()
            except Exception:
                continue
            if not text or len(text) < 80:
                continue
            event = self._parse_post(text, name, url)
            if event and event["title"] not in seen_titles:
                seen_titles.add(event["title"])
                events.append(event)
        return events

    # ------------------------------------------------------------------
    # Post parsing
    # ------------------------------------------------------------------

    def _parse_post(self, text: str, agency_name: str, page_url: str) -> Optional[dict]:
        """Decide whether a post is an event announcement, and extract
        a structured event dict if so.
        """
        # Quick reject: must contain at least one event keyword
        text_lower = text.lower()
        if not any(kw in text_lower for kw in EVENT_KEYWORDS):
            return None

        # Quick reject: must contain a parseable date
        start_dt = self._extract_date(text)
        if start_dt is None:
            return None

        # Build a reasonable title from the first long line of post text.
        # The Page wall format puts the agency name and time before the
        # post body. Skip those.
        body = self._extract_post_body(text)
        if not body:
            return None
        # Title = first sentence or first 100 chars of body
        title = self._pick_title(body, agency_name)
        if not title or len(title) < 8:
            return None

        return self._create_event_dict(
            title=f"[{agency_name}] {title}",
            description=body[:500],
            start_datetime=start_dt,
            end_datetime=None,
            location="Malaysia",  # specific venue rarely in post text
            organiser=agency_name,
            source_url=page_url,
            categories=[],  # orchestrator re-categorises via filters.yaml
        )

    @staticmethod
    def _extract_post_body(text: str) -> str:
        """The first long content segment is usually the post body.

        FB renders posts as: '<Page Name> | 12h | · | <body> | All reactions:...'.
        Strip the prelude and the trailing reactions/comments.
        """
        # Remove anything from "All reactions:" onward
        cut = text.split("All reactions:")[0]
        # Find the first " · " separator and take everything after it
        parts = re.split(r"\s+·\s+", cut)
        if len(parts) > 1:
            body = parts[-1]
        else:
            body = cut
        # Strip see-more markers
        body = body.replace("… See more", "").replace("See more", "")
        # Strip reels-style audio prefixes that look like "Track Title" before the post
        body = re.sub(r"^\ufeff?[A-Za-z0-9 \-,'()]+\s+\|\s+\xa0\s+\|\s+", "", body)
        return body.strip()

    @staticmethod
    def _pick_title(body: str, agency_name: str) -> str:
        # Use the first sentence-ish chunk
        first = re.split(r"[.!?\n]", body, maxsplit=1)[0].strip()
        if not first:
            return ""
        # Cap length
        return first[:140]

    # ------------------------------------------------------------------
    # Date extraction: explicit DD Month YYYY (English or Malay)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_date(text: str) -> Optional[datetime]:
        # Pattern A: "DD Month YYYY"
        for m in re.finditer(
            r"\b(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})\b",
            text,
        ):
            day, month_str, year = m.groups()
            month = ALL_MONTHS.get(month_str.lower())
            if not month:
                continue
            try:
                return datetime(int(year), month, int(day))
            except ValueError:
                continue

        # Pattern B: "Month DD, YYYY" (English)
        for m in re.finditer(
            r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(20\d{2})\b",
            text,
        ):
            month_str, day, year = m.groups()
            month = ENG_MONTHS.get(month_str.lower())
            if not month:
                continue
            try:
                return datetime(int(year), month, int(day))
            except ValueError:
                continue

        # Pattern C: "DD/MM/YYYY" or "DD-MM-YYYY"
        m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", text)
        if m:
            day, month, year = m.groups()
            try:
                return datetime(int(year), int(month), int(day))
            except ValueError:
                pass

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
