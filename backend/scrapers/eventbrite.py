"""Eventbrite scraper using public search page HTML scraping."""
import logging
from datetime import datetime
from typing import Optional
import httpx

from .base import BaseScraper

logger = logging.getLogger(__name__)


class EventbriteScraper(BaseScraper):
    """Scrape events from Eventbrite public search pages."""

    def __init__(self):
        super().__init__(
            "Eventbrite",
            "https://www.eventbrite.com/d/malaysia--kuala-lumpur/",
        )

    def scrape(self) -> list[dict]:
        """Fetch events from Eventbrite public search pages."""
        events = []
        keywords = ["tech", "ai", "cybersecurity", "blockchain", "startup", "investment"]

        for keyword in keywords:
            try:
                url = f"{self.base_url}{keyword}/"
                html = self._fetch_html(url)
                if not html:
                    continue

                soup = self._parse_html(html)
                # Eventbrite renders event cards with structured data in script tags
                parsed = self._parse_from_structured_data(soup, keyword)
                events.extend(parsed)

                # Also try parsing visible event cards
                if not parsed:
                    card_events = self._parse_event_cards(soup, keyword)
                    events.extend(card_events)

                logger.info(f"Eventbrite '{keyword}': found {len(parsed)} events")
            except Exception as e:
                logger.error(f"Error scraping Eventbrite for '{keyword}': {e}")

        return events

    def _parse_from_structured_data(self, soup, keyword: str) -> list[dict]:
        """Parse JSON-LD structured data from the page."""
        import json
        events = []

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "Event":
                        event = self._parse_jsonld_event(item)
                        if event:
                            events.append(event)
                    elif item.get("@type") == "ItemList":
                        for elem in item.get("itemListElement", []):
                            inner = elem.get("item", elem)
                            if inner.get("@type") == "Event":
                                event = self._parse_jsonld_event(inner)
                                if event:
                                    events.append(event)
            except (json.JSONDecodeError, TypeError):
                continue

        return events

    def _parse_jsonld_event(self, item: dict) -> Optional[dict]:
        """Parse a single JSON-LD Event object."""
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
            if isinstance(location_obj, dict):
                loc_name = location_obj.get("name", "")
                address = location_obj.get("address", {})
                if isinstance(address, dict):
                    locality = address.get("addressLocality", "")
                    location = f"{loc_name}, {locality}".strip(", ") if loc_name else locality
                elif isinstance(address, str):
                    location = f"{loc_name}, {address}".strip(", ") if loc_name else address
                else:
                    location = loc_name or "Kuala Lumpur"
            else:
                location = str(location_obj) if location_obj else "Kuala Lumpur"

            organiser = ""
            org_obj = item.get("organizer", {})
            if isinstance(org_obj, dict):
                organiser = org_obj.get("name", "")

            return self._create_event_dict(
                title=title,
                description=item.get("description", ""),
                start_datetime=start_dt,
                end_datetime=end_dt,
                location=location,
                organiser=organiser,
                source_url=item.get("url", ""),
                categories=[self._categorize(title)],
                image_url=item.get("image", ""),
            )
        except Exception as e:
            logger.debug(f"Error parsing JSON-LD event: {e}")
            return None

    def _parse_event_cards(self, soup, keyword: str) -> list[dict]:
        """Fallback: parse event cards from HTML structure."""
        events = []
        # Look for common Eventbrite card patterns
        cards = soup.select("[data-testid='event-card'], .search-event-card-wrapper, .eds-event-card")
        for card in cards:
            try:
                title_el = card.select_one("h2, h3, .event-card__title, [data-testid='event-card-title']")
                link_el = card.select_one("a[href*='/e/']")
                date_el = card.select_one("p, .event-card__date, [data-testid='event-card-date']")

                title = title_el.get_text(strip=True) if title_el else None
                if not title:
                    continue

                url = link_el.get("href", "") if link_el else ""
                if url and not url.startswith("http"):
                    url = f"https://www.eventbrite.com{url}"

                # Use current date as fallback since HTML date parsing is fragile
                event = self._create_event_dict(
                    title=title,
                    start_datetime=datetime.now(),
                    location="Kuala Lumpur",
                    source_url=url,
                    categories=[self._categorize(title)],
                )
                events.append(event)
            except Exception as e:
                logger.debug(f"Error parsing event card: {e}")

        return events

    def _categorize(self, title: str) -> str:
        """Categorize event based on title."""
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
