"""
InfillCode FastAPI application factory.

Usage:
    uvicorn web.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .job_store import JobStore
from .routes.encode import router as encode_router
from .routes.jobs import router as jobs_router
from .worker import start_worker, shutdown_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app startup and shutdown."""
    # Startup
    start_worker()
    yield
    # Shutdown
    shutdown_worker()


def create_app(job_data_dir: str | Path | None = None) -> FastAPI:
    application = FastAPI(
        title="InfillCode",
        description="GCode layer fingerprinting via infill line spacing modulation",
        version="1.0.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
        max_age=600,
    )

    # Shared state — with persistent job storage
    application.state.job_store = JobStore(data_dir=job_data_dir)
    # Optional: cleanup jobs older than 7 days on startup
    application.state.job_store.cleanup_old_jobs(keep_days=7)

    # Health check endpoint
    @application.get("/health")
    async def health_check():
        """Health check endpoint for monitoring."""
        return JSONResponse({
            "status": "ok",
            "version": "1.0.0",
        })

    # API routes
    application.include_router(encode_router, prefix="/api")
    application.include_router(jobs_router, prefix="/api")

    # Static frontend
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        application.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return application


app = create_app()
