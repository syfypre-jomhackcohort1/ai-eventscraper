"""FastAPI application entry point."""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env file BEFORE importing anything that reads env vars.
# python-dotenv silently does nothing if the file doesn't exist.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.database import init_db
from backend.api import events
from backend.scheduler import start_scheduler, stop_scheduler

# Quiet down httpx INFO-level request logs - they include full URLs with
# query string tokens. WARNING+ still surface failures we care about.
logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting KV Events Agent...")
    init_db()
    start_scheduler()

    # Run initial scrape in background if DB is empty
    import threading
    from backend.database import SessionLocal, Event
    db = SessionLocal()
    count = db.query(Event).count()
    db.close()
    if count == 0:
        logger.info("Database empty — running initial scrape in background...")
        from backend.orchestrator import run_scrape
        threading.Thread(target=run_scrape, daemon=True).start()

    yield
    # Shutdown
    stop_scheduler()
    logger.info("KV Events Agent stopped")


app = FastAPI(
    title="KV Events Discovery Agent",
    description="Klang Valley & Online Tech/Business Events Calendar",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(events.router, prefix="/api", tags=["events"])


@app.api_route("/", methods=["GET", "HEAD"])
def root():
    """Serve frontend index.html if it was built into static/, otherwise
    return a JSON sign-of-life. HEAD is supported because Render's free-
    tier health checks use HEAD requests; without it we'd see noisy 405s
    in the logs.
    """
    static_dir = Path(__file__).parent.parent / "static"
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {
        "message": "AI Eventscraper API",
        "version": "1.0.0",
        "note": (
            "Frontend not found in static/ - "
            "run 'cd frontend && npm run build' or check the Render build log."
        ),
    }


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "healthy"}


# Serve static frontend files (built React app) — must be after API routes
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # Catch-all for SPA routing — serve index.html for non-API, non-asset routes
    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        """Serve the SPA for any non-API route. Defends against missing
        index.html (e.g. if the frontend build silently failed) by falling
        back to JSON."""
        file_path = static_dir / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {
            "message": "AI Eventscraper API",
            "note": "Frontend not built. API endpoints under /api/ still work.",
        }
else:
    logger.warning(
        "static/ directory not found - frontend won't be served. "
        "Build it with: cd frontend && npm install && npm run build"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)