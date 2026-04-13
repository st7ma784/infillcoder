"""
In-memory job registry for background encoding jobs.

Job states: pending → running → done | failed
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
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
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Job] = {}

    def create(self, filename: str) -> Job:
        job_id = str(uuid.uuid4())
        job = Job(job_id=job_id, filename=filename)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
