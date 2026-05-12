"""
Tests for persistent job store.
"""

import tempfile
from pathlib import Path

import pytest

from web.job_store import Job, JobState, JobStore


@pytest.fixture
def temp_data_dir():
    """Create a temporary directory for job data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_job_store_create_and_get(temp_data_dir):
    """Test creating and retrieving a job."""
    store = JobStore(data_dir=temp_data_dir)

    # Create a job
    job = store.create("test.gcode")
    assert job.job_id is not None
    assert job.filename == "test.gcode"
    assert job.state == JobState.PENDING

    # Retrieve the job
    retrieved = store.get(job.job_id)
    assert retrieved is not None
    assert retrieved.job_id == job.job_id
    assert retrieved.filename == "test.gcode"


def test_job_store_persistence(temp_data_dir):
    """Test that jobs persist across store instances."""
    # Create a job in first store instance
    store1 = JobStore(data_dir=temp_data_dir)
    job = store1.create("test.gcode")
    job_id = job.job_id

    # Create a new store instance (simulating restart)
    store2 = JobStore(data_dir=temp_data_dir)

    # Job should be retrievable from new instance
    retrieved = store2.get(job_id)
    assert retrieved is not None
    assert retrieved.job_id == job_id
    assert retrieved.filename == "test.gcode"


def test_job_store_update(temp_data_dir):
    """Test updating job state and stats."""
    store = JobStore(data_dir=temp_data_dir)
    job = store.create("test.gcode")

    # Update job state and stats
    job.state = JobState.RUNNING
    job.total_layers = 100
    job.encoded_count = 50
    job.layer_stats = [{"layer_idx": 0, "encoded": True}]
    store.update(job)

    # Verify updates persisted
    retrieved = store.get(job.job_id)
    assert retrieved.state == JobState.RUNNING
    assert retrieved.total_layers == 100
    assert retrieved.encoded_count == 50
    assert len(retrieved.layer_stats) == 1


def test_job_store_binary_data(temp_data_dir):
    """Test storing and retrieving binary gcode and db data."""
    store = JobStore(data_dir=temp_data_dir)
    job = store.create("test.gcode")

    # Add binary data
    job.modified_gcode = b"G28\nG29\n"
    job.db_bytes = b"SELECT * FROM jobs"
    job.state = JobState.DONE
    store.update(job)

    # Verify binary data persisted
    retrieved = store.get(job.job_id)
    assert retrieved.modified_gcode == b"G28\nG29\n"
    assert retrieved.db_bytes == b"SELECT * FROM jobs"


def test_job_store_cleanup_old_jobs(temp_data_dir):
    """Test cleanup of old completed jobs."""
    import time

    store = JobStore(data_dir=temp_data_dir)

    # Create a job and mark it done
    job = store.create("old_job.gcode")
    job.state = JobState.DONE
    job.created_at = time.time() - (8 * 86400)  # 8 days ago
    store.update(job)

    job_id = job.job_id

    # Cleanup jobs older than 7 days
    store.cleanup_old_jobs(keep_days=7)

    # Job should be deleted
    retrieved = store.get(job_id)
    assert retrieved is None


def test_job_store_to_status_dict(temp_data_dir):
    """Test Job.to_status_dict() method."""
    store = JobStore(data_dir=temp_data_dir)
    job = store.create("test.gcode")
    job.state = JobState.DONE
    job.total_layers = 10
    job.encoded_count = 5

    status = job.to_status_dict()
    assert status["job_id"] == job.job_id
    assert status["filename"] == "test.gcode"
    assert status["state"] == JobState.DONE
    assert status["total_layers"] == 10
    assert status["encoded_count"] == 5
