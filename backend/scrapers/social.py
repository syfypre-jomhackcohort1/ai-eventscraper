"""Social media scraper for Malaysian government agency public posts.

Uses approaches that don't require login or official APIs:
- YouTube RSS feeds (fully public)
- Facebook page plugin/embed endpoints
- Instagram embed endpoints for known post URLs
- RSS bridge services for converting social feeds
- Direct scraping of public profile pages where possible
"""
import json
import logging
import re
from datetime import datetime
from typing import Optional
from xml.etree import ElementTree

import httpx

from .base import BaseScraper

logger = logging.getLogger(__name__)


# Government agency social media profiles
# Format: (agency_name, platform, identifier, url)
AGENCY_PROFILES = [
    # YouTube channels (RSS feeds are fully public)
    ("MDEC", "youtube", "UCxxxxxxxxxxx", "https://www.youtube.com/@MyMDEC"),
    ("HRD Corp", "youtube", "UCxxxxxxxxxxx", "https://www.youtube.com/@HRDCorp"),
    ("INSKEN", "youtube", "UCxxxxxxxxxxx", "https://www.youtube.com/@inskenofficial"),
    ("SME Corp", "youtube", "UCxxxxxxxxxxx", "https://www.youtube.com/@smecorpmalaysia"),
    ("MCMC", "youtube", "UCxxxxxxxxxxx", "https://www.youtube.com/@MCMCgovmy"),
    ("NACSA", "youtube", "UCxxxxxxxxxxx", "https://www.youtube.com/@NCSAMalaysia"),
    ("Bank Negara", "youtube", "UCxxxxxxxxxxx", "https://www.youtube.com/@BankNegaraMalaysia"),
    ("SC Malaysia", "youtube", "UCxxxxxxxxxxx", "https://www.youtube.com/@SecuritiesCommissionMY"),
    ("MATRADE", "youtube", "UCxxxxxxxxxxx", "https://www.youtube.com/@MATRADE"),
    ("KUSKOP", "youtube", "UCxxxxxxxxxxx", "https://www.youtube.com/@KUSKOP"),
    ("MPC", "youtube", "UCxxxxxxxxxxx", "https://www.youtube.com/@MPCMalaysia"),
    ("Cybersecurity MY", "youtube", "UCxxxxxxxxxxx", "https://www.youtube.com/@CyberSecurityMalaysia"),

    # Facebook pages (will try embed/plugin approach)
    ("MDEC", "facebook", "MyMDEC", "https://www.facebook.com/MyMDEC"),
    ("HRD Corp", "facebook", "HRDCorp", "https://www.facebook.com/HRDCorp"),
    ("INSKEN", "facebook", "insaborneo", "https://www.facebook.com/insaborneo"),
    ("SME Corp", "facebook", "smecorpmalaysia", "https://www.facebook.com/smecorpmalaysia"),
    ("MCMC", "facebook", "MCMCgovmy", "https://www.facebook.com/MCMCgovmy"),
    ("MATRADE", "facebook", "MATRADE", "https://www.facebook.com/MATRADE"),
    ("KUSKOP", "facebook", "KUSKOP", "https://www.facebook.com/KUSKOPMalaysia"),
    ("MPC", "facebook", "MPCMalaysia", "https://www.facebook.com/MPCMalaysia"),
    ("Bank Negara", "facebook", "BankNegaraMY", "https://www.facebook.com/BankNegaraMY"),
    ("SC Malaysia", "facebook", "SecuritiesCommissionMalaysia", "https://www.facebook.com/SecuritiesCommissionMalaysia"),

    # Instagram profiles
    ("MDEC", "instagram", "mymdec", "https://www.instagram.com/mymdec"),
    ("INSKEN", "instagram", "insken_official", "https://www.instagram.com/insken_official"),
    ("HRD Corp", "instagram", "haborneo", "https://www.instagram.com/hrdcorp"),
    ("MCMC", "instagram", "mcaborneo", "https://www.instagram.com/mcmcgovmy"),
]

# Event-related keywords to filter social posts
EVENT_KEYWORDS = [
    "seminar", "workshop", "conference", "webinar", "forum", "summit",
    "hackathon", "bootcamp", "training", "programme", "program",
    "bengkel", "kursus", "latihan", "persidangan", "symposium",
    "expo", "exhibition", "meetup", "networking", "launch",
    "pelancaran", "dialog", "townhall", "register", "daftar",
    "jemputan", "invitation", "upcoming", "join us", "sertai",
    "event", "acara", "majlis", "ceremony",
]


