"""Scraper orchestrator - coordinates all scrapers."""
import logging
from datetime import datetime
from pathlib import Path

# Load .env so standalone runs (python -m backend.orchestrator)
# also pick up env vars without going through main.py.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass

from backend.database import SessionLocal, Event
from backend.filters import FilterEngine
from backend.scrapers import EventbriteScraper, MeetupScraper, LumaScraper, EventsizeScraper, PeatixScraper, SocialMediaScraper, GovAgencyScraper, VenueScraper, FacebookWallScraper, InskenScraper, KuskopScraper, InstagramScraper
from backend.timezone import normalize_event_times

logger = logging.getLogger(__name__)


class Orchestrator:
    """Coordinates scraping from all sources."""

    def __init__(self):
        self.filter_engine = FilterEngine()
        self.scrapers = [
            EventbriteScraper(),
            MeetupScraper(),
            LumaScraper(),
            EventsizeScraper(),
            PeatixScraper(),
            SocialMediaScraper(),
            GovAgencyScraper(),
            VenueScraper(),
            FacebookWallScraper(),
            InskenScraper(),
            KuskopScraper(),
            InstagramScraper(),
        ]

    def run_all(self) -> int:
        """Run all scrapers and save events to database."""
        all_events = []

        for scraper in self.scrapers:
            try:
                logger.info(f"Running scraper: {scraper.name}")
                events = scraper.scrape()
                # Normalise every event to naive MYT immediately. Single
                # chokepoint - downstream code never sees mixed tz again.
                events = [normalize_event_times(e) for e in events]
                # Sanity: drop events where end is before start. These are
                # always parser bugs (e.g. fragments from two events glued
                # together) and never legitimate.
                clean = []
                for e in events:
                    s, end = e.get("start_datetime"), e.get("end_datetime")
                    if s and end and end < s:
                        logger.warning(
                            f"Dropping event with end < start: '{e.get('title','')[:60]}' "
                            f"start={s} end={end} src={e.get('source_platform')}"
                        )
                        continue
                    clean.append(e)
                events = clean
                # Re-categorise using filters.yaml as the single source of
                # truth. Per-scraper _categorize() produces a single legacy
                # bucket ("Tech", "Other"); this overwrites with the topic
                # set from YAML so new topics in YAML reach the DB without
                # editing every scraper.
                for e in events:
                    e["categories"] = self.filter_engine.categorize(
                        e.get("title", ""),
                        e.get("description", "") or "",
                    )
                logger.info(f"  -> Found {len(events)} events")
                all_events.extend(events)
            except Exception as e:
                logger.error(f"Error running {scraper.name}: {e}")

        # Apply filters
        filtered = [e for e in all_events if self.filter_engine.filter_event(e)]
        logger.info(f"After filtering: {len(filtered)} events")

        # Universal geo guard: drop any event whose location/title/organiser
        # text indicates a foreign venue. The check has two parts:
        # 1. Region marker scan on combined text - catches Singapore Options
        #    Group, Beijing AI conferences, etc. that the platform's own
        #    location filter let through.
        # 2. Non-Latin script check on the VENUE field only - catches a
        #    Beijing venue like '青龙湖湿地公园' but lets Chinese-titled
        #    events at Malaysian venues through.
        from backend.scrapers.orgs._geo import is_out_of_region, is_foreign_venue
        before_geo = len(filtered)
        filtered = [
            e for e in filtered
            if not is_out_of_region(
                f"{e.get('location','')} {e.get('title','')} {e.get('organiser','')}"
            )
            and not is_foreign_venue(e.get("location", ""))
        ]
        logger.info(f"After geo filter: {len(filtered)} events (dropped {before_geo - len(filtered)} foreign)")

        # Remove past events and events with no real date.
        # Compare in MYT since events are normalised to naive MYT above.
        from backend.timezone import MYT
        now_myt = datetime.now(MYT).replace(tzinfo=None)
        today_start = now_myt.replace(hour=0, minute=0, second=0, microsecond=0)
        future_events = []
        for e in filtered:
            start = e.get("start_datetime")
            if not start:
                continue
            # All events are naive MYT at this point; tzinfo stripping above
            # is defensive in case a scraper bypasses normalize_event_times.
            start_naive = start.replace(tzinfo=None) if getattr(start, "tzinfo", None) else start
            if start_naive >= today_start:
                future_events.append(e)
            else:
                logger.debug(f"Skipping past event: {e.get('title')[:50]} ({start_naive.date()})")
        logger.info(f"After date filter: {len(future_events)} future events (dropped {len(filtered) - len(future_events)} past)")

        # Deduplicate
        unique = self.filter_engine.deduplicate(future_events)
        logger.info(f"After dedup: {len(unique)} unique events")

        # Save to database
        saved = self.save_events(unique)
        logger.info(f"Saved {saved} events to database")
        return saved

    def save_events(self, events: list[dict]) -> int:
        """Save events to database."""
        db = SessionLocal()
        saved = 0
        try:
            for event_data in events:
                # Generate ID (title + date only - source excluded so dupes
                # from different platforms collide here too)
                event_id = Event.generate_id(
                    event_data["title"],
                    event_data["start_datetime"],
                )
                event_data["id"] = event_id

                # Check if exists
                existing = db.query(Event).filter(Event.id == event_id).first()
                if existing:
                    continue

                # Create event
                event = Event(
                    id=event_id,
                    title=event_data["title"],
                    description=event_data.get("description"),
                    start_datetime=event_data["start_datetime"],
                    end_datetime=event_data.get("end_datetime"),
                    location=event_data.get("location"),
                    is_virtual=event_data.get("is_virtual", False),
                    organiser=event_data.get("organiser"),
                    source_platform=event_data["source_platform"],
                    source_url=event_data.get("source_url"),
                    categories=",".join(event_data.get("categories", [])),
                    image_url=event_data.get("image_url"),
                )
                db.add(event)
                saved += 1

            db.commit()
        except Exception as e:
            logger.error(f"Error saving events: {e}")
            db.rollback()
        finally:
            db.close()

        return saved


def run_scrape():
    """Entry point for scheduled/manual scrape."""
    orchestrator = Orchestrator()
    return orchestrator.run_all()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = run_scrape()
    print(f"Scraped {count} events")