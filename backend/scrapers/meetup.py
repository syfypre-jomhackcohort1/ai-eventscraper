"""Meetup scraper using public search page HTML scraping."""
import json
import logging
from datetime import datetime
from typing import Optional
import httpx

from .base import BaseScraper

logger = logging.getLogger(__name__)


class MeetupScraper(BaseScraper):
    """Scrape events from Meetup public search pages."""

    def __init__(self):
        super().__init__(
            "Meetup",
            "https://www.meetup.com/find/",
        )

    def scrape(self) -> list[dict]:
        """Fetch events from Meetup public search pages."""
        events = []
        keywords = ["tech", "AI", "cybersecurity", "blockchain", "startup", "investment"]

        for keyword in keywords:
            try:
                url = f"{self.base_url}?keywords={keyword}&location=my--kualaLumpur&source=EVENTS"
                html = self._fetch_html(url)
                if not html:
                    continue

                soup = self._parse_html(html)

                # Try JSON-LD structured data first
                parsed = self._parse_from_structured_data(soup)
                events.extend(parsed)

                # Try parsing Next.js __NEXT_DATA__ payload
                if not parsed:
                    next_events = self._parse_next_data(soup, keyword)
                    events.extend(next_events)

                logger.info(f"Meetup '{keyword}': found {len(parsed)} events")
            except Exception as e:
                logger.error(f"Error scraping Meetup for '{keyword}': {e}")

        return events

    def _parse_from_structured_data(self, soup) -> list[dict]:
        """Parse JSON-LD structured data from the page."""
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

    def _parse_next_data(self, soup, keyword: str) -> list[dict]:
        """Try to parse Meetup's __NEXT_DATA__ JSON payload."""
        events = []
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            return events

        try:
            data = json.loads(script.string)
            # Navigate the Next.js data structure to find events
            props = data.get("props", {}).get("pageProps", {})
            results = props.get("searchResults", props.get("results", []))

            if isinstance(results, dict):
                results = results.get("edges", results.get("nodes", []))

            for item in results:
                node = item.get("node", item) if isinstance(item, dict) else item
                if not isinstance(node, dict):
                    continue

                title = node.get("title", node.get("name", ""))
                if not title:
                    continue

                date_str = node.get("dateTime", node.get("startDate", ""))
                try:
                    start_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00")) if date_str else datetime.now()
                except ValueError:
                    start_dt = datetime.now()

                venue = node.get("venue", {}) or {}
                location = venue.get("name", "Kuala Lumpur") if isinstance(venue, dict) else "Kuala Lumpur"

                group = node.get("group", {}) or {}
                organiser = group.get("name", "") if isinstance(group, dict) else ""

                event_url = node.get("eventUrl", node.get("link", ""))

                event = self._create_event_dict(
                    title=title,
                    start_datetime=start_dt,
                    location=location,
                    organiser=organiser,
                    source_url=event_url,
                    categories=[self._categorize(title)],
                )
                events.append(event)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.debug(f"Error parsing __NEXT_DATA__: {e}")

        return events

    def _categorize(self, title: str) -> str:
        """Categorize event based on title."""
        title_lower = title.lower()
        if any(kw in title_lower for kw in ["ai", "machine learning", "ml", "llm"]):
            return "AI"
        if any(kw in title_lower for kw in ["cyber", "security", "infosec"]):
            return "Cybersecurity"
        if any(kw in title_lower for kw in ["blockchain", "web3", "crypto"]):
            return "Blockchain"
        if any(kw in title_lower for kw in ["investment", "trading", "stock"]):
            return "Investment"
        if any(kw in title_lower for kw in ["startup", "entrepreneur"]):
            return "Entrepreneurship"
        return "Tech"
