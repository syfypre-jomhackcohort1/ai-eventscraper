"""INSKEN registration page scraper.

INSKEN's FB wall posts often link to https://www.insken.gov.my/pendaftaran/
which is a server-rendered page with structured event cards. We scrape
the page directly - cheaper, more accurate, and not subject to FB's JS
rendering wall.

Page structure (as of 2026-05-27):
  <div class="artikel-grid">
    <div class="grid-33">
      <div class="al_date">3 - 5 Jun 2026</div>
      <h-tag>INSKEN BANGKIT : Fashion & Accessories- Espira Kinrara, Puchong</h-tag>
      ... description / fee ...
    </div>
    ... 9 cards total ...
  </div>
"""
import logging
import re
from datetime import datetime
from typing import Optional

from ..base import BaseScraper
from ._geo import is_out_of_region

logger = logging.getLogger(__name__)


URL = "https://www.insken.gov.my/pendaftaran/"

# Malay + English month abbreviations.
MONTHS = {
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

DATE_RE = re.compile(
    r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})"
)


class InskenScraper(BaseScraper):
    """Scrape INSKEN's structured pendaftaran (registration) page."""

    def __init__(self):
        super().__init__("Insken", URL, delay=2.0)

    def scrape(self) -> list[dict]:
        html = self._fetch_html(URL)
        if not html:
            logger.warning("INSKEN: empty response")
            return []

        soup = self._parse_html(html)
        cards = soup.select(".artikel-grid > .grid-33")
        events = []
        for card in cards:
            event = self._parse_card(card)
            if event:
                events.append(event)
        logger.info(f"INSKEN: parsed {len(events)} events from {len(cards)} cards")
        return events

    def _parse_card(self, card) -> Optional[dict]:
        date_el = card.select_one(".al_date")
        if not date_el:
            return None
        date_text = date_el.get_text(" ", strip=True)
        date_pair = self._parse_date_range(date_text)
        if not date_pair:
            return None
        start_dt, end_dt = date_pair

        # Title lives in .home_pro_title (the .grid-33 layout has it twice -
        # in front and back face. Either copy works, take the first.)
        title_el = card.select_one(".home_pro_title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        if not title or len(title) < 5:
            return None

        # Registration link is in a.button-insken (the SELANJUTNYA button).
        # Falls back to the page URL if missing.
        link = card.select_one("a.button-insken[href]")
        source_url = link["href"] if link and link.get("href", "").startswith("http") else URL

        # Tag (e.g. "BANGKIT", "JAGUH") - useful as a category hint.
        tag_el = card.select_one(".home-tag span")
        program_tag = tag_el.get_text(" ", strip=True) if tag_el else ""

        # Price (e.g. "RM500")
        price_el = card.select_one(".home-price")
        price = price_el.get_text(" ", strip=True) if price_el else ""

        # Location: the title format is usually "<Program Name>- <Venue/City>".
        # Default to "Malaysia"; refine if we can detect a known KL/Selangor token.
        location = "Malaysia"
        for split_token in ["–", "-"]:
            if split_token in title:
                tail = title.split(split_token)[-1].strip()
                if tail and any(kw in tail.lower() for kw in [
                    "kuala lumpur", "selangor", "puchong", "putrajaya",
                    "klang", "petaling", "subang", "shah alam", "lembah",
                    "cyberjaya", "bangi", "kajang", "pahang", "sarawak",
                    "sabah", "perak", "kedah", "kelantan", "johor",
                    "terengganu", "melaka", "penang", "perlis", "negeri",
                ]):
                    location = tail
                break

        # Drop events outside KL/Selangor. Aiman's stated scope is
        # KL/Selangor/online; INSKEN runs many programs in other states
        # (Sarawak, Pahang, Penang etc.) which we shouldn't surface.
        # Check both extracted location AND title text in case the
        # location couldn't be split off cleanly.
        if is_out_of_region(location + " " + title):
            logger.debug(f"INSKEN: skipping {title[:50]!r} - out of region")
            return None

        # Build a description that gives FilterEngine.categorize more
        # signal than the title alone.
        description_bits = [title]
        if program_tag:
            description_bits.append(f"Program: {program_tag}")
        if price:
            description_bits.append(f"Fee: {price}")
        description = " | ".join(description_bits)

        return self._create_event_dict(
            title=title,
            description=description,
            start_datetime=start_dt,
            end_datetime=end_dt,
            location=location,
            organiser="INSKEN",
            source_url=source_url,
            categories=[],
            image_url="",
        )

    @staticmethod
    def _parse_date_range(text: str) -> Optional[tuple]:
        """Parse '3 - 5 Jun 2026' style ranges into (start, end) datetimes."""
        m = DATE_RE.search(text)
        if not m:
            return None
        d1, d2, month_str, year = m.groups()
        month = MONTHS.get(month_str.lower())
        if not month:
            return None
        try:
            start = datetime(int(year), month, int(d1))
            end = datetime(int(year), month, int(d2))
            if end < start:
                return None
            return (start, end)
        except ValueError:
            return None
