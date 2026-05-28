"""Base scraper class with retry logic and polite delays."""
import time
import logging
from abc import ABC, abstractmethod
from typing import Optional
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for all event scrapers."""

    def __init__(self, name: str, base_url: str, delay: float = 2.0):
        self.name = name
        self.base_url = base_url
        self.delay = delay
        self.last_request_time = 0.0

    def _wait_for_polite_delay(self):
        """Ensure minimum delay between requests."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self.last_request_time = time.time()

    def _fetch_html(self, url: str, headers: Optional[dict] = None) -> Optional[str]:
        """Fetch HTML with retry logic."""
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        if headers:
            default_headers.update(headers)

        for attempt in range(3):
            try:
                self._wait_for_polite_delay()
                response = httpx.get(url, headers=default_headers, timeout=30.0, follow_redirects=True)
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt == 2:
                    return None
                time.sleep(2 ** attempt)
        return None

    def _parse_html(self, html: str) -> BeautifulSoup:
        """Parse HTML string with BeautifulSoup."""
        return BeautifulSoup(html, "html.parser")

    @abstractmethod
    def scrape(self) -> list[dict]:
        """Scrape events and return list of event dicts."""
        pass

    def _create_event_dict(
        self,
        title: str,
        start_datetime,
        location: str = None,
        description: str = None,
        end_datetime=None,
        organiser: str = None,
        source_url: str = None,
        categories: list = None,
        image_url: str = None,
    ) -> dict:
        """Helper to create standardized event dict."""
        return {
            "title": title,
            "description": description,
            "start_datetime": start_datetime,
            "end_datetime": end_datetime,
            "location": location,
            "is_virtual": any(kw in (location or "").lower() for kw in ["online", "virtual", "webinar", "zoom", "teams"]),
            "organiser": organiser,
            "source_platform": self.name.lower(),
            "source_url": source_url,
            "categories": categories or [],
            "image_url": image_url,
        }