# DESIGN — KV Events Agent: Zero-Miss Wedge

_Status: Draft. Office Hours discovery + Eng Review on 2026-05-27._

## Problem statement (reframed)

The original ask was "scrape Instagram / LinkedIn / Facebook / Threads / GLC websites." That conflated three different problems:

1. **Trust bug** — Solana Network State appears on May 25 _and_ May 26. Same event, two cards, different dates. Root cause (confirmed in eng review): `tz_normalize` does not exist. Luma returns timezone-aware UTC datetimes; other scrapers return naive datetimes assumed to be MYT. The Luma event at `2026-05-25T16:30:00Z` is May 26 00:30 in MYT. `filters.deduplicate` keys on `f"{title}|{start_datetime}"`, so the two scraper outputs produce different string keys and survive dedup. `Event.generate_id` then produces two different SHA hashes, so both rows land in SQLite. The fix is centralised timezone normalisation, not architectural change.
2. **Coverage gap** — events Aiman misses are announced on **Facebook, Instagram, and Threads first**, and only sometimes (or never) make it to Luma / Eventbrite / Eventsize / Meetup. The platform scrapers are necessary but not sufficient.
3. **Scope confusion** — "scrape every GLC website" is a platform-first framing. The real shape is **organiser-first**: for each organiser Aiman cares about, watch every channel they post to.

The reframed problem: **Aiman should never have to open Instagram or Eventbrite again to find a KL tech event in his interest areas.** That promise has two preconditions — the calendar must be correct (no dupes), and it must catch announcements wherever they land.

## Target user

**Aiman, 28, indie founder in Bangsar.** Checks the calendar Sunday night to plan his week. Goes to 2–3 events a week. Network is the product. Today he searches Luma + Eventbrite manually and scrolls FB / IG / Threads feeds for his ~30 favourite organisers. Misses ~1 event a week that he wishes he hadn't.

This is a tool for Aiman first. Anyone else is a bonus.

## Core assumption to validate

> For a curated list of ~17 KL/Selangor agencies + venues, **Facebook Events tab + official websites alone** close enough of Aiman's coverage gap that we do not need IG / Threads / flyer parsing in v1.

If true: wedge ships and the project stays cheap. If false: we need the medium-scope work (IG / Threads + vision LLM flyer parsing) and we'll have learned that from real data instead of guessing.

## Chosen approach: Narrow wedge (2–3 days)

Four commits, each green before the next. Built in this order:

### Commit 1 — Timezone normalisation + dedup fix
- New helper `backend/timezone.py` exposing `to_myt_naive(dt)`. Converts tz-aware UTC datetimes to Asia/Kuala_Lumpur and strips tzinfo. Naive datetimes pass through unchanged.
- Orchestrator runs every event through `to_myt_naive` immediately after `scraper.scrape()` returns, before filtering / deduping / saving. Single chokepoint.
- Dedup key changes from `f"{title}|{start_datetime}"` to `f"{normalize_title(title)}|{start_datetime.date()}"`. Title normalisation: lowercase, strip punctuation, collapse whitespace. **Same date** is enough to dedup; small time changes do not create dupes.
- `Event.generate_id` drops `source` from the hash so the same event from two platforms collides at the DB layer too.
- Regression test: Solana Network State, two scrapers (Luma UTC + Eventsize naive MYT), survives as one event on May 26 MYT. Test lives in `tests/test_dedup.py`.

### Commit 2 — Filter config refresh
- Extend `config/filters.yaml` topics with `Hackathon`, `Anti-Scam`, `Social Enterprise`, `Fintech`. Existing six (AI / Cybersecurity / Blockchain / Investment / Trading / Entrepreneurship) stay.
- No code changes; only YAML and category color additions.
- Validate: existing events get categorised under the new topics on a fresh scrape.

