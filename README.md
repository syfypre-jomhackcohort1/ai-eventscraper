# KV Events Discovery Agent

An automated event aggregator that scrapes tech, business, and startup events from multiple platforms and displays them in a clean calendar view. Built for the Klang Valley (Malaysia) ecosystem but configurable for any city or region.

![status](https://img.shields.io/badge/status-active-brightgreen) ![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Multi-source scraping** — Eventbrite, Meetup, Luma, Eventsize, YouTube, MITEC venue calendar, government agency websites, Instagram (via API), Facebook Page walls (via Playwright)
- **Vision-LLM flyer extraction** — pluggable Gemini / OpenAI provider that reads event flyer images for posts where the date lives only in the image
- **Provider-agnostic Instagram backend** — swap between Apify and HikerAPI by changing one env var
- **Smart filtering** — topics in YAML, KL/Selangor location guard, automatic past-event drop, dedup across sources
- **Auto-refresh** — scrapes 3x daily (8am, 4pm, 12am MYT)
- **Calendar UI** — monthly view with color-coded categories, hover tooltips, click-through to event details
- **No paid APIs required for the core** — paid services (Apify, Gemini) are optional layers

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for the frontend)

### Backend Setup

```bash
pip install -r requirements.txt
python -m playwright install chromium  # only if you enable Facebook Wall scraping
cp .env.example .env                   # then edit .env to add API keys (all optional)
python -m uvicorn backend.main:app --reload
```

### Frontend Setup

```bash
cd frontend
npm install
npm run build           # builds into ../static/, served by the backend at /
# OR for development with hot-reload:
npm run dev             # serves at http://localhost:3000 with proxy to backend
```

Open http://localhost:8000 (production) or http://localhost:3000 (dev).

## Configuration

All configuration lives in two files. No code changes needed for normal customisation.

### `config/sources.yaml`

- `search.*` — geo / keyword settings for the platform scrapers
- `scrapers.*` — toggle individual scrapers on/off
- `fb_pages` — list of Facebook Pages to scrape via Playwright
- `ig_profiles` — list of Instagram profiles to scrape via the active backend

### `config/filters.yaml`

- `topics` — interest categories with their keywords and colors. Edit this to change which events are kept and how they're displayed.
- `locations.include` — areas considered "in scope". Events outside this list (and not virtual) are dropped from open platforms.

## Environment Variables

All optional — the app starts and runs with none of them set. See `.env.example` for the full list.

| Variable | Purpose |
|---|---|
| `IG_BACKEND` | `apify` \| `hikerapi` \| `disabled` (default) |
| `APIFY_TOKEN` | Required when `IG_BACKEND=apify` |
| `HIKERAPI_KEY` | Required when `IG_BACKEND=hikerapi` |
| `LLM_PROVIDER` | `gemini` \| `openai` \| `disabled` (default) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | For Gemini vision-LLM flyer extraction |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | For OpenAI vision-LLM flyer extraction |

**Never commit `.env` to git.** It's in `.gitignore`. Use `.env.example` as a template.

## Architecture

