"""MCMC events scraper."""
import logging
from datetime import datetime
from .base import BaseScraper

logger = logging.getLogger(__name__)


class MCMCScraper(BaseScraper):
    """Scrape events from MCMC website."""

    def __init__(self):
        super().__init__("MCMC", "https://www.mcmc.gov.my/en/events", delay=2.0)

    def scrape(self) -> list[dict]:
        """Scrape MCMC events page."""
        html = self._fetch_html(self.base_url)
        if not html:
            return []

        soup = self._parse_html(html)
        events = []

        # Generic selector - may need adjustment based on actual page structure
        for item in soup.select(".event-item, .news-item, .list-item"):
            try:
                title_elem = item.select_one("h3, h4, .title, a")
                date_elem = item.select_one(".date, .event-date, time")
                link_elem = item.select_one("a")

                if title_elem:
                    events.append(self._create_event_dict(
                        title=title_elem.get_text(strip=True),
                        start_datetime=datetime.now(),  # Would need proper date parsing
                        location="Malaysia",
                        source_url=link_elem.get("href") if link_elem else None,
                        categories=["Tech"],
                    ))
            except Exception as e:
                logger.debug(f"Error parsing MCMC event: {e}")

        return events