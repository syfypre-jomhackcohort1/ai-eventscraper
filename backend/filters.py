"""Filter engine for events."""
import re
from pathlib import Path
from typing import Optional
import yaml


class FilterEngine:
    """Filter events by topic keywords and location."""

    def __init__(self, config_path: str = "config/filters.yaml"):
        self.config_path = Path(config_path)
        self.topics = {}
        self.locations = []
        self.virtual_keywords = []
        self._load_config()

    def _load_config(self):
        """Load filter configuration from YAML."""
        if self.config_path.exists():
            with open(self.config_path) as f:
                config = yaml.safe_load(f)
                self.topics = config.get("topics", {})
                self.locations = config.get("locations", {}).get("include", [])
                self.virtual_keywords = config.get("locations", {}).get("virtual_keywords", [])

    def is_valid_location(self, location: str) -> bool:
        """Check if location is valid (Klang Valley or virtual)."""
        if not location:
            return False
        loc_lower = location.lower()
        # Check for virtual keywords
        if any(kw in loc_lower for kw in self.virtual_keywords):
            return True
        # Check for Klang Valley locations
        return any(loc in loc_lower for loc in self.locations)

    def categorize(self, title: str, description: str = "") -> list[str]:
        """Categorize event based on title and description.

        Short keywords (<=3 chars like 'AI', 'ML', 'VC', 'KL') match on
        word boundaries to avoid e.g. 'AI' matching inside 'Français' or
        'ML' inside 'family'. Longer keywords use substring match because
        they're specific enough not to false-positive.
        """
        import re
        text = f"{title} {description}".lower()
        categories = []
        for topic, config in self.topics.items():
            keywords = config.get("keywords", [])
            for kw in keywords:
                kw_lower = kw.lower()
                if len(kw_lower) <= 3:
                    # Word-boundary match for short tokens
                    if re.search(rf"\b{re.escape(kw_lower)}\b", text):
                        categories.append(topic)
                        break
                else:
                    if kw_lower in text:
                        categories.append(topic)
                        break
        return categories if categories else ["Other"]

    # Sources whose curation we trust. Events from these bypass the topic
    # filter — they're already pre-vetted by being on a tracked venue or
    # agency calendar. Open platforms (Eventbrite, Meetup, Luma) still
    # need a topic match.
    CURATED_SOURCES = {"venues", "govagency", "insken", "kuskop", "instagram"}

    # Scrapers that already target KL/Selangor in their search queries.
    # Eventsize is included because its URL filters by ?location=Malaysia--KL
    # and ?location=Malaysia--Selangor, so the platform itself has already
    # promised the event is in our region.
    KL_TARGETED_SOURCES = {"meetup", "eventbrite", "luma", "social", "eventsize"}

    def filter_event(self, event: dict) -> bool:
        """Filter event based on location and topic.
        
        Only keeps events in Klang Valley (KL, Selangor, Putrajaya) or online.
        Events from KL-targeted scrapers (Meetup, Eventbrite, Luma) pass the
        location filter even if the location field is empty, since the search
        was already geo-scoped to KL.

        Events from curated sources (venues, govagency) bypass the topic
        filter so we don't drop trade shows / agency events that happen to
        not have an interest keyword in their title.
        """
        location = event.get("location", "")
        source = event.get("source_platform", "")

        # Check location validity
        location_ok = self.is_valid_location(location)

        if not location_ok:
            # Accept if location mentions Malaysia
            if location and "malaysia" in location.lower():
                location_ok = True
            # Accept events from KL-targeted scrapers even with empty/unknown location
            elif source in self.KL_TARGETED_SOURCES:
                location_ok = True
            # Accept events from curated venue / agency scrapers similarly
            elif source in self.CURATED_SOURCES:
                location_ok = True

        if not location_ok:
            return False

        # Curated sources bypass the topic gate
        if source in self.CURATED_SOURCES:
            return True

        # Open platforms must have at least one relevant category
        categories = event.get("categories", [])
        if not categories or categories == ["Other"]:
            return False
        return True

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Conservative title normalisation for dedup keys.

        Lowercase, strip punctuation, collapse whitespace. Year suffixes and
        other modifiers are NOT stripped - we never want to merge two
        legitimately different events.
        """
        import re
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", title.lower())).strip()

    def deduplicate(self, events: list[dict]) -> list[dict]:
        """Remove duplicate events based on normalised title and date.

        Same date is the bucket; same title (after normalisation) is the
        match. Times are ignored so a 7pm → 7:30pm reschedule does not
        produce a duplicate. `start_datetime` is expected to be naive MYT
        (the orchestrator runs `to_myt_naive` before this step).
        """
        seen = set()
        unique = []
        for event in events:
            title = event.get("title", "")
            start = event.get("start_datetime")
            if start is None:
                # Without a date we cannot dedup safely - skip.
                continue
            date_part = start.date() if hasattr(start, "date") else start
            key = f"{self._normalize_title(title)}|{date_part}"
            if key not in seen:
                seen.add(key)
                unique.append(event)
        return unique