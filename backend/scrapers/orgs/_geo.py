"""Shared geo-filter helpers for per-organisation scrapers.

Aiman's stated scope is Kuala Lumpur, Selangor, or online/virtual events
only. Most agencies run nationwide events; per-org scrapers reuse this
helper to drop the out-of-region events.
"""
import re

# State / city tokens that indicate the event is NOT in KL or Selangor.
# Conservative list - we'd rather drop a KL event than show a Penang one.
# Multi-character markers below are checked as substrings; short tokens
# (<=4 chars or all-caps acronyms) are checked on word boundaries to
# avoid false positives like 'ums' matching inside 'tsunami'.
OUT_OF_REGION_MARKERS = (
    "sarawak", "sabah", "perak", "kedah", "kelantan", "johor",
    "terengganu", "melaka", "penang", "pulau pinang", "perlis",
    "pahang", "negeri sembilan",
    # Specific cities outside KL/Selangor
    "kuching", "miri", "kota kinabalu",
    "ipoh", "taiping", "teluk intan",
    "alor setar", "kulim",
    "georgetown", "george town", "seberang jaya", "seberang perai",
    "kota bharu",
    "kuala terengganu",
    "kuantan", "temerloh",
    "seremban",
    "johor bahru", "iskandar puteri",
    # International - Meetup/Luma/Eventbrite location filters leak these
    "singapore", "manila", "philippines", "filipino",
    "jakarta", "bandung", "bali", "surabaya",
    "bangkok", "phuket", "chiang mai",
    "ho chi minh", "hanoi", "saigon",
    "mumbai", "delhi", "bengaluru",
    "lagos", "nigeria", "abuja",
    "manchester",
    "denver", "colorado", "florida", "texas", "california",
    "ontario", "vancouver", "toronto",
    "beijing", "shanghai", "shenzhen", "guangzhou",
    "hong kong", "taipei", "tokyo", "osaka", "seoul",
)

# Short / ambiguous tokens that need word-boundary matching to avoid
# false positives. 'ums' can appear inside 'tsunami', 'rumour'; 'london'
# is a substring of 'londoners'; 'umt' is fine on its own but appears
# inside random tech acronyms; etc.
WORD_BOUNDARY_MARKERS = (
    "ums", "umt", "unisza", "unimas",
    "uitm seri iskandar", "uitm sungai petani", "uitm dungun",
    "london",
)


def _has_non_latin_script(text: str) -> bool:
    """Return True if the text contains characters from non-Latin scripts
    typically used outside Malaysia (Chinese, Japanese, Arabic, Cyrillic,
    Thai, Korean). Malay is written in Latin script so this is a clean
    signal that the event venue is foreign."""
    for ch in text:
        cp = ord(ch)
        # CJK Unified Ideographs (Chinese / Japanese kanji)
        if 0x4E00 <= cp <= 0x9FFF:
            return True
        # Hiragana / Katakana (Japanese)
        if 0x3040 <= cp <= 0x30FF:
            return True
        # Hangul (Korean)
        if 0xAC00 <= cp <= 0xD7AF:
            return True
        # Cyrillic (Russian, Ukrainian, etc.)
        if 0x0400 <= cp <= 0x04FF:
            return True
        # Arabic (excluding the Bismillah character which appears in Malay)
        if 0x0600 <= cp <= 0x06FF and cp != 0xFDFD:
            return True
        # Thai
        if 0x0E00 <= cp <= 0x0E7F:
            return True
    return False


def is_out_of_region(text: str) -> bool:
    """True if the given text contains a city/state token outside KL/Selangor.

    Pass `location + " " + title + " " + organiser` for best signal.
    Note: non-Latin script detection is NOT done here because Chinese-
    titled events at Malaysian venues are common and legitimate. Use
    is_foreign_venue(location_only) for that check.
    """
    if not text:
        return False
    lower = text.lower()
    if any(m in lower for m in OUT_OF_REGION_MARKERS):
        return True
    # Word-boundary checks for ambiguous tokens
    for token in WORD_BOUNDARY_MARKERS:
        if re.search(rf"\b{re.escape(token)}\b", lower):
            return True
    return False


def is_foreign_venue(location: str) -> bool:
    """True if the venue field alone contains non-Latin script characters
    (Chinese, Japanese, Arabic, Cyrillic, Thai, Korean) - a clean signal
    that the venue is foreign. Use this only on the location/venue field,
    NOT on titles, since titles in non-Latin scripts can be at Malaysian
    venues."""
    if not location:
        return False
    return _has_non_latin_script(location)
