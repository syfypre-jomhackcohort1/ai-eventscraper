"""KUSKOP (Kementerian Pembangunan Usahawan dan Koperasi) website scraper.

KUSKOP's homepage embeds an event carousel at .owl-carousel-kalendar.
Each .item in that carousel has a title, a date in DD-Mmm-YYYY format,
a time, and a location. The site also has separate "kalendar" entries
elsewhere.

This is a low-yield source (typically 2-3 events live at a time) but
it's the agency's authoritative event channel - they post every event
here that they want public attention on.
"""
import logging
import re
from datetime import datetime
from typing import Optional

from ..base import BaseScraper
from ._geo import is_out_of_region

logger = logging.getLogger(__name__)


URL = "https://www.kuskop.gov.my/"

# DD-Mmm-YYYY where Mmm can be Malay or English abbreviation OR full name
MONTHS = {
    "jan": 1, "january": 1, "januari": 1,
    "feb": 2, "february": 2, "februari": 2,
    "mac": 3, "march": 3, "mar": 3,
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

# Match either "27-Apr-2026" or "27 April 2026" or "27 Apr 2026"
DATE_RE = re.compile(
    r"(\d{1,2})[-\s]+([A-Za-z]+)[-\s]+(\d{4})"
)


class KuskopScraper(BaseScraper):
    """Scrape KUSKOP's event calendar widget."""

    def __init__(self):
        super().__init__("Kuskop", URL, delay=2.0)

    def scrape(self) -> list[dict]:
        html = self._fetch_html(URL)
        if not html:
            logger.warning("KUSKOP: empty response")
            return []

        soup = self._parse_html(html)
        events = []

        # Carousel cards: .owl-carousel-kalendar > .item
        carousel = soup.select_one(".owl-carousel-kalendar")
        if carousel:
            for item in carousel.select(".item"):
                event = self._parse_carousel_item(item)
                if event:
                    events.append(event)

        # Deduplicate (carousels sometimes repeat for autoplay)
        events = self._deduplicate(events)
        logger.info(f"KUSKOP: parsed {len(events)} events")
        return events

    def _parse_carousel_item(self, item) -> Optional[dict]:
        text = item.get_text("\n", strip=True)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            return None

        # Find a date line
        start_dt = None
        for line in lines:
            parsed = self._parse_date(line)
            if parsed:
                start_dt = parsed
                break
        if not start_dt:
            return None

        # The first line that doesn't look like a date/time is the title.
        # Times use "pagi", "petang", "AM", "PM"
        title = ""
        for line in lines:
            if self._parse_date(line):
                continue
            if any(t in line.lower() for t in ["pagi", "petang", "malam", " am", " pm", "AM", "PM"]) and len(line) < 30:
                continue
            title = line
            break
        if not title or len(title) < 5:
            return None

        # Location: first line with one of the venue markers
        location = "Malaysia"
        for line in lines:
            if any(kw in line.lower() for kw in [
                "dewan", "hab", "menara", "kompleks", "pusat",
                "kuala lumpur", "selangor", "putrajaya", "cyberjaya",
                "shah alam", "petaling", "subang", "klang",
                "penang", "pulau pinang", "johor", "perak", "kedah",
                "kelantan", "terengganu", "pahang", "sabah", "sarawak",
                "melaka", "negeri sembilan", "perlis",
            ]):
                location = line
                break

        # Drop events outside KL/Selangor. KUSKOP runs nationwide events;
        # Aiman's stated scope is KL/Selangor/online only.
        if is_out_of_region(location + " " + title):
            logger.debug(f"KUSKOP: skipping {title[:50]!r} - out of region")
            return None

        return self._create_event_dict(
            title=title,
            description=text[:500],
            start_datetime=start_dt,
            end_datetime=None,
            location=location,
            organiser="KUSKOP",
            source_url=URL,
            categories=[],  # orchestrator re-categorises via filters.yaml
            image_url="",
        )

    @staticmethod
    def _parse_date(text: str) -> Optional[datetime]:
        m = DATE_RE.search(text)
        if not m:
            return None
        day, month_str, year = m.groups()
        month = MONTHS.get(month_str.lower())
        if not month:
            return None
        try:
            return datetime(int(year), month, int(day))
        except ValueError:
            return None

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
