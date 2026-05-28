"""Luma scraper using HTML parsing and API calls (no Playwright)."""
import json
import logging
from datetime import datetime
from typing import Optional

import httpx

from .base import BaseScraper

logger = logging.getLogger(__name__)


class LumaScraper(BaseScraper):
    """Scrape events from Luma using HTML + API (no browser required)."""

    # Location-specific discover URLs to try
    DISCOVER_URLS = [
        "https://lu.ma/discover",
        "https://lu.ma/discover/kuala-lumpur",
        "https://lu.ma/discover/kl",
        "https://luma.com/discover",
        "https://luma.com/discover/kuala-lumpur",
    ]

    # Luma internal API endpoints to try
    API_ENDPOINTS = [
        {
            "url": "https://api.lu.ma/discover/get-paginated-events",
            "params": {"discover_place_api_id": "kuala-lumpur"},
        },
        {
            "url": "https://api.lu.ma/discover/get-paginated-events",
            "params": {"discover_place_api_id": "malaysia"},
        },
        {
            "url": "https://api.lu.ma/discover/get-paginated-events",
            "params": {"geo_latitude": "3.1390", "geo_longitude": "101.6869"},
        },
    ]

    def __init__(self):
        super().__init__("Luma", "https://lu.ma/discover", delay=2.0)

    def scrape(self) -> list[dict]:
        """Fetch events from Luma via HTML scraping and API calls."""
        events = []

        # Strategy 1: Parse HTML pages for JSON-LD and embedded data
        for url in self.DISCOVER_URLS:
            try:
                html = self._fetch_html(url)
                if not html:
                    continue

                soup = self._parse_html(html)
                parsed = self._parse_jsonld_events(soup)
                events.extend(parsed)

                # Also try extracting from Next.js / embedded JSON payloads
                embedded = self._parse_embedded_data(soup)
                events.extend(embedded)

                if parsed or embedded:
                    logger.info(
                        f"Luma HTML '{url}': found {len(parsed)} JSON-LD + "
                        f"{len(embedded)} embedded events"
                    )
            except Exception as e:
                logger.error(f"Error scraping Luma HTML at {url}: {e}")

        # Strategy 2: Try the Luma internal API directly
        api_events = self._fetch_from_api()
        events.extend(api_events)

        # Deduplicate by title + start_datetime
        events = self._deduplicate(events)
        logger.info(f"Luma total: {len(events)} unique events")
        return events

    # ------------------------------------------------------------------
    # HTML parsing helpers
    # ------------------------------------------------------------------

    def _parse_jsonld_events(self, soup) -> list[dict]:
        """Parse JSON-LD structured data (application/ld+json) from the page."""
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
        """Convert a single JSON-LD Event object into our event dict."""
        try:
            title = item.get("name", "")
            if not title:
                return None

            start_str = item.get("startDate", "")
            if not start_str:
                return None
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))

            end_str = item.get("endDate", "")
            end_dt = (
                datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                if end_str
                else None
            )

            location = self._extract_location(item.get("location", {}))
            organiser = ""
            org_obj = item.get("organizer", {})
            if isinstance(org_obj, dict):
                organiser = org_obj.get("name", "")

            image = item.get("image", "")
            if isinstance(image, list) and image:
                image = image[0]

            return self._create_event_dict(
                title=title,
                description=item.get("description", ""),
                start_datetime=start_dt,
                end_datetime=end_dt,
                location=location,
                organiser=organiser,
                source_url=item.get("url", ""),
                categories=[self._categorize(title)],
                image_url=image if isinstance(image, str) else "",
            )
        except Exception as e:
            logger.debug(f"Error parsing Luma JSON-LD event: {e}")
            return None

    def _parse_embedded_data(self, soup) -> list[dict]:
        """Try to extract events from embedded JS payloads (__NEXT_DATA__, etc.)."""
        events = []

        # Next.js payload
        script = soup.find("script", id="__NEXT_DATA__")
        if script and script.string:
            try:
                data = json.loads(script.string)
                events.extend(self._walk_next_data(data))
            except (json.JSONDecodeError, TypeError):
                pass

        # Also look for inline JSON blobs that contain event arrays
        for script in soup.find_all("script"):
            if not script.string:
                continue
            text = script.string
            # Luma sometimes embeds event data in window.__INITIAL_STATE__ or similar
            for marker in ["__INITIAL_STATE__", "__APOLLO_STATE__", "window.__DATA__"]:
                if marker in text:
                    try:
                        # Extract JSON after the marker
                        start = text.index(marker) + len(marker)
                        # Skip '=' and whitespace
                        while start < len(text) and text[start] in " =":
                            start += 1
                        # Find the JSON object/array
                        depth = 0
                        end = start
                        opener = text[start] if start < len(text) else ""
                        if opener in "{[":
                            closer = "}" if opener == "{" else "]"
                            for i in range(start, len(text)):
                                if text[i] == opener:
                                    depth += 1
                                elif text[i] == closer:
                                    depth -= 1
                                    if depth == 0:
                                        end = i + 1
                                        break
                            blob = json.loads(text[start:end])
                            events.extend(self._extract_events_from_blob(blob))
                    except (json.JSONDecodeError, ValueError, IndexError):
                        continue

        return events

    def _walk_next_data(self, data: dict) -> list[dict]:
        """Walk a Next.js __NEXT_DATA__ payload looking for event objects."""
        events = []
        try:
            props = data.get("props", {}).get("pageProps", {})
            # Try common keys
            for key in ["events", "initialEvents", "featuredEvents", "data"]:
                items = props.get(key, [])
                if isinstance(items, list):
                    for item in items:
                        event = self._parse_api_event(item)
                        if event:
                            events.append(event)
                elif isinstance(items, dict):
                    # Could be a paginated wrapper
                    inner = items.get("entries", items.get("data", items.get("nodes", [])))
                    if isinstance(inner, list):
                        for item in inner:
                            event = self._parse_api_event(item)
                            if event:
                                events.append(event)
        except Exception as e:
            logger.debug(f"Error walking __NEXT_DATA__: {e}")
        return events

    def _extract_events_from_blob(self, blob) -> list[dict]:
        """Recursively look for event-like objects in an arbitrary JSON blob."""
        events = []
        if isinstance(blob, dict):
            # Check if this dict looks like an event
            if "name" in blob and ("start_at" in blob or "startDate" in blob):
                event = self._parse_api_event(blob)
                if event:
                    events.append(event)
            else:
                for value in blob.values():
                    events.extend(self._extract_events_from_blob(value))
        elif isinstance(blob, list):
            for item in blob:
                events.extend(self._extract_events_from_blob(item))
        return events

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def _fetch_from_api(self) -> list[dict]:
        """Try fetching events from Luma's internal API."""
        events = []
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://lu.ma/discover",
            "Origin": "https://lu.ma",
        }

        for endpoint in self.API_ENDPOINTS:
            try:
                response = httpx.get(
                    endpoint["url"],
                    params=endpoint["params"],
                    headers=headers,
                    timeout=30.0,
                    follow_redirects=True,
                )
                if response.status_code != 200:
                    logger.debug(
                        f"Luma API {endpoint['url']} returned {response.status_code}"
                    )
                    continue

                data = response.json()
                api_events = self._parse_api_response(data)
                events.extend(api_events)
                logger.info(
                    f"Luma API ({endpoint['params']}): found {len(api_events)} events"
                )
            except Exception as e:
                logger.debug(f"Error fetching Luma API {endpoint['url']}: {e}")

        return events

    def _parse_api_response(self, data: dict) -> list[dict]:
        """Parse the Luma API response into event dicts."""
        events = []

        # The API may return events under various keys
        entries = []
        if isinstance(data, list):
            entries = data
        elif isinstance(data, dict):
            for key in ["entries", "events", "data", "results"]:
                candidate = data.get(key, [])
                if isinstance(candidate, list) and candidate:
                    entries = candidate
                    break
            # Paginated wrapper: entries might have nested event objects
            if not entries and "has_more" in data:
                entries = data.get("entries", [])

        for entry in entries:
            # Luma API entries often wrap the event: {"event": {...}, "calendar": {...}}
            event_data = entry.get("event", entry) if isinstance(entry, dict) else entry
            event = self._parse_api_event(event_data)
            if event:
                events.append(event)

        return events

    def _parse_api_event(self, item: dict) -> Optional[dict]:
        """Parse a single event from the Luma API response."""
        if not isinstance(item, dict):
            return None

        try:
            title = item.get("name", item.get("title", ""))
            if not title:
                return None

            # Luma uses various date field names
            start_str = item.get("start_at", item.get("startDate", item.get("start", "")))
            if not start_str:
                return None
            start_dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))

            end_str = item.get("end_at", item.get("endDate", item.get("end", "")))
            end_dt = (
                datetime.fromisoformat(str(end_str).replace("Z", "+00:00"))
                if end_str
                else None
            )

            # Location
            location = (
                item.get("geo_address_info", {}).get("full_address")
                or item.get("location", "")
                or item.get("geo_address_json", {}).get("description", "")
                or "Kuala Lumpur"
            )
            if isinstance(location, dict):
                location = location.get("name", location.get("description", "Kuala Lumpur"))

            # Organiser
            organiser = ""
            host = item.get("hosts", item.get("host", None))
            if isinstance(host, list) and host:
                organiser = host[0].get("name", "") if isinstance(host[0], dict) else str(host[0])
            elif isinstance(host, dict):
                organiser = host.get("name", "")

            # Source URL
            api_id = item.get("api_id", item.get("url", item.get("slug", "")))
            source_url = item.get("url", "")
            if source_url and not source_url.startswith("http"):
                source_url = f"https://lu.ma/{source_url}"
            elif not source_url and api_id:
                source_url = f"https://lu.ma/{api_id}"

            # Image
            image_url = item.get("cover_url", item.get("image_url", item.get("image", "")))

            return self._create_event_dict(
                title=title,
                description=item.get("description", item.get("description_short", "")),
                start_datetime=start_dt,
                end_datetime=end_dt,
                location=str(location),
                organiser=organiser,
                source_url=source_url,
                categories=[self._categorize(title)],
                image_url=image_url or "",
            )
        except Exception as e:
            logger.debug(f"Error parsing Luma API event: {e}")
            return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_location(location_obj) -> str:
        """Extract a human-readable location string from a JSON-LD location."""
        if isinstance(location_obj, dict):
            loc_name = location_obj.get("name", "")
            address = location_obj.get("address", {})
            if isinstance(address, dict):
                locality = address.get("addressLocality", "")
                return f"{loc_name}, {locality}".strip(", ") if loc_name else locality
            elif isinstance(address, str):
                return f"{loc_name}, {address}".strip(", ") if loc_name else address
            return loc_name or "Kuala Lumpur"
        elif isinstance(location_obj, str):
            return location_obj
        return "Kuala Lumpur"

    @staticmethod
    def _deduplicate(events: list[dict]) -> list[dict]:
        """Remove duplicate events based on title + start_datetime."""
        seen = set()
        unique = []
        for event in events:
            key = (event["title"], str(event.get("start_datetime", "")))
            if key not in seen:
                seen.add(key)
                unique.append(event)
        return unique

    def _categorize(self, title: str) -> str:
        """Categorize event based on title keywords."""
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
