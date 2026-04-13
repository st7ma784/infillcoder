"""
POST /api/encode — accept a GCode file and queue it for encoding.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/encode")
async def encode(request: Request, file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    gcode_bytes = await file.read()
    if not gcode_bytes:
        raise HTTPException(status_code=400, detail="Empty file.")

    job_store = request.app.state.job_store
    job = job_store.create(file.filename)

    from web.worker import submit_job
    submit_job(job, gcode_bytes, job_store)

    return JSONResponse({"job_id": job.job_id}, status_code=202)
