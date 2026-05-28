"""Eventsize scraper - listing pages only, card-text parsing.

Decision (2026-05-27): Eventsize ships malformed JSON-LD with end-before-
start dates on roughly a third of events. The visible card text is the
authoritative signal: each card on the location-filtered listing pages
contains a date+time string ("28 May, 2:00 PM"), a title, and a venue
line. We parse those directly and never trust the per-event JSON-LD.

Tradeoffs:
  + Trustworthy data, no garbage to filter out
  + 2 HTTP requests per scrape instead of 30+
  - Year is implicit (we infer current year, rolling forward if the
    parsed date is in the past)
  - No end time / multi-day events (every event is single-day)
  - No description (only title + venue + date)
"""
import logging
import re
from datetime import datetime
from typing import Optional

from .base import BaseScraper

logger = logging.getLogger(__name__)


# The two location filters Aiman cares about, plus topic searches.
# Eventsize's listing-by-location surfaces only ~38 curated events; many
# real KL events are findable only through search. We use both.
LISTING_URLS = [
    "https://eventsize.com/?location=Malaysia--Kuala-Lumpur",
    "https://eventsize.com/?location=Malaysia--Selangor",
]

# Topic-keyword searches scoped to Malaysia. Eventsize's location filter
# on search routes is buggy (Kuala-Lumpur filter drops legitimate KL
# events), so we filter only at the country level here and rely on the
# venue-text foreign filter to catch actual non-Malaysia events.
SEARCH_URLS = [
    "https://eventsize.com/?search=entrepreneur&location=Malaysia",
    "https://eventsize.com/?search=startup&location=Malaysia",
    "https://eventsize.com/?search=AI&location=Malaysia",
    "https://eventsize.com/?search=hackathon&location=Malaysia",
    "https://eventsize.com/?search=cybersecurity&location=Malaysia",
    "https://eventsize.com/?search=fintech&location=Malaysia",
    "https://eventsize.com/?search=blockchain&location=Malaysia",
    "https://eventsize.com/?search=crypto&location=Malaysia",
    "https://eventsize.com/?search=workshop&location=Malaysia",
    "https://eventsize.com/?search=training&location=Malaysia",
    "https://eventsize.com/?search=networking&location=Malaysia",
    "https://eventsize.com/?search=founder&location=Malaysia",
    "https://eventsize.com/?search=open+day&location=Malaysia",
    "https://eventsize.com/?search=bootcamp&location=Malaysia",
    "https://eventsize.com/?search=mentoring&location=Malaysia",
]

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Card date format examples seen in the wild:
#   "28 May, 2:00 PM"
#   "11 June, 2:15 PM"
#   "20 July, 9:00 AM"
DATE_RE = re.compile(
    r"^\s*(\d{1,2})\s+([A-Za-z]+)\s*,\s*(\d{1,2})(?::(\d{2}))?\s*([APap][Mm])\s*$"
)


