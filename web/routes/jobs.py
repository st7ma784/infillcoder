"""
GET /api/jobs/{id}        — job status + layer stats
GET /api/jobs/{id}/gcode  — download modified GCode
GET /api/jobs/{id}/db     — download SQLite dump
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter()


def _get_job_or_404(request: Request, job_id: str):
    job = request.app.state.job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found.")
    return job


@router.get("/jobs/{job_id}")
async def job_status(job_id: str, request: Request):
    job = _get_job_or_404(request, job_id)
    return JSONResponse(job.to_status_dict())


@router.get("/jobs/{job_id}/gcode")
async def download_gcode(job_id: str, request: Request):
    job = _get_job_or_404(request, job_id)
    if job.state != "done":
        raise HTTPException(status_code=409, detail=f"Job is {job.state}, not done.")
    if not job.modified_gcode:
        raise HTTPException(status_code=500, detail="GCode not available.")

    safe_name = job.filename.replace(" ", "_")
    stem = safe_name.rsplit(".", 1)[0] if "." in safe_name else safe_name
    download_name = f"{stem}_infillcode.gcode"

    return Response(
        content=job.modified_gcode,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


@router.get("/jobs/{job_id}/db")
async def download_db(job_id: str, request: Request):
    job = _get_job_or_404(request, job_id)
    if job.state != "done":
        raise HTTPException(status_code=409, detail=f"Job is {job.state}, not done.")
    if not job.db_bytes:
        raise HTTPException(status_code=500, detail="Database not available.")

    safe_name = job.filename.replace(" ", "_")
    stem = safe_name.rsplit(".", 1)[0] if "." in safe_name else safe_name
    download_name = f"{stem}_infillcode.sql"

    return Response(
        content=job.db_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )
