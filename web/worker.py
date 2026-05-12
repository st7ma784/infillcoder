"""
Background encoding worker using queue-based job processing.

Jobs are processed serially through a queue to prevent database concurrency issues.
"""

from __future__ import annotations

import io
import logging
import queue
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from core.database import open_memory_db, get_all_layers
from core.pipeline import run_pipeline
from .job_store import Job, JobState, JobStore

logger = logging.getLogger(__name__)

# Queue for serializing encoding jobs
_job_queue: queue.Queue = queue.Queue()
_executor: Optional[ThreadPoolExecutor] = None
_executor_shutdown = False


def _worker_thread() -> None:
    """Process jobs from queue one at a time."""
    global _executor_shutdown
    while not _executor_shutdown:
        try:
            job, gcode_bytes, job_store = _job_queue.get(timeout=1.0)
            _run_job(job, gcode_bytes, job_store)
        except queue.Empty:
            continue
        except Exception as e:
            logger.exception("Unexpected error in worker thread: %s", e)


def _run_job(job: Job, gcode_bytes: bytes, job_store: JobStore) -> None:
    """Run a single encoding job."""
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
        logger.info("Job %s completed: %d layers, %d encoded", job.job_id, job.total_layers, job.encoded_count)

    except Exception as exc:
        job.state = JobState.FAILED
        job.error = traceback.format_exc()
        logger.error("Job %s failed: %s", job.job_id, job.error)

    finally:
        job.finished_at = time.time()
        job_store.update(job)


def submit_job(job: Job, gcode_bytes: bytes, job_store: JobStore) -> None:
    """Submit job for background processing via queue."""
    _job_queue.put((job, gcode_bytes, job_store))
    logger.info("Job %s queued for encoding", job.job_id)


def start_worker() -> None:
    """Start the worker thread (call once at app startup)."""
    global _executor, _executor_shutdown
    _executor_shutdown = False
    
    # Create new executor if needed (e.g., after shutdown or on first call)
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="infillcode-worker")
    
    _executor.submit(_worker_thread)


def shutdown_worker(timeout: float = 30.0) -> None:
    """Gracefully shutdown the worker thread."""
    global _executor, _executor_shutdown
    _executor_shutdown = True
    
    if _executor is None:
        return
    
    try:
        # ThreadPoolExecutor.shutdown() doesn't support timeout in Python 3.13
        # Wait for queue to empty within timeout
        start_time = time.time()
        while not _job_queue.empty() and (time.time() - start_time) < timeout:
            time.sleep(0.1)
        
        _executor.shutdown(wait=True)
        _executor = None  # Reset for next startup
        logger.info("Worker thread shutdown gracefully")
    except Exception as e:
        logger.error("Error during worker shutdown: %s", e)
