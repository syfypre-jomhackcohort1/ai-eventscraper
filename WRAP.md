# Wrap-up & Handoff

End-of-session state of the KV Events Agent project. This file is for future-you (or whoever picks this up) to know what's done, what's deferred, and how to push safely.

## Status

- **109 tests passing**
- **9 sources live**: Eventbrite, Meetup, Luma, Eventsize, Peatix, MITEC venue, INSKEN, KUSKOP, Instagram (via Apify)
- **Plus 2 fallback layers**: Facebook Page wall (Playwright), GovAgency (generic)
- **Universal geo guard** drops foreign venues from every source regardless of the source's own filter
- **Universal sanity guard** drops events with `end < start`
- **Curated sources** (venues, govagency, insken, kuskop, instagram) bypass the topic gate; open platforms still need a topic match

## Pre-push checklist

Run these before `git init && git push`:

```powershell
# 1. Confirm no API tokens leaked into source
grep -rE "apify_api|sk-[A-Za-z0-9]{20}|AIza[A-Za-z0-9]{20}" --include="*.py" --include="*.yaml" --include="*.md" .

# 2. Tests pass
python -m pytest tests/ -q

# 3. Server boots clean
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
# (then Ctrl+C)

# 4. Init git, verify .env is excluded
git init
git add -A
git status | findstr ".env"
# Expected: only ".env.example" appears, NOT ".env"
```

If `.env` shows up in `git status`, STOP. Recheck `.gitignore`.

## Optional but smart: rotate the Apify token before pushing

The Apify token shared during the build session was transmitted in plaintext
through chat. It's not in any committed file but to eliminate even theoretical
risk:

1. Go to https://console.apify.com/account/integrations
2. Revoke the existing token
3. Generate a new one
4. Update `.env` (locally) and Render's environment dashboard (production)

## Deploying to Render

`render.yaml` is wired up. Set these env vars in Render's dashboard (Settings → Environment):

| Key | Value | Required? |
|---|---|---|
| `IG_BACKEND` | `apify` | Optional - omit to disable IG |
| `APIFY_TOKEN` | (your new token) | If `IG_BACKEND=apify` |
| `LLM_PROVIDER` | `gemini` | Optional - omit to disable vision-LLM |
| `GEMINI_API_KEY` | (your key) | If `LLM_PROVIDER=gemini` |

Build command already pre-installs Playwright Chromium with system deps for the FB Wall scraper.

**Render free tier note**: Playwright + Chromium pushes the container size up. If the free tier rejects the build, either remove FB Wall from the scrapers list (set `fb_pages: []` in `config/sources.yaml`) or upgrade to the starter plan.

## What's deferred

These didn't ship in this session and live in `DESIGN.md` as medium-scope work:

- **KLCC Convention Centre native scrape** - their site is a JS SPA; we removed the stale hardcoded list to stop lying to Aiman. Fix needs Playwright + per-event website cross-validation.
- **LinkedIn** - skipped indefinitely. Anti-scrape too aggressive; also Aiman doesn't browse LinkedIn for events.
- **Threads** - probably scrapable via Apify (different actor) but not high yield based on current usage patterns.
- **Per-organisation scrapers for the remaining 14 agencies** - INSKEN and KUSKOP are the templates. Each one is ~30 min of probe + parser + tests. ROI varies wildly per agency.
- **"Submit a missed event" UI** - manual escape hatch for events that slip through all 3 layers. Useful but not built.
- **Vision-LLM flyer extraction at scale** - the wiring is there (`flyer_extractor.py` with Gemini + OpenAI providers), but `LLM_PROVIDER=disabled` by default. Set `LLM_PROVIDER=gemini` and add `GEMINI_API_KEY` to enable. Cost: ~$0.0001 per flyer image.

## Architecture decisions worth remembering

These came up multiple times. Future-you will save time if you don't re-litigate them.

1. **Three-layer fallback for IG/FB events**: per-agency website (best signal) → FB Wall via Playwright (fallback) → IG via paid API (third fallback). All three run, dedup happens at the orchestrator's `Event.generate_id` step (title + date only — source is intentionally NOT in the hash so the same event from different platforms collides).

2. **Curated sources bypass the topic gate**. Trade shows at MITEC, agency programmes at INSKEN, etc. don't have to match a topic keyword to be saved. Open platforms (Eventbrite/Meetup/Luma) still need a topic match.

3. **Word-boundary keyword matching for short tokens**. Keywords ≤ 3 chars (AI, ML, VC) match on `\bX\b` not substring; otherwise "AI" matches inside "Français".

4. **Eventsize JSON-LD is unreliable** (end < start on a third of events). We parse the visible card text and ignore JSON-LD dates entirely.

5. **Provider-agnostic IG backend** means we can swap from Apify to HikerAPI by changing one env var. Don't undo this — the lock-in to one provider is a real liability when Meta changes its anti-scrape rules.

6. **`.env` over hardcoded secrets**. `python-dotenv` loads at app startup. Never commit `.env`. `.env.example` shows the shape with empty values.

## Quick commands

```powershell
# Run tests
python -m pytest tests/ -q

# Run a manual scrape
python -m backend.orchestrator

# Start the server (auto-reload)
python -m uvicorn backend.main:app --reload

# Rebuild frontend
cd frontend && npm run build
```

## Files I'd hand back to a developer

- `README.md` - public-facing docs
- `DESIGN.md` - product reasoning + architecture decisions
- `.env.example` - all configurable env vars with comments
- `config/filters.yaml` - topics + keywords + colors (single source of truth)
- `config/sources.yaml` - per-scraper config + tracked profile lists
- `backend/scrapers/orgs/` - the per-agency scraper template (start here when adding a new agency)
- `backend/scrapers/instagram/` - the provider-agnostic IG backend pattern (start here when adding a new platform)

That's it. Good luck shipping.