### Commit 3 — Facebook Events tab scraper
- New scraper: `backend/scrapers/facebook_events.py`. Targets `facebook.com/<page>/events` — the public events tab, not the page plugin embed.
- Page handles configured in `config/sources.yaml` under `facebook_events.pages`. 17 organisers from the wedge list.
- Polite rate: 3-second delay (matches `govagency`).
- **Delete dead Facebook code in `backend/scrapers/social.py`.** YouTube RSS portion stays. Decision locked: delete, don't disable.
- If `facebook.com/<page>/events` returns 0 events for a page, log WARN. No retry.

### Commit 4 — Coverage fill on existing scrapers
- Add to `govagency.py` `AGENCIES` list: MCMC, MITI, SKM, MRANTI, CSM (5 missing from the 14 agency/regulator wedge list).
- Add WTC KL (`worldtradecentrekl.com/events/`) to `venues.py`.
- No new files.

### Why narrow wedge

- Commit 1 alone repairs trust. Aiman won't believe new events while dupes remain.
- FB Events tab is structured HTML — same shape as Eventbrite. No vision LLM, no flyer parsing, no data-quality fear yet.
- We can measure coverage lift from FB Events alone before committing to IG / Threads / vision-LLM.
- The organiser list is the moat. Adding a new organiser becomes one YAML entry plus possibly one URL in `govagency.py`.

## Success criteria

Run the wedge for 2 weeks with Aiman as sole user. Promote to medium scope only if **all** of:

1. **Zero duplicates.** Aiman reports no duplicate events on the calendar across 14 days. (Tracked: weekly check.)
2. **Missed-event rate ≤ 1 per week.** Aiman logs each event he hears about elsewhere that should have been on the calendar. Target: ≤ 1 / week, down from the current ~1 / week baseline. (We need the wedge to at least hold the line; ideally improve.)
3. **FB Events contribution ≥ 20%.** At least 1 in 5 events that survived dedup came from the new FB Events scraper. If lower, FB Events isn't the gap-closer and medium scope must address IG / Threads.
4. **Filter precision ≥ 80%.** Of events shown on the calendar, ≥ 80% match Aiman's stated topics. He skims a week's worth and tags each as "relevant / not relevant".

## Out of scope (explicit)

The following are **deferred to medium scope** and are not built in the wedge:

- **Instagram scraping** of any kind (public profile, hashtag, or otherwise)
- **Threads scraping**
- **LinkedIn scraping** (deferred indefinitely — anti-scrape is too aggressive)
- **Vision-LLM flyer parsing** of image-only event posts
- **Generic GLC / agency website scraping** beyond the 14 tracked + existing `govagency.py`
- **Auto-discovery** of new organisers
- **Sunday digest email**
- **"People you know are going" / RSVP overlay**
- **Topic filter UI changes** beyond what already exists (filters are configured in YAML for now)
- **"Submit missed event" feature** for Aiman to backfill
- **Disposable accounts / logged-in scraping** of any social network — never built

## Resolved during eng review

- **Existing govt coverage audit (resolved):** `govagency.py` already covers MDEC, HRD Corp, NACSA, INSKEN, SME Corp, MATRADE, MPC, MIMOS, SC, BNM, Bursa, KUSKOP, KESUMA. Missing 5 from the wedge list (MCMC, MITI, SKM, MRANTI, CSM). `venues.py` covers KLCC and MITEC; missing WTC KL. Commit 4 fills these.
- **Dedup key (resolved):** drop `source_platform` from `Event.generate_id`. Same event from two platforms now collides at the DB layer.
- **Title normalisation (resolved):** conservative — lowercase + strip punctuation + collapse whitespace. Do not strip year suffixes.
- **Time bucket (resolved):** dedup on date, not hour. A 7pm → 7:30pm change does not create a dupe.
- **Source health check (resolved):** WARN log when a source returns 0 events for 2 consecutive runs. No alerting infra in wedge.
- **Dead FB code in `social.py` (resolved):** delete it. YouTube RSS portion stays.

## Concrete next step

Build commit 1 (timezone normalisation + dedup fix + Solana regression test). Each subsequent commit ships independently.

