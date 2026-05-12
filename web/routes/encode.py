"""
POST /api/encode — accept a GCode file and queue it for encoding.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Configuration
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
MIN_FILE_SIZE = 100  # 100 bytes (minimum valid GCode)

router = APIRouter()


def _validate_gcode_content(content: bytes) -> None:
    """
    Validate that content appears to be valid GCode.
    
    Raises:
        HTTPException: If validation fails
    """
    # Decode to check for valid UTF-8
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"File is not valid text: {e}",
        )
    
    # Check for basic GCode patterns
    has_g_command = any(line.strip().startswith("G") for line in text.split("\n"))
    has_m_command = any(line.strip().startswith("M") for line in text.split("\n"))
    
    if not (has_g_command or has_m_command):
        raise HTTPException(
            status_code=400,
            detail="File does not appear to be valid GCode (no G or M commands found)",
        )


@router.post("/encode")
async def encode(request: Request, file: UploadFile = File(...)):
    """
    Queue a GCode file for encoding.
    
    Parameters:
        file: GCode file to encode
        
    Returns:
        job_id: Unique job identifier for tracking progress
        
    Raises:
        400: Invalid file or file too large
        202: Job accepted (Accepted)
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")
    
    # Check filename has reasonable length
    if len(file.filename) > 255:
        raise HTTPException(status_code=400, detail="Filename too long (max 255 chars).")
    
    # Check file size before reading
    if file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_FILE_SIZE / 1024 / 1024:.0f} MB).",
        )

    gcode_bytes = await file.read()
    
    if not gcode_bytes:
        raise HTTPException(status_code=400, detail="Empty file.")
    
    if len(gcode_bytes) < MIN_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too small (min {MIN_FILE_SIZE} bytes).",
        )
    
    if len(gcode_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_FILE_SIZE / 1024 / 1024:.0f} MB).",
        )

    # Validate GCode content
    _validate_gcode_content(gcode_bytes)

    job_store = request.app.state.job_store
    job = job_store.create(file.filename)
    logger.info("Created encoding job %s for file %s", job.job_id, file.filename)

    from web.worker import submit_job
    submit_job(job, gcode_bytes, job_store)

    return JSONResponse({"job_id": job.job_id}, status_code=202)