class SocialMediaScraper(BaseScraper):
    """Scrape event announcements from government agency social media.

    Uses public endpoints that don't require authentication:
    - YouTube RSS feeds
    - Facebook page embed widgets
    - Direct page scraping where possible
    """

    def __init__(self):
        super().__init__("Social", "https://www.youtube.com", delay=2.0)

    def scrape(self) -> list[dict]:
        """Scrape events from social media platforms."""
        events = []

        # YouTube RSS feeds — most reliable, fully public
        events.extend(self._scrape_youtube_feeds())

        # Facebook — try embed/plugin approach
        events.extend(self._scrape_facebook_embeds())

        # Deduplicate
        events = self._deduplicate(events)
        logger.info(f"Social media total: {len(events)} events")
        return events

    # ------------------------------------------------------------------
    # YouTube (RSS feeds — fully public, no auth needed)
    # ------------------------------------------------------------------

    def _scrape_youtube_feeds(self) -> list[dict]:
        """Scrape YouTube channels via RSS feeds."""
        events = []
        youtube_profiles = [p for p in AGENCY_PROFILES if p[1] == "youtube"]

        for agency_name, _, _, channel_url in youtube_profiles:
            try:
                # First, resolve the channel ID from the channel page
                channel_id = self._get_youtube_channel_id(channel_url)
                if not channel_id:
                    continue

                # Fetch the RSS feed
                feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
                self._wait_for_polite_delay()
                response = httpx.get(feed_url, timeout=15.0, follow_redirects=True)
                if response.status_code != 200:
                    continue

                # Parse the Atom feed
                feed_events = self._parse_youtube_feed(response.text, agency_name)
                events.extend(feed_events)

                if feed_events:
                    logger.info(f"YouTube {agency_name}: found {len(feed_events)} event posts")
            except Exception as e:
                logger.debug(f"Error scraping YouTube for {agency_name}: {e}")

        return events

    def _get_youtube_channel_id(self, channel_url: str) -> Optional[str]:
        """Extract channel ID from a YouTube channel page."""
        try:
            self._wait_for_polite_delay()
            response = httpx.get(
                channel_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                timeout=15.0,
                follow_redirects=True,
            )
            if response.status_code != 200:
                return None

            # Look for channel ID in meta tags or page source
            # Pattern: "channelId":"UCxxxxxxxx" or channel_id=UCxxxxxxxx
            match = re.search(r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]+)"', response.text)
            if match:
                return match.group(1)

            # Try meta tag
            match = re.search(r'<meta\s+itemprop="channelId"\s+content="(UC[a-zA-Z0-9_-]+)"', response.text)
            if match:
                return match.group(1)

            # Try link tag with RSS
            match = re.search(r'channel_id=(UC[a-zA-Z0-9_-]+)', response.text)
            if match:
                return match.group(1)

            return None
        except Exception as e:
            logger.debug(f"Error getting YouTube channel ID from {channel_url}: {e}")
            return None

    def _parse_youtube_feed(self, xml_text: str, agency_name: str) -> list[dict]:
        """Parse YouTube Atom RSS feed for event-related videos."""
        events = []
        try:
            ns = {
                "atom": "http://www.w3.org/2005/Atom",
                "media": "http://search.yahoo.com/mrss/",
                "yt": "http://www.youtube.com/xml/schemas/2015",
            }
            root = ElementTree.fromstring(xml_text)

            for entry in root.findall("atom:entry", ns):
                title_el = entry.find("atom:title", ns)
                published_el = entry.find("atom:published", ns)
                link_el = entry.find("atom:link", ns)
                media_group = entry.find("media:group", ns)

                if title_el is None or published_el is None:
                    continue

                title = title_el.text or ""
                title_lower = title.lower()

                # Only include posts that mention events
                if not any(kw in title_lower for kw in EVENT_KEYWORDS):
                    continue

                # Parse date
                try:
                    pub_date = datetime.fromisoformat(published_el.text.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    continue

                url = ""
                if link_el is not None:
                    url = link_el.get("href", "")

                description = ""
                if media_group is not None:
                    desc_el = media_group.find("media:description", ns)
                    if desc_el is not None and desc_el.text:
                        description = desc_el.text[:500]

                # Try to extract actual event date from title/description
                event_date = self._extract_event_date(title + " " + description)
                if event_date is None:
                    event_date = pub_date

                thumbnail = ""
                if media_group is not None:
                    thumb_el = media_group.find("media:thumbnail", ns)
                    if thumb_el is not None:
                        thumbnail = thumb_el.get("url", "")

                events.append(self._create_event_dict(
                    title=f"[{agency_name}] {title}",
                    description=description,
                    start_datetime=event_date,
                    location="Malaysia",
                    organiser=agency_name,
                    source_url=url,
                    categories=[self._categorize(title)],
                    image_url=thumbnail,
                ))
        except ElementTree.ParseError as e:
            logger.debug(f"Error parsing YouTube feed: {e}")

        return events

    # ------------------------------------------------------------------
    # Facebook (embed widget approach)
    # ------------------------------------------------------------------

    def _scrape_facebook_embeds(self) -> list[dict]:
        """Try to get Facebook page posts via the page plugin embed."""
        events = []
        fb_profiles = [p for p in AGENCY_PROFILES if p[1] == "facebook"]

        for agency_name, _, page_id, page_url in fb_profiles:
            try:
                # Try the Facebook page plugin endpoint
                # This is the embed widget that websites use to show FB feeds
                embed_url = (
                    f"https://www.facebook.com/plugins/page.php"
                    f"?href=https%3A%2F%2Fwww.facebook.com%2F{page_id}"
                    f"&tabs=timeline&width=500&height=800"
                    f"&small_header=true&adapt_container_width=true"
                    f"&hide_cover=true&show_facepile=false"
                )

                self._wait_for_polite_delay()
                response = httpx.get(
                    embed_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "text/html",
                    },
                    timeout=15.0,
                    follow_redirects=True,
                )

                if response.status_code != 200:
                    continue

                soup = self._parse_html(response.text)
                fb_events = self._parse_facebook_embed(soup, agency_name, page_url)
                events.extend(fb_events)

                if fb_events:
                    logger.info(f"Facebook {agency_name}: found {len(fb_events)} event posts")
            except Exception as e:
                logger.debug(f"Error scraping Facebook embed for {agency_name}: {e}")

        return events

    def _parse_facebook_embed(self, soup, agency_name: str, page_url: str) -> list[dict]:
        """Parse Facebook page plugin embed HTML for event posts."""
        events = []

        # The embed widget renders posts as divs
        # Look for post content that mentions events
        posts = soup.find_all("div", class_=re.compile(r"_5pbx|userContent|_5rgt"))
        if not posts:
            # Try broader selectors
            posts = soup.find_all("p")

        for post in posts:
            text = post.get_text(strip=True)
            if not text or len(text) < 20:
                continue

            text_lower = text.lower()
            if not any(kw in text_lower for kw in EVENT_KEYWORDS):
                continue

            # Try to extract event date from the post text
            event_date = self._extract_event_date(text)
            if event_date is None:
                continue  # Skip posts without a discernible date

            # Extract a title (first line or first sentence)
            title = text.split("\n")[0][:100].strip()
            if not title:
                title = text[:100].strip()

            events.append(self._create_event_dict(
                title=f"[{agency_name}] {title}",
                description=text[:500],
                start_datetime=event_date,
                location="Malaysia",
                organiser=agency_name,
                source_url=page_url,
                categories=[self._categorize(text)],
            ))

        return events

    # ------------------------------------------------------------------
    # Date extraction from free text
    # ------------------------------------------------------------------

    def _extract_event_date(self, text: str) -> Optional[datetime]:
        """Try to extract an event date from free-form text."""
        if not text:
            return None

        # Pattern: "15 May 2026", "May 15, 2026", "15/05/2026", "2026-05-15"
        patterns = [
            # ISO format
            (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
            # DD/MM/YYYY
            (r"(\d{1,2}/\d{1,2}/\d{4})", "%d/%m/%Y"),
            # DD-MM-YYYY
            (r"(\d{1,2}-\d{1,2}-\d{4})", "%d-%m-%Y"),
        ]

        for pattern, fmt in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    dt = datetime.strptime(match.group(1), fmt)
                    # Only accept dates in 2025-2027 range
                    if 2025 <= dt.year <= 2027:
                        return dt
                except ValueError:
                    continue

        # Month name patterns: "15 May 2026", "May 15, 2026"
        months = {
            "january": 1, "february": 2, "march": 3, "april": 4,
            "may": 5, "june": 6, "july": 7, "august": 8,
            "september": 9, "october": 10, "november": 11, "december": 12,
            "jan": 1, "feb": 2, "mar": 3, "apr": 4,
            "mei": 5, "jun": 6, "jul": 7, "ogos": 8,  # Malay months
            "sept": 9, "okt": 10, "nov": 11, "dis": 12,
        }

        # "15 May 2026" or "15 Mei 2026"
        match = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text, re.IGNORECASE)
        if match:
            day, month_str, year = match.groups()
            month_num = months.get(month_str.lower())
            if month_num and 2025 <= int(year) <= 2027:
                try:
                    return datetime(int(year), month_num, int(day))
                except ValueError:
                    pass

        # "May 15, 2026"
        match = re.search(r"(\w+)\s+(\d{1,2}),?\s+(\d{4})", text, re.IGNORECASE)
        if match:
            month_str, day, year = match.groups()
            month_num = months.get(month_str.lower())
            if month_num and 2025 <= int(year) <= 2027:
                try:
                    return datetime(int(year), month_num, int(day))
                except ValueError:
                    pass

        return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate(events: list[dict]) -> list[dict]:
        """Remove duplicate events."""
        seen = set()
        unique = []
        for event in events:
            key = event["title"].lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(event)
        return unique

    def _categorize(self, title: str) -> str:
        """Categorize event based on title keywords."""
        title_lower = title.lower()
        if any(kw in title_lower for kw in ["ai", "machine learning", "ml", "llm", "generative", "kecerdasan buatan"]):
            return "AI"
        if any(kw in title_lower for kw in ["cyber", "security", "infosec", "keselamatan siber"]):
            return "Cybersecurity"
        if any(kw in title_lower for kw in ["blockchain", "web3", "crypto", "nft"]):
            return "Blockchain"
        if any(kw in title_lower for kw in ["investment", "trading", "stock", "finance", "pelaburan"]):
            return "Investment"
        if any(kw in title_lower for kw in ["startup", "entrepreneur", "founder", "usahawan", "keusahawanan"]):
            return "Entrepreneurship"
        return "Tech"
