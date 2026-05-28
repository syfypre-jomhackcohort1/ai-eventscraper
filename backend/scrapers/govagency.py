"""Government agency website scraper for Malaysian tech/business events."""
import json
import logging
import re
from datetime import datetime
from typing import Optional

from .base import BaseScraper

logger = logging.getLogger(__name__)


# Each agency entry: (name, urls_to_try, default_categories)
AGENCIES = [
    {
        "name": "MDEC",
        "urls": [
            "https://mdec.my/news",
            "https://mdec.my/events",
            "https://mdec.my/programmes",
        ],
        "categories": ["Tech"],
    },
    {
        "name": "HRD Corp",
        "urls": [
            "https://www.hrdcorp.gov.my/news-and-articles",
            "https://www.hrdcorp.gov.my/programmes",
        ],
        "categories": ["Tech"],
    },
    {
        "name": "NACSA",
        "urls": [
            "https://www.nacsa.gov.my",
        ],
        "categories": ["Cybersecurity"],
    },
    {
        "name": "INSKEN",
        "urls": [
            "https://www.insken.gov.my",
            "https://www.insken.gov.my/program",
            "https://www.insken.gov.my/events",
        ],
        "categories": ["Entrepreneurship"],
    },
    {
        "name": "SME Corp",
        "urls": [
            "https://www.smecorp.gov.my/index.php/en/",
        ],
        "categories": ["Entrepreneurship"],
    },
    {
        "name": "MATRADE",
        "urls": [
            "https://www.matrade.gov.my",
        ],
        "categories": ["Entrepreneurship"],
    },
    {
        "name": "MPC",
        "urls": [
            "https://www.mpc.gov.my",
            "https://www.mpc.gov.my/events",
        ],
        "categories": ["Tech"],
    },
    {
        "name": "MIMOS",
        "urls": [
            "https://www.mimos.my",
            "https://www.mimos.my/events",
        ],
        "categories": ["AI"],
    },
    {
        "name": "SC Malaysia",
        "urls": [
            "https://www.sc.com.my/development/digital",
        ],
        "categories": ["Investment"],
    },
    {
        "name": "Bank Negara",
        "urls": [
            "https://www.bnm.gov.my/news-and-events",
        ],
        "categories": ["Investment"],
    },
    {
        "name": "Bursa Malaysia",
        "urls": [
            "https://www.bursamalaysia.com/market_information/news_and_announcements",
        ],
        "categories": ["Investment"],
    },
    {
        "name": "KUSKOP",
        "urls": [
            "https://www.kuskop.gov.my",
        ],
        "categories": ["Entrepreneurship"],
    },
    {
        "name": "KESUMA",
        "urls": [
            "https://www.kesuma.gov.my",
        ],
        "categories": ["Entrepreneurship"],
    },
]


