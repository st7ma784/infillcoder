"""
GET /api/jobs/{id}        — job status + layer stats
GET /api/jobs/{id}/gcode  — download modified GCode
GET /api/jobs/{id}/db     — download SQLite dump
"""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter()

# UUID v4 regex pattern
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE
)


def _validate_job_id(job_id: str) -> None:
    """
    Validate job_id format (must be valid UUID).
    
    Raises:
        HTTPException: If job_id is invalid
    """
    if not UUID_PATTERN.match(job_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid job_id format (must be UUID)",
        )


def _get_job_or_404(request: Request, job_id: str):
    _validate_job_id(job_id)
    job = request.app.state.job_store.get(job_id)
    if job is None:
        logger.warning("Job not found: %s", job_id)
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    return job


@router.get("/jobs/{job_id}")
async def job_status(job_id: str, request: Request):
    """Get job status and progress."""
    job = _get_job_or_404(request, job_id)
    logger.info("Fetching status for job %s", job_id)
    return JSONResponse(job.to_status_dict())


@router.get("/jobs/{job_id}/gcode")
async def download_gcode(job_id: str, request: Request):
    """Download modified GCode if job is complete."""
    job = _get_job_or_404(request, job_id)
    
    if job.state != "done":
        logger.warning("Job %s requested but not done (state=%s)", job_id, job.state)
        raise HTTPException(status_code=409, detail=f"Job is {job.state}, not done.")
    
    if not job.modified_gcode:
        logger.error("Job %s is done but no gcode available", job_id)
        raise HTTPException(status_code=500, detail="GCode not available.")

    safe_name = job.filename.replace(" ", "_")
    stem = safe_name.rsplit(".", 1)[0] if "." in safe_name else safe_name
    download_name = f"{stem}_infillcode.gcode"

    logger.info("Downloading gcode for job %s (file: %s)", job_id, download_name)
    return Response(
        content=job.modified_gcode,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


@router.get("/jobs/{job_id}/db")
async def download_db(job_id: str, request: Request):
    """Download SQLite database dump if job is complete."""
    job = _get_job_or_404(request, job_id)
    
    if job.state != "done":
        logger.warning("Job %s db requested but not done (state=%s)", job_id, job.state)
        raise HTTPException(status_code=409, detail=f"Job is {job.state}, not done.")
    
    if not job.db_bytes:
        logger.error("Job %s is done but no db available", job_id)
        raise HTTPException(status_code=500, detail="Database not available.")

    safe_name = job.filename.replace(" ", "_")
    stem = safe_name.rsplit(".", 1)[0] if "." in safe_name else safe_name
    download_name = f"{stem}_infillcode.sql"

    logger.info("Downloading db for job %s (file: %s)", job_id, download_name)
    return Response(
        content=job.db_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )
