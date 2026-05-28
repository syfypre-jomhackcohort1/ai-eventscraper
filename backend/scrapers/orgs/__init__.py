"""Per-organisation scrapers.

These scrape an individual agency's official website (not Facebook). They
exist because (a) FB Page walls are JS-rendered and unreliable, and
(b) most agencies maintain their own structured event/registration pages
that are far more accurate than scraping post text or flyer images.

Pattern: one file per organisation, each exposing a class that subclasses
BaseScraper. The Orchestrator wires them all in via the parent
OrgsAggregateScraper to keep the orchestrator init list short.
"""
from .insken import InskenScraper
from .kuskop import KuskopScraper

__all__ = ["InskenScraper", "KuskopScraper"]