```
kv-events-agent/
├── backend/
│   ├── main.py                     # FastAPI app entry point
│   ├── database.py                 # SQLite + Event model
│   ├── orchestrator.py             # Coordinates all scrapers, normalises tz, dedups
│   ├── scheduler.py                # 3x daily cron (8am, 4pm, 12am MYT)
│   ├── filters.py                  # Location + topic + curated-source filter logic
│   ├── timezone.py                 # All times normalised to Asia/Kuala_Lumpur
│   ├── models.py                   # Pydantic response shapes
│   ├── api/events.py               # REST API
│   └── scrapers/
│       ├── base.py                 # Polite HTTP base class with retries
│       ├── eventbrite.py           # Eventbrite HTML + JSON-LD
│       ├── meetup.py               # Meetup HTML + JSON-LD
│       ├── luma.py                 # Luma geo-coordinate API
│       ├── eventsize.py            # Eventsize listing-page card parsing
│       ├── social.py               # YouTube RSS feeds
│       ├── govagency.py            # Generic agency website scraping
│       ├── venues.py               # MITEC + WTC KL convention centre calendars
│       ├── fb_wall.py              # FB Page wall via Playwright (event-shaped post detector)
│       ├── orgs/                   # Per-organisation targeted scrapers
│       │   ├── _geo.py             # Shared KL/Selangor out-of-region filter
│       │   ├── insken.py           # INSKEN registration page parser
│       │   └── kuskop.py           # KUSKOP event carousel parser
│       └── instagram/              # IG via pluggable backend
│           ├── backend.py          # IGBackend interface + factory
│           ├── apify_backend.py    # Apify provider
│           ├── hikerapi_backend.py # HikerAPI provider
│           ├── flyer_extractor.py  # Vision-LLM event extractor
│           └── scraper.py          # Top-level Instagram scraper
├── config/
│   ├── filters.yaml                # Topics, keywords, location include-list
│   └── sources.yaml                # Per-scraper config + tracked profiles
├── frontend/
│   ├── src/
│   │   ├── App.jsx                 # Calendar with hover tooltips
│   │   └── components/
│   │       ├── EventModal.jsx      # Click-through detail modal
│   │       ├── FilterChips.jsx     # Topic toggle chips
│   │       └── Legend.jsx          # Color legend
│   └── vite.config.js
├── tests/                          # 109+ regression tests
├── DESIGN.md                       # Wedge plan + decisions
└── .env.example                    # Optional config template
```

## Data Sources & How They're Scraped

| Source | Method | Auth | Notes |
|---|---|---|---|
| Eventbrite | HTML + JSON-LD | None | Public search page per keyword |
| Meetup | HTML + JSON-LD | None | Geo-scoped search |
| Luma | Public API | None | Geo-coordinate endpoint |
| Eventsize | Listing page card text + per-event enrichment | None | JSON-LD dates were unreliable; we use visible card text |
| YouTube | RSS feeds | None | Per-channel atom feed |
| MITEC | HTML | None | `.card`-element parsing of the event calendar |
| WTC KL | Hardcoded list | None | Static (their site requires JS) |
| INSKEN | Registration page HTML | None | `.artikel-grid > .grid-33` cards |
| KUSKOP | Carousel widget HTML | None | `.owl-carousel-kalendar` parsing |
| Facebook Page wall | Playwright + post text | None | JS rendering required; event-keyword + date heuristic |
| Instagram | Apify or HikerAPI | API key | Vision-LLM extracts events from flyer images |

## Adding a New Scraper

```python
from .base import BaseScraper

class MyNewScraper(BaseScraper):
    def __init__(self):
        super().__init__("MySource", "https://example.com", delay=2.0)

    def scrape(self) -> list[dict]:
        html = self._fetch_html(self.base_url)
        soup = self._parse_html(html)
        return [
            self._create_event_dict(
                title="...",
                start_datetime=datetime(2026, 6, 18),
                location="Kuala Lumpur",
                organiser="...",
                source_url="...",
                categories=[],   # orchestrator re-categorises via filters.yaml
            )
        ]
```

Then wire it into `backend/scrapers/__init__.py` and `backend/orchestrator.py`.

## Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

Tests cover: timezone normalisation, dedup, category matching with word-boundary safety, venue date parsing, Eventsize date repair, FB wall keyword logic, INSKEN/KUSKOP parsers, geo filter, IG flyer extractor JSON parsing.

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/events` | List events (filter by `month`, `category`, `location`) |
| GET | `/api/events/{id}` | Get single event |
| GET | `/api/categories` | List available categories from `filters.yaml` |
| GET | `/api/sources` | List scraper sources |
| POST | `/api/refresh` | Trigger manual re-scrape (background) |
| GET | `/health` | Health check |

## Security

- Secrets live only in `.env` which is gitignored
- `.env.example` shows the variable shape with empty values
- No API key is hardcoded anywhere; all access goes through `os.environ`
- Probe / debug / one-off scripts (`probe_*.py`, `trace_*.py`, etc.) are gitignored to prevent accidental token leaks

If a token is ever leaked, rotate it immediately at the provider's dashboard.

## License

MIT — see [LICENSE](LICENSE).