class GovAgencyScraper(BaseScraper):
    """Scrape events from Malaysian government agency websites."""

    def __init__(self):
        super().__init__("GovAgency", "https://mdec.my", delay=3.0)

    def scrape(self) -> list[dict]:
        """Scrape events from all configured government agency websites."""
        all_events = []

        for agency in AGENCIES:
            agency_events = self._scrape_agency(agency)
            all_events.extend(agency_events)

        # Deduplicate
        unique = self._deduplicate(all_events)
        logger.info(f"GovAgency total: {len(unique)} unique events")
        return unique

    def _scrape_agency(self, agency: dict) -> list[dict]:
        """Scrape a single agency's pages."""
        events = []
        name = agency["name"]
        default_cats = agency["categories"]

        for url in agency["urls"]:
            try:
                html = self._fetch_html(url)
                if not html:
                    continue

                soup = self._parse_html(html)

                # Strategy 1: JSON-LD structured data
                jsonld_events = self._parse_jsonld(soup, name, default_cats)
                events.extend(jsonld_events)

                # Strategy 2: Parse event/program cards from HTML
                card_events = self._parse_cards(soup, url, name, default_cats)
                events.extend(card_events)

                # Strategy 3: Parse news/announcement items that look like events
                news_events = self._parse_news_items(soup, url, name, default_cats)
                events.extend(news_events)

                total = len(jsonld_events) + len(card_events) + len(news_events)
                if total > 0:
                    logger.info(f"{name} ({url}): found {total} events")
            except Exception as e:
                logger.debug(f"Error scraping {name} at {url}: {e}")

        return events

    def _parse_jsonld(self, soup, agency_name: str, default_cats: list) -> list[dict]:
        """Parse JSON-LD structured data."""
        events = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "Event":
                        event = self._parse_jsonld_event(item, agency_name, default_cats)
                        if event:
                            events.append(event)
                    elif item.get("@type") == "ItemList":
                        for elem in item.get("itemListElement", []):
                            inner = elem.get("item", elem)
                            if inner.get("@type") == "Event":
                                event = self._parse_jsonld_event(inner, agency_name, default_cats)
                                if event:
                                    events.append(event)
            except (json.JSONDecodeError, TypeError):
                continue
        return events

    def _parse_jsonld_event(self, item: dict, agency_name: str, default_cats: list) -> Optional[dict]:
        """Parse a single JSON-LD Event."""
        try:
            title = item.get("name", "")
            if not title:
                return None

            start_str = item.get("startDate", "")
            if not start_str:
                return None
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))

            end_str = item.get("endDate", "")
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00")) if end_str else None

            location_obj = item.get("location", {})
            location = self._extract_location(location_obj)

            organiser = agency_name
            org_obj = item.get("organizer", {})
            if isinstance(org_obj, dict) and org_obj.get("name"):
                organiser = org_obj["name"]

            cats = [self._categorize(title)]
            if cats == ["Tech"] and default_cats != ["Tech"]:
                cats = default_cats

            return self._create_event_dict(
                title=title,
                description=item.get("description", ""),
                start_datetime=start_dt,
                end_datetime=end_dt,
                location=location,
                organiser=organiser,
                source_url=item.get("url", ""),
                categories=cats,
                image_url=item.get("image", ""),
            )
        except Exception as e:
            logger.debug(f"Error parsing JSON-LD event from {agency_name}: {e}")
            return None

    def _parse_cards(self, soup, page_url: str, agency_name: str, default_cats: list) -> list[dict]:
        """Parse event/program cards from HTML."""
        events = []

        # Common selectors for event cards across government sites
        selectors = [
            ".event-card", ".event-item", ".programme-card", ".program-item",
            ".card-event", "[data-event]", ".training-item", ".workshop-item",
            ".event-listing", ".event-list-item",
        ]

        cards = []
        for sel in selectors:
            cards = soup.select(sel)
            if cards:
                break

        for card in cards:
            event = self._parse_single_card(card, page_url, agency_name, default_cats)
            if event:
                events.append(event)

        return events

    def _parse_news_items(self, soup, page_url: str, agency_name: str, default_cats: list) -> list[dict]:
        """Parse news/announcement items that contain event-like content."""
        events = []

        # Event keywords to look for in news items
        event_keywords = [
            "seminar", "workshop", "conference", "webinar", "forum",
            "summit", "hackathon", "bootcamp", "training", "programme",
            "program", "bengkel", "kursus", "latihan", "persidangan",
            "symposium", "expo", "exhibition", "meetup", "networking",
            "launch", "pelancaran", "dialog", "townhall",
        ]

        # Look for news/article items
        news_selectors = [
            ".news-item", ".article-item", ".post-item", ".announcement",
            ".news-card", ".blog-post", ".media-item", "article",
            ".list-item", ".item-row",
        ]

        items = []
        for sel in news_selectors:
            items = soup.select(sel)
            if items:
                break

        # If no structured items found, try links with event-like text
        if not items:
            for link in soup.find_all("a", href=True):
                text = link.get_text(strip=True).lower()
                if any(kw in text for kw in event_keywords) and len(text) > 10:
                    event = self._link_to_event(link, page_url, agency_name, default_cats)
                    if event:
                        events.append(event)
            return events

        for item in items:
            text = item.get_text(strip=True).lower()
            if any(kw in text for kw in event_keywords):
                event = self._parse_single_card(item, page_url, agency_name, default_cats)
                if event:
                    events.append(event)

        return events

    def _parse_single_card(self, card, page_url: str, agency_name: str, default_cats: list) -> Optional[dict]:
        """Parse a single card/item element into an event dict."""
        try:
            # Title
            title_el = card.select_one("h2, h3, h4, h5, .title, .event-title, .card-title, a")
            title = title_el.get_text(strip=True) if title_el else None
            if not title or len(title) < 5:
                return None

            # Link
            link_el = card.select_one("a[href]") or (card if card.name == "a" else None)
            url = ""
            if link_el:
                url = link_el.get("href", "")
                if url and not url.startswith("http"):
                    # Resolve relative URL
                    from urllib.parse import urljoin
                    url = urljoin(page_url, url)

            # Date — skip items without a real date
            start_dt = self._extract_date(card)
            if start_dt is None:
                return None

            # Location
            loc_el = card.select_one(".location, .venue, .event-location")
            location = loc_el.get_text(strip=True) if loc_el else "Kuala Lumpur"

            # Categories
            cats = [self._categorize(title)]
            if cats == ["Tech"] and default_cats != ["Tech"]:
                cats = default_cats

            return self._create_event_dict(
                title=title,
                start_datetime=start_dt,
                location=location,
                organiser=agency_name,
                source_url=url,
                categories=cats,
            )
        except Exception as e:
            logger.debug(f"Error parsing card from {agency_name}: {e}")
            return None

    def _link_to_event(self, link, page_url: str, agency_name: str, default_cats: list) -> Optional[dict]:
        """Convert a link element to an event dict."""
        try:
            title = link.get_text(strip=True)
            if not title or len(title) < 10:
                return None

            url = link.get("href", "")
            if url and not url.startswith("http"):
                from urllib.parse import urljoin
                url = urljoin(page_url, url)

            # Try to extract a date from the link text or surrounding context
            parent = link.parent
            context_text = parent.get_text(strip=True) if parent else title
            start_dt = self._parse_date_text(context_text)
            if start_dt is None:
                return None  # Skip items without a real date

            cats = [self._categorize(title)]
            if cats == ["Tech"] and default_cats != ["Tech"]:
                cats = default_cats

            return self._create_event_dict(
                title=title,
                start_datetime=start_dt,
                location="Malaysia",
                organiser=agency_name,
                source_url=url,
                categories=cats,
            )
        except Exception:
            return None

    def _extract_date(self, element) -> datetime:
        """Try to extract a date from an element."""
        # Try time/datetime elements
        time_el = element.select_one("time[datetime], [datetime]")
        if time_el:
            dt_str = time_el.get("datetime", "")
            if dt_str:
                try:
                    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

        # Try date-like text patterns
        date_el = element.select_one(".date, .event-date, .post-date, .meta-date")
        if date_el:
            text = date_el.get_text(strip=True)
            parsed = self._parse_date_text(text)
            if parsed:
                return parsed

        # Try finding date patterns in the full text
        full_text = element.get_text(strip=True)
        parsed = self._parse_date_text(full_text)
        if parsed:
            return parsed

        return None

    @staticmethod
    def _parse_date_text(text: str) -> Optional[datetime]:
        """Try to parse a date from free-form text."""
        # Common date patterns
        patterns = [
            # 2026-05-15
            (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
            # 15/05/2026 or 15-05-2026
            (r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})", None),
            # May 15, 2026
            (r"(\w+ \d{1,2},?\s*\d{4})", None),
            # 15 May 2026
            (r"(\d{1,2}\s+\w+\s+\d{4})", None),
        ]

        for pattern, fmt in patterns:
            match = re.search(pattern, text)
            if match:
                date_str = match.group(1)
                if fmt:
                    try:
                        return datetime.strptime(date_str, fmt)
                    except ValueError:
                        continue
                else:
                    # Try common formats
                    for f in [
                        "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y",
                        "%B %d, %Y", "%B %d %Y",
                        "%d %B %Y", "%d %b %Y",
                    ]:
                        try:
                            return datetime.strptime(date_str.replace(",", ""), f)
                        except ValueError:
                            continue
        return None

    @staticmethod
    def _extract_location(location_obj) -> str:
        """Extract location string from JSON-LD location object."""
        if isinstance(location_obj, dict):
            name = location_obj.get("name", "")
            address = location_obj.get("address", {})
            if isinstance(address, dict):
                locality = address.get("addressLocality", "")
                return f"{name}, {locality}".strip(", ") if name else locality
            elif isinstance(address, str):
                return f"{name}, {address}".strip(", ") if name else address
            return name or "Kuala Lumpur"
        elif isinstance(location_obj, str):
            return location_obj
        return "Kuala Lumpur"

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
        """Categorize event based on title keywords."""
        title_lower = title.lower()
        if any(kw in title_lower for kw in ["ai", "machine learning", "ml", "llm", "generative", "kecerdasan buatan"]):
            return "AI"
        if any(kw in title_lower for kw in ["cyber", "security", "infosec", "keselamatan siber"]):
            return "Cybersecurity"
        if any(kw in title_lower for kw in ["blockchain", "web3", "crypto", "nft"]):
            return "Blockchain"
        if any(kw in title_lower for kw in ["investment", "trading", "stock", "finance", "pelaburan", "kewangan"]):
            return "Investment"
        if any(kw in title_lower for kw in ["startup", "entrepreneur", "founder", "usahawan", "keusahawanan", "sme", "pks"]):
            return "Entrepreneurship"
        return "Tech"
