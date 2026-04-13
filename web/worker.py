"""
Background encoding worker using ThreadPoolExecutor.
"""

from __future__ import annotations

import io
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from core.database import open_memory_db, get_all_layers
from core.pipeline import run_pipeline
from .job_store import Job, JobState, JobStore

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="infillcode-worker")


def _run_job(job: Job, gcode_bytes: bytes, job_store: JobStore) -> None:
    job.state = JobState.RUNNING
    job.started_at = time.time()
    job_store.update(job)

    try:
        gcode_text = gcode_bytes.decode("utf-8", errors="replace")
        conn = open_memory_db()

        result = run_pipeline(
            gcode_text=gcode_text,
            filename=job.filename,
            db_conn=conn,
        )

        # Serialize DB to bytes
        db_buf = io.BytesIO()
        import sqlite3
        mem_path = ":memory:"
        # Dump memory DB via iterdump
        dump_lines = list(conn.iterdump())
        db_sql = "\n".join(dump_lines)
        db_bytes = db_sql.encode()

        # Collect layer stats
        layers_rows = get_all_layers(conn, result.file_id)
        layer_stats = [
            {
                "layer_idx": r["layer_idx"],
                "z_height_mm": r["z_height_mm"],
                "line_count": r["line_count"],
                "encoded": bool(r["encoded"]),
                "skip_reason": r["skip_reason"],
                "cumulative_e_mm": r["cumulative_e_mm"],
            }
            for r in layers_rows
        ]

        job.modified_gcode = result.modified_gcode.encode("utf-8")
        job.db_bytes = db_bytes
        job.total_layers = result.total_layers
        job.encoded_count = result.encoded_count
        job.skipped_count = result.skipped_count
        job.nominal_spacing_mm = result.nominal_spacing_mm
        job.file_id = result.file_id
        job.layer_stats = layer_stats
        job.state = JobState.DONE

    except Exception as exc:
        job.state = JobState.FAILED
        job.error = traceback.format_exc()

    finally:
        job.finished_at = time.time()
        job_store.update(job)


def submit_job(job: Job, gcode_bytes: bytes, job_store: JobStore) -> None:
    """Submit *job* for background processing."""
    _executor.submit(_run_job, job, gcode_bytes, job_store)