---

## Wedge shipped — final state (2026-05-27)

The plan started as 4 commits. Reality required more — every probe surfaced bugs in pre-existing scrapers that the original eng review didn't anticipate. Final shipped state:

### Bug fixes that landed in the wedge
1. **Timezone + dedup fix** (commit 1) — `to_myt_naive` chokepoint, normalised dedup key drops `source_platform` so cross-platform events collide. Solana Network State no longer duplicated.
2. **Filter config refresh** (commit 2) — 6 → 10 topics. API reads from YAML. Frontend reads colours from API. Conservative word-boundary keyword matching (no more "AI" matching inside "Français").
3. **Venue date parser rewrite** — MITEC `_parse_mitec_date` had no cross-month regex. MyARTTE 2026 (`30 SEPT - 2 OCT`) was landing as `Oct 26 → Oct 2`. Rewrote with sanity guard (end ≥ start).
4. **`venues.py` cleanup** — Strategy 3 (Eventbrite-search-tagged-as-Venue) deleted. Pisco Bar parties no longer appear as KLCC events.
5. **Eventsize rewrite** — JSON-LD dates were garbage on a third of events. Switched to listing-page card-text parsing (option A). Search-by-keyword adds events the location-only URL hides. Foreign venue filter strengthened (Cyrillic / Lagos / Manila / non-KL Malaysian states).
6. **Hover tooltip** — `position: fixed`, z-index 10000, source label instead of categories.
7. **Multi-day event rendering fix** — only add +1 day to FullCalendar end for all-day events, not timed ones.
8. **Old DB cleanup** — re-categorised 144 stale rows; dropped 3 backwards-date events; dropped 21 stale hardcoded KLCC rows; dropped foreign-venue leaks.

### New scrapers added beyond the original wedge
1. **`backend/scrapers/orgs/insken.py`** — direct parse of insken.gov.my/pendaftaran/, 9 events visible
2. **`backend/scrapers/orgs/kuskop.py`** — direct parse of kuskop.gov.my carousel widget
3. **`backend/scrapers/fb_wall.py`** — Playwright-rendered FB Page walls with bilingual (English + Malay) event-keyword heuristic. Low yield because agencies have largely abandoned the FB Events tab, but kept as a fallback layer.
4. **`backend/scrapers/instagram/`** — pluggable backend (Apify default, HikerAPI alternative, Disabled fallback) + vision-LLM flyer extractor (Gemini default, OpenAI alternative, regex-only fallback). Caught the May 19 ASB Hive Roundtable event you screenshotted, end-to-end.

### Decisions deferred to medium scope
- KLCC Convention Centre proper scrape (their site requires JS; the hardcoded list was removed when it went stale)
- LinkedIn entirely (anti-scrape too aggressive)
- Threads (probably scrapable via Apify but profiles less event-relevant)
- Per-organiser scrapers for the remaining 14 agencies (effort vs. yield TBD)
- "Submit a missed event" UI (manual escape hatch)

### Test coverage at wedge close
- 109 tests passing
- All core date / dedup / filter / categorisation logic covered
- Live integration with Apify confirmed: ASB Hive May 19 event extracted end-to-end

### Architecture decisions worth remembering
- **Three-layer fallback**: per-agency website (best signal) → FB Wall (fallback) → IG via paid API (third fallback). All run, dedup happens at the orchestrator's `Event.generate_id` step (title + date only).
- **Curated sources bypass topic gate**: events from `venues`, `govagency`, `insken`, `kuskop`, `instagram` are kept even if their title doesn't hit a topic keyword. Open platforms (Eventbrite/Meetup/Luma) still need a topic match.
- **Per-org scrapers carry their own out-of-region filter** via `backend/scrapers/orgs/_geo.py`. INSKEN runs Sarawak/Pahang programs, KUSKOP runs Penang programs — all dropped at scraper time.
- **Provider-agnostic IG backend** means we can switch from Apify to HikerAPI by changing one env var; no code changes.
