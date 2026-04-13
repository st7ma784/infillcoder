"""
InfillCode FastAPI application factory.

Usage:
    uvicorn web.main:app --reload
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .job_store import JobStore
from .routes.encode import router as encode_router
from .routes.jobs import router as jobs_router


def create_app() -> FastAPI:
    application = FastAPI(
        title="InfillCode",
        description="GCode layer fingerprinting via infill line spacing modulation",
        version="1.0.0",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Shared state
    application.state.job_store = JobStore()

    # API routes
    application.include_router(encode_router, prefix="/api")
    application.include_router(jobs_router, prefix="/api")

    # Static frontend
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        application.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return application


app = create_app()
