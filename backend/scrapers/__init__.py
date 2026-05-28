"""Scrapers package."""
from .base import BaseScraper
from .eventbrite import EventbriteScraper
from .meetup import MeetupScraper
from .luma import LumaScraper
from .eventsize import EventsizeScraper
from .peatix import PeatixScraper
from .social import SocialMediaScraper
from .govagency import GovAgencyScraper
from .venues import VenueScraper
from .fb_wall import FacebookWallScraper
from .orgs.insken import InskenScraper
from .orgs.kuskop import KuskopScraper
from .instagram import InstagramScraper

__all__ = [
    "BaseScraper",
    "EventbriteScraper",
    "MeetupScraper",
    "LumaScraper",
    "EventsizeScraper",
    "PeatixScraper",
    "SocialMediaScraper",
    "GovAgencyScraper",
    "VenueScraper",
    "FacebookWallScraper",
    "InskenScraper",
    "KuskopScraper",
    "InstagramScraper",
]
