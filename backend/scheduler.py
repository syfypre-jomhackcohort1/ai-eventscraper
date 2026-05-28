"""APScheduler setup — scrapes at 8am, 4pm, and 12am MYT daily."""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.orchestrator import run_scrape

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def start_scheduler():
    """Start the background scheduler with 3x daily scrape (8am, 4pm, 12am MYT).
    
    MYT = UTC+8, so:
    - 8am MYT  = 0:00 UTC
    - 4pm MYT  = 8:00 UTC
    - 12am MYT = 16:00 UTC
    """
    if not scheduler.running:
        scheduler.add_job(
            run_scrape,
            CronTrigger(hour="0,8,16", minute=0),  # UTC hours
            id="scheduled_scrape",
            name="Scrape events at 8am, 4pm, 12am MYT",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Scheduler started — scraping at 8am, 4pm, 12am MYT daily")


def stop_scheduler():
    """Stop the background scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
