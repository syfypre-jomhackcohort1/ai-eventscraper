"""Instagram scraping with provider-agnostic backend.

Architecture:
  InstagramScraper (orchestrator-facing)
    └── IGBackend (abstract, swappable)
          ├── ApifyBackend
          ├── HikerAPIBackend
          └── DisabledBackend (no-op when no API key configured)

Environment-driven config:
  IG_BACKEND     = apify | hikerapi | disabled  (default: disabled)
  APIFY_TOKEN    = required when IG_BACKEND=apify
  HIKERAPI_KEY   = required when IG_BACKEND=hikerapi

Once a backend returns posts (caption + image_url + post_url + timestamp),
we hand each post to the FlyerExtractor which uses a vision LLM to extract
structured event data from the flyer image when the caption alone is
insufficient.
"""
from .scraper import InstagramScraper

__all__ = ["InstagramScraper"]
