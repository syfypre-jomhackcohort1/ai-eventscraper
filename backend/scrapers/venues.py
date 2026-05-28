"""Venue scraper for MITEC and KLCC Convention Centre event calendars."""
import re
import logging
from datetime import datetime
from typing import Optional

from .base import BaseScraper

logger = logging.getLogger(__name__)


class VenueScraper(BaseScraper):
    """Scrape events from major KL venue calendars (MITEC, KLCC)."""

    def __init__(self):
        super().__init__("Venues", "https://mitec.com.my", delay=3.0)

    def scrape(self) -> list[dict]:
        """Scrape events from all venue calendars."""
        events = []
        events.extend(self._scrape_mitec())
        events.extend(self._scrape_klcc())
        logger.info(f"Venues total: {len(events)} events")
        return events

    # ------------------------------------------------------------------
    # MITEC
    # ------------------------------------------------------------------

    def _scrape_mitec(self) -> list[dict]:
        """Scrape MITEC event calendar.

        MITEC renders each event as a <div class="card"><div class="card-body">
        block containing a date string and an h2 title. We iterate `.card`
        elements (NOT h2 tags walking up to parents) so date text never
        leaks across card boundaries. The page also has a "Past Events"
        section with the same markup; we use the section heading position
        to decide which cards are upcoming vs past.
        """
        events = []
        url = "https://mitec.com.my/visit/event-calendar/"

        html = self._fetch_html(url)
        if not html:
            logger.warning("MITEC: could not fetch page")
            return []

        soup = self._parse_html(html)

        # Find the "Past Events" heading - cards after it are historical
        past_marker = None
        for h in soup.find_all(["h1", "h2", "h3"]):
            if "PAST EVENTS" in h.get_text(strip=True).upper():
                past_marker = h
                break

        for card in soup.select(".card"):
            # Skip if this card sits after the "Past Events" heading
            if past_marker is not None:
                # past_marker is later in document order than this card iff
                # past_marker comes after card in find_all order. Simpler:
                # check if past_marker appears as a previous sibling/ancestor
                # before this card. Use sourcepos comparison:
                # cards before past_marker have a smaller string offset.
                if hasattr(card, "sourcepos") and hasattr(past_marker, "sourcepos"):
                    pass  # bs4 doesn't track sourcepos by default
                # Cheap proxy: search for past_marker among elements that
                # come before the card. If found, card is past.
                preceding_h_texts = [
                    h.get_text(strip=True).upper()
                    for h in card.find_all_previous(["h1", "h2", "h3"], limit=20)
                ]
                if any("PAST EVENTS" in t for t in preceding_h_texts):
                    continue

            body = card.find(class_="card-body") or card
            h2 = body.find("h2")
            if not h2:
                continue

            title = h2.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            if title.upper() in ("UPCOMING EVENTS", "PAST EVENTS"):
                continue

            # Extract date text from the card body, EXCLUDING the title.
            # Build a string from text nodes that aren't inside the h2.
            parts = []
            for el in body.descendants:
                if hasattr(el, "find_parent") and el.find_parent("h2") is not None:
                    continue
                if isinstance(el, str):
                    s = el.strip()
                    if s:
                        parts.append(s)
            date_text = " ".join(parts)

            date_range = self._parse_mitec_date(date_text)
            if not date_range:
                continue
            start_dt, end_dt = date_range

            # Sanity: skip events whose end is before start (parser regression)
            if end_dt and end_dt < start_dt:
                logger.debug(
                    f"MITEC: dropping {title!r} - parsed end {end_dt} before start {start_dt}"
                )
                continue

            # Skip events that already ended
            if (end_dt or start_dt) < datetime.now().replace(hour=0, minute=0, second=0, microsecond=0):
                continue

            link = h2.find("a") or body.find("a")
            source_url = ""
            if link:
                source_url = link.get("href", "") or ""
                if source_url and not source_url.startswith("http"):
                    source_url = f"https://mitec.com.my{source_url}"

            events.append(self._create_event_dict(
                title=title,
                start_datetime=start_dt,
                end_datetime=end_dt,
                location="MITEC, Kuala Lumpur",
                organiser="MITEC",
                source_url=source_url,
                categories=[self._categorize(title)],
            ))

        events = self._deduplicate(events)
        logger.info(f"MITEC: found {len(events)} upcoming events")
        return events

    def _parse_mitec_date(self, text: str) -> Optional[tuple]:
        """Parse MITEC date formats. Order matters: try most specific first
        so cross-month patterns win before the loose "DD - DD Month YYYY"
        regex grabs fragments from neighbouring events.
        """
        # Pattern: "DD Month YYYY - DD Month YYYY" (full-form both sides)
        match = re.search(
            r"(\d{1,2})\s+(\w+)\s+(\d{4})\s*-\s*(\d{1,2})\s+(\w+)\s+(\d{4})", text
        )
        if match:
            d1, m1, y1, d2, m2, y2 = match.groups()
            month1 = self._month_to_num(m1)
            month2 = self._month_to_num(m2)
            if month1 and month2:
                try:
                    start = datetime(int(y1), month1, int(d1))
                    end = datetime(int(y2), month2, int(d2))
                    if end >= start:
                        return (start, end)
                except ValueError:
                    pass

        # Pattern: "DD Month - DD Month YYYY" (cross-month, single year)
        # e.g. "30 SEPT - 2 OCT 2026"
        match = re.search(
            r"(\d{1,2})\s+(\w+)\s*-\s*(\d{1,2})\s+(\w+)\s+(\d{4})", text
        )
        if match:
            d1, m1, d2, m2, year = match.groups()
            month1 = self._month_to_num(m1)
            month2 = self._month_to_num(m2)
            if month1 and month2:
                try:
                    start = datetime(int(year), month1, int(d1))
                    end = datetime(int(year), month2, int(d2))
                    # Cross-year wrap: "30 DEC - 2 JAN 2027" - end month < start month
                    if month2 < month1:
                        end = datetime(int(year) + 1, month2, int(d2))
                    if end >= start:
                        return (start, end)
                except ValueError:
                    pass

        # Pattern: "DD - DD Month YYYY" (same-month range)
        match = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})\s+(\w+)\s+(\d{4})", text)
        if match:
            day1, day2, month_str, year = match.groups()
            month = self._month_to_num(month_str)
            if month:
                try:
                    start = datetime(int(year), month, int(day1))
                    end = datetime(int(year), month, int(day2))
                    # Sanity: start day must be <= end day. If not, this is
                    # almost certainly fragments from two different events.
                    if int(day1) <= int(day2):
                        return (start, end)
                except ValueError:
                    pass

        # Pattern: "DD Month YYYY" (single day)
        match = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text)
        if match:
            day, month_str, year = match.groups()
            month = self._month_to_num(month_str)
            if month:
                try:
                    start = datetime(int(year), month, int(day))
                    return (start, None)
                except ValueError:
                    pass

        return None

    # ------------------------------------------------------------------
    # KLCC Convention Centre
    # ------------------------------------------------------------------

    def _scrape_klcc(self) -> list[dict]:
        """KLCC Convention Centre events.

        KLCC's /whats-on page is a JavaScript-rendered SPA - httpx returns
        an empty shell. Without a headless browser (Playwright) we cannot
        scrape it reliably.

        A previous version of this file shipped a hardcoded list of events
        manually copied from KLCC's site at some point. That list went
        stale (e.g. surfacing IGEM 2026 with dates that no longer match
        KLCC's actual calendar). Stale curation pretending to be fresh
        scraping is worse than no data, so the list was removed on
        2026-05-27.

        TODO: revisit with Playwright + a per-event website-cross-check
        in the medium-scope wedge. Until then, KLCC trade-show coverage
        comes only via Eventbrite when an event also lists there.
        """
        logger.info(
            "KLCC scraper: skipped. Site requires JS rendering; hardcoded "
            "list was removed on 2026-05-27 to avoid stale data."
        )
        return []

    def _parse_klcc_date(self, text: str) -> Optional[tuple]:
        """Parse KLCC date formats like 'May 12-13, 2026' or 'Jun 03-05, 2026'."""
        # Pattern: "Month DD-DD, YYYY"
        match = re.search(r"(\w+)\s+(\d{1,2})\s*-\s*(\d{1,2}),?\s*(\d{4})", text)
        if match:
            month_str, day1, day2, year = match.groups()
            month = self._month_to_num(month_str)
            if month:
                try:
                    start = datetime(int(year), month, int(day1))
                    end = datetime(int(year), month, int(day2))
                    return (start, end)
                except ValueError:
                    pass

        # Pattern: "Month DD, YYYY" (single day)
        match = re.search(r"(\w+)\s+(\d{1,2}),?\s*(\d{4})", text)
        if match:
            month_str, day, year = match.groups()
            month = self._month_to_num(month_str)
            if month:
                try:
                    start = datetime(int(year), month, int(day))
                    return (start, None)
                except ValueError:
                    pass

        # Also try "DD-DD Month YYYY" format
        match = re.search(r"(\d{1,2})\s*-\s*(\d{1,2})\s+(\w+)\s+(\d{4})", text)
        if match:
            day1, day2, month_str, year = match.groups()
            month = self._month_to_num(month_str)
            if month:
                try:
                    start = datetime(int(year), month, int(day1))
                    end = datetime(int(year), month, int(day2))
                    return (start, end)
                except ValueError:
                    pass

        return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _month_to_num(month_str: str) -> Optional[int]:
        """Convert month name/abbreviation to number."""
        months = {
            "jan": 1, "january": 1, "feb": 2, "february": 2,
            "mar": 3, "march": 3, "apr": 4, "april": 4,
            "may": 5, "jun": 6, "june": 6,
            "jul": 7, "july": 7, "aug": 8, "august": 8,
            "sep": 9, "sept": 9, "september": 9,
            "oct": 10, "october": 10, "nov": 11, "november": 11,
            "dec": 12, "december": 12,
        }
        return months.get(month_str.lower())

    @staticmethod
    def _deduplicate(events: list[dict]) -> list[dict]:
        """Remove duplicates by title."""
        seen = set()
        unique = []
        for event in events:
            key = event["title"].lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(event)
        return unique

    def _categorize(self, title: str) -> str:
        """Categorize event based on title."""
        title_lower = title.lower()
        if any(kw in title_lower for kw in ["ai", "machine learning", "ml", "llm", "artificial intelligence"]):
            return "AI"
        if any(kw in title_lower for kw in ["cyber", "security", "infosec"]):
            return "Cybersecurity"
        if any(kw in title_lower for kw in ["blockchain", "web3", "crypto", "nft"]):
            return "Blockchain"
        if any(kw in title_lower for kw in ["investment", "trading", "stock", "finance", "fintech"]):
            return "Investment"
        if any(kw in title_lower for kw in ["startup", "entrepreneur", "founder"]):
            return "Entrepreneurship"
        return "Tech"
