"""
Persistent job registry for background encoding jobs with SQLite backend.

Job states: pending → running → done | failed

Jobs are stored in SQLite for persistence across restarts. Binary data (gcode, db)
is stored as files on disk in the jobs directory.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE    = "done"
    FAILED  = "failed"


@dataclass
class Job:
    job_id: str
    filename: str
    state: JobState = JobState.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None

    # Results (populated on completion)
    modified_gcode: Optional[bytes] = None
    db_bytes: Optional[bytes] = None

    # Stats
    total_layers: int = 0
    encoded_count: int = 0
    skipped_count: int = 0
    nominal_spacing_mm: float = 0.0
    file_id: Optional[int] = None

    # Per-layer info (list of dicts) — populated from DB rows
    layer_stats: list = field(default_factory=list)

    def to_status_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "filename": self.filename,
            "state": self.state,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "total_layers": self.total_layers,
            "encoded_count": self.encoded_count,
            "skipped_count": self.skipped_count,
            "nominal_spacing_mm": self.nominal_spacing_mm,
            "file_id": self.file_id,
            "layers": self.layer_stats,
        }


class JobStore:
    """Persistent job storage with SQLite backend."""

    def __init__(self, data_dir: Optional[Path | str] = None) -> None:
        """
        Initialize job store.

        Args:
            data_dir: Directory for job storage. Defaults to ./data/jobs.
                      Create if missing.
        """
        self._lock = threading.Lock()
        self._in_memory_cache: Dict[str, Job] = {}

        # Setup data directory
        if data_dir is None:
            self.data_dir = Path("data/jobs")
        else:
            self.data_dir = Path(data_dir)

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "jobs.db"

        # Initialize database
        self._init_db()

    def _init_db(self) -> None:
        """Create jobs table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    error TEXT,
                    total_layers INTEGER DEFAULT 0,
                    encoded_count INTEGER DEFAULT 0,
                    skipped_count INTEGER DEFAULT 0,
                    nominal_spacing_mm REAL DEFAULT 0.0,
                    file_id INTEGER,
                    layer_stats TEXT DEFAULT '[]'
                )
            """)
            conn.commit()

    def _to_db_row(self, job: Job) -> dict:
        """Convert Job to database row."""
        return {
            "job_id": job.job_id,
            "filename": job.filename,
            "state": job.state.value,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "error": job.error,
            "total_layers": job.total_layers,
            "encoded_count": job.encoded_count,
            "skipped_count": job.skipped_count,
            "nominal_spacing_mm": job.nominal_spacing_mm,
            "file_id": job.file_id,
            "layer_stats": json.dumps(job.layer_stats),
        }

    def _from_db_row(self, row: sqlite3.Row) -> Job:
        """Convert database row to Job."""
        return Job(
            job_id=row["job_id"],
            filename=row["filename"],
            state=JobState(row["state"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error=row["error"],
            total_layers=row["total_layers"],
            encoded_count=row["encoded_count"],
            skipped_count=row["skipped_count"],
            nominal_spacing_mm=row["nominal_spacing_mm"],
            file_id=row["file_id"],
            layer_stats=json.loads(row["layer_stats"] or "[]"),
            modified_gcode=self._load_gcode_file(row["job_id"]),
            db_bytes=self._load_db_file(row["job_id"]),
        )

    def _gcode_path(self, job_id: str) -> Path:
        """Return path to gcode file for job."""
        return self.data_dir / f"{job_id}.gcode"

    def _db_path(self, job_id: str) -> Path:
        """Return path to db file for job."""
        return self.data_dir / f"{job_id}.sql"

    def _save_gcode_file(self, job_id: str, data: bytes) -> None:
        """Save gcode data to disk."""
        if data:
            self._gcode_path(job_id).write_bytes(data)

    def _save_db_file(self, job_id: str, data: bytes) -> None:
        """Save db data to disk."""
        if data:
            self._db_path(job_id).write_bytes(data)

    def _load_gcode_file(self, job_id: str) -> Optional[bytes]:
        """Load gcode data from disk."""
        path = self._gcode_path(job_id)
        return path.read_bytes() if path.exists() else None

    def _load_db_file(self, job_id: str) -> Optional[bytes]:
        """Load db data from disk."""
        path = self._db_path(job_id)
        return path.read_bytes() if path.exists() else None

    def _cleanup_job_files(self, job_id: str) -> None:
        """Delete gcode and db files for job."""
        self._gcode_path(job_id).unlink(missing_ok=True)
        self._db_path(job_id).unlink(missing_ok=True)

    def create(self, filename: str) -> Job:
        """Create a new job and save to database."""
        job_id = str(uuid.uuid4())
        job = Job(job_id=job_id, filename=filename)

        with self._lock:
            row = self._to_db_row(job)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO jobs (
                        job_id, filename, state, created_at, started_at,
                        finished_at, error, total_layers, encoded_count,
                        skipped_count, nominal_spacing_mm, file_id, layer_stats
                    ) VALUES (
                        :job_id, :filename, :state, :created_at, :started_at,
                        :finished_at, :error, :total_layers, :encoded_count,
                        :skipped_count, :nominal_spacing_mm, :file_id, :layer_stats
                    )
                """, row)
                conn.commit()

            self._in_memory_cache[job_id] = job

        return job

    def get(self, job_id: str) -> Optional[Job]:
        """Get job by ID from cache or database."""
        with self._lock:
            # Check in-memory cache first
            if job_id in self._in_memory_cache:
                return self._in_memory_cache[job_id]

            # Load from database
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
                ).fetchone()

            if row:
                job = self._from_db_row(row)
                self._in_memory_cache[job_id] = job
                return job

            return None

    def update(self, job: Job) -> None:
        """Update job in database and cache."""
        with self._lock:
            self._in_memory_cache[job.job_id] = job

            # Save binary data to files
            self._save_gcode_file(job.job_id, job.modified_gcode)
            self._save_db_file(job.job_id, job.db_bytes)

            # Update database row (exclude binary data)
            row = self._to_db_row(job)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE jobs SET
                        filename = :filename,
                        state = :state,
                        created_at = :created_at,
                        started_at = :started_at,
                        finished_at = :finished_at,
                        error = :error,
                        total_layers = :total_layers,
                        encoded_count = :encoded_count,
                        skipped_count = :skipped_count,
                        nominal_spacing_mm = :nominal_spacing_mm,
                        file_id = :file_id,
                        layer_stats = :layer_stats
                    WHERE job_id = :job_id
                """, row)
                conn.commit()

    def cleanup_old_jobs(self, keep_days: int = 7) -> None:
        """Delete jobs older than keep_days. Useful for maintenance."""
        cutoff_time = time.time() - (keep_days * 86400)

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT job_id FROM jobs WHERE created_at < ? AND state IN (?, ?)",
                    (cutoff_time, JobState.DONE.value, JobState.FAILED.value),
                ).fetchall()

                for (job_id,) in rows:
                    self._cleanup_job_files(job_id)
                    self._in_memory_cache.pop(job_id, None)

            # Delete from database
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM jobs WHERE created_at < ? AND state IN (?, ?)",
                    (cutoff_time, JobState.DONE.value, JobState.FAILED.value),
                )
                conn.commit()