class EventsizeScraper(BaseScraper):
    """Scrape events from Eventsize KL+Selangor location listings."""

    def __init__(self):
        # 3-second polite delay; Eventsize rate-limits aggressively.
        super().__init__("Eventsize", "https://eventsize.com", delay=3.0)

    def scrape(self) -> list[dict]:
        events = []
        # Pull from both location-only listings and topic-keyword searches.
        # Searches typically return only 0-19 cards each, so this is far
        # cheaper than crawling the whole site.
        all_urls = LISTING_URLS + SEARCH_URLS
        for url in all_urls:
            html = self._fetch_html(url)
            if not html:
                logger.warning(f"Eventsize: empty response from {url}")
                continue
            soup = self._parse_html(html)
            page_events = self._parse_listing(soup)
            events.extend(page_events)
            logger.debug(f"Eventsize {url}: parsed {len(page_events)} cards")

        # Dedupe across the URLs before enrichment (multiple search queries
        # often surface the same event).
        events = self._deduplicate(events)
        logger.info(f"Eventsize: {len(events)} unique cards before enrichment")

        # For events whose card text alone doesn't match any topic, fetch
        # the per-event page and try to enrich title/description with the
        # organiser line. Eventsize's per-event JSON-LD has reliable name/
        # description/organizer fields even when its dates are garbage -
        # we ignore the dates from the detail page.
        events = self._enrich_low_signal_events(events)

        events = self._deduplicate(events)
        logger.info(f"Eventsize total: {len(events)} unique events")
        return events

    # ------------------------------------------------------------------
    # Card parsing
    # ------------------------------------------------------------------

    def _parse_listing(self, soup) -> list[dict]:
        """Extract events from card divs on a listing page.

        Each card sits in a <div style="display:inline-block; ... width:280px;">
        and contains:
          <span>FEATURED</span>     # optional badge
          <p><strong>DATE TIME</strong></p>
          <h3><a href="event/<slug>">TITLE</a></h3>
          <p>VENUE/LOCALITY</p>
        """
        events = []
        seen_slugs = set()

        # Walk anchor tags and use them as our card anchor; for each, walk
        # up to the card container by matching the inline-block style.
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if not href.startswith("event/"):
                continue
            slug = self._normalise_slug(href)
            if not slug or slug in seen_slugs:
                continue

            card = self._find_card_container(anchor)
            if card is None:
                continue

            event = self._parse_card(card, slug)
            if event:
                seen_slugs.add(slug)
                events.append(event)

        return events

    @staticmethod
    def _normalise_slug(href: str) -> str:
        """Return the path-safe slug for an event link.

        Inputs we see on the listing pages:
          'event/1779455172516-e3-institute-open-day-2026'
          'event/python-bootcamp-june2026'
          'event/scaling-in-a-changing-world-workshop-2/p/1/'   (FEATURED)
        """
        slug = href[len("event/"):].rstrip("/")
        slug = re.sub(r"/p/\d+$", "", slug)
        if "/" in slug:
            return ""
        return slug

    @staticmethod
    def _find_card_container(anchor):
        """Walk up the DOM until we hit the card div, identified by its
        inline-block + width:280px inline style. Returns None if not found."""
        cur = anchor
        for _ in range(6):
            cur = cur.parent
            if cur is None:
                return None
            style = cur.get("style", "") if hasattr(cur, "get") else ""
            if "inline-block" in style and "width:280px" in style:
                return cur
        return None

    def _parse_card(self, card, slug: str) -> Optional[dict]:
        """Parse one card div into an event dict, or None if essential
        fields can't be extracted."""
        # Pull <h3> first - title is the most identifying field
        h3 = card.find("h3")
        if not h3:
            return None
        title = h3.get_text(" ", strip=True)
        if not title or len(title) < 3:
            return None

        # The date <p> is the FIRST <p> in the card body whose text starts
        # with a digit and matches our DATE_RE. We deliberately skip the
        # FEATURED <span> if present.
        start_dt = None
        date_text_used = ""
        for p in card.find_all("p"):
            txt = p.get_text(" ", strip=True)
            if not txt:
                continue
            parsed = self._parse_card_date(txt)
            if parsed:
                start_dt = parsed
                date_text_used = txt
                break

        if start_dt is None:
            logger.debug(f"Eventsize: skipping {slug} - no parseable date")
            return None

        # The venue/locality <p> is the FIRST <p> after the title that
        # is NOT the date. Could be the venue name or just a city.
        venue = ""
        for p in card.find_all("p"):
            txt = p.get_text(" ", strip=True)
            if txt and txt != date_text_used and not self._parse_card_date(txt):
                venue = txt
                break
        if not venue:
            venue = "Kuala Lumpur"

        # Eventsize's own location filter is loose; drop venues that are
        # obviously outside Malaysia. Check both venue line and title -
        # sometimes the city is only in the title (e.g. "Lagos International
        # Crypto Summit" with venue field "Landmark Centre").
        check_text = f"{venue} {title}"
        if self._is_obviously_foreign(check_text):
            logger.debug(f"Eventsize: skipping {slug} - foreign venue/title {check_text!r}")
            return None

        return self._create_event_dict(
            title=title,
            description="",
            start_datetime=start_dt,
            end_datetime=None,  # listing cards don't show end time
            location=venue,
            organiser="",  # listing cards don't show organiser
            source_url=f"https://eventsize.com/event/{slug}",
            categories=[self._categorize(title)],
            image_url="",
        )

    @staticmethod
    def _is_obviously_foreign(text: str) -> bool:
        """Cheap filter for events whose location or title is clearly
        outside KL/Selangor. Conservative: only catches obvious cases.
        Pass venue+title concatenated for best signal.
        """
        # Cyrillic characters never appear in Malaysian event listings
        for ch in text:
            if "\u0400" <= ch <= "\u04FF":
                return True
        lower = text.lower()
        foreign_markers = [
            # US tourist venues / state names
            "powderhorn", "sarasota", "mesa", " york", "elkhorn",
            "blue mountain event", "rocky mountain",
            "denver", "colorado", "florida", "texas", "california",
            # Canada / UK
            "ontario", "vancouver", "toronto",
            "uk", " london", "manchester",
            # Europe / Russia / Ukraine
            "kazna", "moscow", "kyiv", "kiev", "berlin", "paris",
            # Other Asian cities not in our region
            "singapore", "manila", "filipino", "philippines",
            "jakarta", "bandung", "surabaya",
            "bangkok", "phuket", "chiang mai",
            "ho chi minh", "hanoi", "saigon",
            "mumbai", "delhi", "bengaluru",
            # African cities
            "lagos", "nigeria", "abuja", "nairobi",
            # Malaysian states OUTSIDE KL/Selangor that Aiman doesn't care about
            "penang", "george town", "johor", "johor bahru", " jb ",
            "kota kinabalu", "kuching", "miri", "ipoh", "malacca",
            "melaka", "kedah", "kelantan", "terengganu", "sabah",
            "sarawak", "perlis", "perak", "pahang",
            "spice convention", "setia spice",
        ]
        return any(m in lower for m in foreign_markers)

    # ------------------------------------------------------------------
    # Date parsing: "28 May, 2:00 PM" -> naive datetime in current year
    # (rolled forward to next year if month is in the past).
    # ------------------------------------------------------------------

    @classmethod
    def _parse_card_date(cls, text: str) -> Optional[datetime]:
        m = DATE_RE.match(text)
        if not m:
            return None
        day_str, month_str, hour_str, minute_str, ampm = m.groups()

        month = MONTHS.get(month_str.lower())
        if not month:
            return None

        try:
            day = int(day_str)
            hour = int(hour_str)
            minute = int(minute_str) if minute_str else 0
        except ValueError:
            return None

        if ampm.upper() == "PM" and hour != 12:
            hour += 12
        elif ampm.upper() == "AM" and hour == 12:
            hour = 0

        # Year inference: assume the current year. If that produces a date
        # that's already 30+ days in the past, roll forward to next year.
        # This handles the December->January wrap correctly.
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

        return candidate

    # ------------------------------------------------------------------
    # Enrichment: fetch per-event JSON-LD for events whose card text
    # didn't supply enough signal for a topic match. We only want extra
    # name/description/organizer text - the dates on Eventsize's per-event
    # JSON-LD are unreliable, so we keep the listing-card date.
    # ------------------------------------------------------------------

    def _enrich_low_signal_events(self, events: list[dict]) -> list[dict]:
        """For each event whose categorisation looks weak, fetch the detail
        page and append organiser + description into the description field
        so the orchestrator's FilterEngine.categorize has more text to
        match against.
        """
        from .base import BaseScraper as _BS  # type-only
        import json as _json

        enriched = []
        for ev in events:
            title = ev.get("title", "")
            desc = ev.get("description", "") or ""
            # Cheap pre-check: if the title already contains topic-y words,
            # skip the network request.
            cheap_text = (title + " " + desc).lower()
            if any(
                kw in cheap_text
                for kw in [
                    "ai", "ml", "machine learning", "startup", "entrepreneur",
                    "founder", "sme", "cyber", "blockchain", "crypto",
                    "investment", "trading", "fintech", "hackathon",
                    "social enterprise",
                ]
            ):
                enriched.append(ev)
                continue

            slug_url = ev.get("source_url", "")
            if not slug_url or not slug_url.startswith("https://eventsize.com/event/"):
                enriched.append(ev)
                continue

            html = self._fetch_html(slug_url)
            if not html:
                enriched.append(ev)
                continue

            soup = self._parse_html(html)
            extra_text = self._extract_event_signal_text(soup)
            if extra_text:
                ev["description"] = (desc + " " + extra_text).strip()
            enriched.append(ev)

        return enriched

    @staticmethod
    def _extract_event_signal_text(soup) -> str:
        """Pull organiser name + description out of the per-event JSON-LD,
        ignoring date fields entirely (those are unreliable on Eventsize).
        """
        import json as _json

        signal_parts = []
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = _json.loads(script.string)
            except Exception:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") != "Event":
                    continue
                if item.get("description"):
                    signal_parts.append(item["description"])
                org = item.get("organizer", {})
                if isinstance(org, dict) and org.get("name"):
                    signal_parts.append(org["name"])
                elif isinstance(org, list):
                    for o in org:
                        if isinstance(o, dict) and o.get("name"):
                            signal_parts.append(o["name"])
        return " ".join(signal_parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate(events: list[dict]) -> list[dict]:
        seen = set()
        unique = []
        for event in events:
            key = (
                event.get("title", "").lower().strip(),
                str(event.get("start_datetime", "")),
            )
            if key not in seen:
                seen.add(key)
                unique.append(event)
        return unique

    def _categorize(self, title: str) -> str:
        """Coarse first-bucket categorisation. The orchestrator overwrites
        this with the YAML-driven FilterEngine.categorize() so this is just
        a placeholder."""
        title_lower = title.lower()
        if any(kw in title_lower for kw in ["ai", "machine learning", "ml", "llm", "generative"]):
            return "AI"
        if any(kw in title_lower for kw in ["cyber", "security", "infosec"]):
            return "Cybersecurity"
        if any(kw in title_lower for kw in ["blockchain", "web3", "crypto", "nft"]):
            return "Blockchain"
        if any(kw in title_lower for kw in ["investment", "trading", "stock", "finance"]):
            return "Investment"
        if any(kw in title_lower for kw in ["startup", "entrepreneur", "founder"]):
            return "Entrepreneurship"
        return "Tech"
