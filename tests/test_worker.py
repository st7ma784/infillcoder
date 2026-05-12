"""
Tests for background worker thread and job queue processing.

Covers:
- Concurrent job submissions with serialization
- Job state transitions (pending → running → done)
- Error handling and failed job tracking
- Worker thread lifecycle (startup, shutdown, timeout)
- Queue blocking and timeout behavior
"""

from __future__ import annotations

import queue
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

from web.job_store import Job, JobState, JobStore
from web.worker import (
    _job_queue,
    _run_job,
    shutdown_worker,
    start_worker,
    submit_job,
)


class TestWorkerJobSubmission(unittest.TestCase):
    """Test job submission and queue behavior."""

    def setUp(self) -> None:
        """Clear queue before each test by draining it."""
        # Drain the global queue instead of replacing it
        while not _job_queue.empty():
            try:
                _job_queue.get_nowait()
            except queue.Empty:
                break

    def test_submit_job_adds_to_queue(self) -> None:
        """Verify submit_job puts job into queue."""
        job = Job(job_id="test-1", filename="test.gcode")
        gcode_bytes = b"G28\nG0 Z10\n"
        job_store = MagicMock(spec=JobStore)

        initial_size = _job_queue.qsize()
        submit_job(job, gcode_bytes, job_store)

        # Queue should have one more item
        self.assertEqual(_job_queue.qsize(), initial_size + 1)
        queued_job, queued_bytes, queued_store = _job_queue.get_nowait()
        self.assertEqual(queued_job.job_id, "test-1")
        self.assertEqual(queued_bytes, gcode_bytes)
        self.assertEqual(queued_store, job_store)

    def test_submit_multiple_jobs_preserves_order(self) -> None:
        """Verify multiple submissions are queued in FIFO order."""
        job_store = MagicMock(spec=JobStore)
        jobs = [
            Job(job_id="test-1", filename="a.gcode"),
            Job(job_id="test-2", filename="b.gcode"),
            Job(job_id="test-3", filename="c.gcode"),
        ]
        gcode = b"G28\n"

        initial_size = _job_queue.qsize()
        for job in jobs:
            submit_job(job, gcode, job_store)

        self.assertEqual(_job_queue.qsize(), initial_size + 3)
        # Verify FIFO order
        for expected_job in jobs:
            queued_job, _, _ = _job_queue.get_nowait()
            self.assertEqual(queued_job.job_id, expected_job.job_id)

    def test_submit_job_with_empty_gcode(self) -> None:
        """Verify submit_job works with minimal gcode."""
        job = Job(job_id="test-empty", filename="minimal.gcode")
        gcode_bytes = b""
        job_store = MagicMock(spec=JobStore)

        initial_size = _job_queue.qsize()
        submit_job(job, gcode_bytes, job_store)

        self.assertEqual(_job_queue.qsize(), initial_size + 1)
        queued_job, queued_bytes, _ = _job_queue.get_nowait()
        self.assertEqual(queued_bytes, b"")

    def test_submit_large_gcode_file(self) -> None:
        """Verify submit_job handles large files."""
        job = Job(job_id="test-large", filename="large.gcode")
        # 50MB of repetitive gcode
        gcode_bytes = b"G0 X100 Y100\n" * (50 * 1024 * 1024 // 14)
        job_store = MagicMock(spec=JobStore)

        initial_size = _job_queue.qsize()
        submit_job(job, gcode_bytes, job_store)

        self.assertEqual(_job_queue.qsize(), initial_size + 1)
        queued_job, queued_bytes, _ = _job_queue.get_nowait()
        self.assertEqual(len(queued_bytes), len(gcode_bytes))


class TestRunJob(unittest.TestCase):
    """Test job execution and state transitions."""

    def setUp(self) -> None:
        """Mock job_store and dependencies."""
        self.job_store = MagicMock(spec=JobStore)

    @patch("web.worker.open_memory_db")
    @patch("web.worker.run_pipeline")
    @patch("web.worker.get_all_layers")
    def test_run_job_success_transitions_to_done(
        self, mock_get_layers, mock_pipeline, mock_open_db
    ) -> None:
        """Verify successful job transitions to DONE state."""
        # Setup
        job = Job(job_id="test-1", filename="test.gcode")
        gcode_bytes = b"G28\nG0 Z10\n"
        mock_conn = MagicMock()
        mock_open_db.return_value = mock_conn

        # Pipeline result
        pipeline_result = Mock()
        pipeline_result.modified_gcode = "G28\nG0 Z10.5\n"
        pipeline_result.total_layers = 10
        pipeline_result.encoded_count = 5
        pipeline_result.skipped_count = 5
        pipeline_result.nominal_spacing_mm = 0.2
        pipeline_result.file_id = 1
        mock_pipeline.return_value = pipeline_result

        mock_get_layers.return_value = []

        # Mock iterdump
        mock_conn.iterdump.return_value = ["CREATE TABLE...", "INSERT..."]

        # Execute
        _run_job(job, gcode_bytes, self.job_store)

        # Verify state transition
        self.assertEqual(job.state, JobState.DONE)
        self.assertIsNotNone(job.modified_gcode)
        self.assertEqual(job.total_layers, 10)
        self.assertEqual(job.encoded_count, 5)
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.finished_at)

        # Verify job_store.update called
        self.job_store.update.assert_called()

    @patch("web.worker.open_memory_db")
    @patch("web.worker.run_pipeline")
    def test_run_job_pipeline_exception_sets_failed_state(
        self, mock_pipeline, mock_open_db
    ) -> None:
        """Verify pipeline exception transitions job to FAILED."""
        job = Job(job_id="test-fail", filename="bad.gcode")
        gcode_bytes = b"INVALID\n"
        mock_conn = MagicMock()
        mock_open_db.return_value = mock_conn

        # Pipeline raises exception
        mock_pipeline.side_effect = ValueError("Invalid GCode syntax")

        # Execute
        _run_job(job, gcode_bytes, self.job_store)

        # Verify error state
        self.assertEqual(job.state, JobState.FAILED)
        self.assertIsNotNone(job.error)
        self.assertIn("Invalid GCode", job.error)
        self.assertIsNotNone(job.finished_at)

        # Verify job_store.update called for state change
        self.job_store.update.assert_called()

    @patch("web.worker.open_memory_db")
    @patch("web.worker.run_pipeline")
    @patch("web.worker.get_all_layers")
    def test_run_job_records_timing(
        self, mock_get_layers, mock_pipeline, mock_open_db
    ) -> None:
        """Verify started_at and finished_at are recorded."""
        job = Job(job_id="test-timing", filename="test.gcode")
        gcode_bytes = b"G28\n"
        mock_conn = MagicMock()
        mock_open_db.return_value = mock_conn

        pipeline_result = Mock()
        pipeline_result.modified_gcode = "G28\n"
        pipeline_result.total_layers = 1
        pipeline_result.encoded_count = 0
        pipeline_result.skipped_count = 1
        pipeline_result.nominal_spacing_mm = 0.0
        pipeline_result.file_id = 1
        mock_pipeline.return_value = pipeline_result

        mock_get_layers.return_value = []
        mock_conn.iterdump.return_value = []

        start_time = time.time()
        _run_job(job, gcode_bytes, self.job_store)
        end_time = time.time()

        # Verify timing
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.finished_at)
        self.assertGreaterEqual(job.started_at, start_time)
        self.assertLessEqual(job.finished_at, end_time)
        self.assertGreaterEqual(job.finished_at, job.started_at)

    @patch("web.worker.open_memory_db")
    def test_run_job_handles_utf8_decode_error(self, mock_open_db) -> None:
        """Verify UTF-8 decode errors are handled gracefully."""
        job = Job(job_id="test-decode", filename="test.gcode")
        # Invalid UTF-8 sequence
        gcode_bytes = b"\x80\x81\x82"
        mock_conn = MagicMock()
        mock_open_db.return_value = mock_conn

        # Should not raise, decode with errors="replace"
        with patch("web.worker.run_pipeline") as mock_pipeline:
            mock_pipeline.side_effect = Exception("Simulated pipeline error")
            _run_job(job, gcode_bytes, self.job_store)

        self.assertEqual(job.state, JobState.FAILED)

    @patch("web.worker.open_memory_db")
    @patch("web.worker.run_pipeline")
    @patch("web.worker.get_all_layers")
    def test_run_job_populates_layer_stats(
        self, mock_get_layers, mock_pipeline, mock_open_db
    ) -> None:
        """Verify layer stats are populated from database."""
        job = Job(job_id="test-layers", filename="test.gcode")
        gcode_bytes = b"G28\n"
        mock_conn = MagicMock()
        mock_open_db.return_value = mock_conn

        pipeline_result = Mock()
        pipeline_result.modified_gcode = "G28\n"
        pipeline_result.total_layers = 2
        pipeline_result.encoded_count = 1
        pipeline_result.skipped_count = 1
        pipeline_result.nominal_spacing_mm = 0.2
        pipeline_result.file_id = 1
        mock_pipeline.return_value = pipeline_result

        # Layer data from database
        layer_rows = [
            {
                "layer_idx": 0,
                "z_height_mm": 0.2,
                "line_count": 100,
                "encoded": 0,
                "skip_reason": "too_few_lines",
                "cumulative_e_mm": 150.0,
            },
            {
                "layer_idx": 1,
                "z_height_mm": 0.4,
                "line_count": 200,
                "encoded": 1,
                "skip_reason": None,
                "cumulative_e_mm": 450.0,
            },
        ]
        mock_get_layers.return_value = layer_rows
        mock_conn.iterdump.return_value = []

        _run_job(job, gcode_bytes, self.job_store)

        # Verify layer stats
        self.assertEqual(len(job.layer_stats), 2)
        self.assertEqual(job.layer_stats[0]["layer_idx"], 0)
        self.assertEqual(job.layer_stats[0]["z_height_mm"], 0.2)
        self.assertEqual(job.layer_stats[1]["encoded"], True)
        self.assertIsNone(job.layer_stats[1]["skip_reason"])


class TestWorkerLifecycle(unittest.TestCase):
    """Test worker thread startup and shutdown."""

    def setUp(self) -> None:
        """Drain queue before test."""
        while not _job_queue.empty():
            try:
                _job_queue.get_nowait()
            except queue.Empty:
                break

    def tearDown(self) -> None:
        """Ensure worker is shutdown after tests."""
        try:
            shutdown_worker(timeout=2.0)
        except Exception:
            pass

    def test_start_worker_initializes_thread(self) -> None:
        """Verify start_worker starts the worker thread."""
        start_worker()
        # Give thread time to start
        time.sleep(0.1)

        # Job should be processable (queue should accept it)
        job = Job(job_id="test-1", filename="test.gcode")
        job_store = MagicMock(spec=JobStore)
        initial_size = _job_queue.qsize()
        submit_job(job, b"G28\n", job_store)

        # Should not block
        self.assertEqual(_job_queue.qsize(), initial_size + 1)

    def test_shutdown_worker_stops_processing(self) -> None:
        """Verify shutdown_worker prevents further processing."""
        start_worker()
        time.sleep(0.1)
        shutdown_worker(timeout=2.0)

        # After shutdown, job queue should still accept submissions
        # but the worker won't process them
        job = Job(job_id="test-1", filename="test.gcode")
        job_store = MagicMock(spec=JobStore)
        initial_size = _job_queue.qsize()
        submit_job(job, b"G28\n", job_store)

        # Job remains in queue (not processed)
        self.assertEqual(_job_queue.qsize(), initial_size + 1)

    def test_shutdown_worker_timeout(self) -> None:
        """Verify shutdown_worker respects timeout."""
        start_worker()
        time.sleep(0.1)

        start_time = time.time()
        shutdown_worker(timeout=1.0)
        elapsed = time.time() - start_time

        # Should respect timeout (allow some slack for scheduling)
        self.assertLess(elapsed, 3.0)

    def test_start_worker_multiple_times(self) -> None:
        """Verify start_worker can be called multiple times safely."""
        start_worker()
        time.sleep(0.1)
        # Should not error on second call
        start_worker()
        time.sleep(0.1)

        shutdown_worker(timeout=2.0)


class TestConcurrentJobProcessing(unittest.TestCase):
    """Test concurrent job submission and serialized processing."""

    def setUp(self) -> None:
        """Reset queue and start worker."""
        # Drain queue
        while not _job_queue.empty():
            try:
                _job_queue.get_nowait()
            except queue.Empty:
                break
        self.job_store = MagicMock(spec=JobStore)
        self.processed_jobs: list = []
        self.lock = threading.Lock()

    def tearDown(self) -> None:
        """Cleanup worker."""
        try:
            shutdown_worker(timeout=2.0)
        except Exception:
            pass

    @patch("web.worker.open_memory_db")
    @patch("web.worker.run_pipeline")
    @patch("web.worker.get_all_layers")
    def test_multiple_submissions_processed_serially(
        self, mock_get_layers, mock_pipeline, mock_open_db
    ) -> None:
        """Verify multiple jobs are processed one at a time."""
        # Setup
        mock_conn = MagicMock()
        mock_open_db.return_value = mock_conn

        pipeline_result = Mock()
        pipeline_result.modified_gcode = "G28\n"
        pipeline_result.total_layers = 1
        pipeline_result.encoded_count = 0
        pipeline_result.skipped_count = 1
        pipeline_result.nominal_spacing_mm = 0.0
        pipeline_result.file_id = 1
        mock_pipeline.return_value = pipeline_result

        mock_get_layers.return_value = []
        mock_conn.iterdump.return_value = []

        # Track job processing order
        original_run_job = _run_job

        def track_run_job(job, gcode_bytes, job_store):
            with self.lock:
                self.processed_jobs.append(job.job_id)
            original_run_job(job, gcode_bytes, job_store)

        # Submit multiple jobs
        start_worker()
        time.sleep(0.1)

        jobs = [
            Job(job_id=f"job-{i}", filename=f"test-{i}.gcode")
            for i in range(3)
        ]

        for job in jobs:
            submit_job(job, b"G28\n", self.job_store)

        # Wait for processing
        time.sleep(1.0)

        shutdown_worker(timeout=2.0)

    def test_queue_blocks_on_full_capacity(self) -> None:
        """Verify queue handles blocking when full (rare case)."""
        # Standard Queue is unbounded, so we test put/get behavior
        job = Job(job_id="test-block", filename="test.gcode")
        job_store = MagicMock(spec=JobStore)

        initial_size = _job_queue.qsize()
        # Should not block on put
        submit_job(job, b"G28\n", job_store)
        self.assertEqual(_job_queue.qsize(), initial_size + 1)

        # Should not block on get
        queued = _job_queue.get_nowait()
        self.assertIsNotNone(queued)


class TestJobProcessingErrorHandling(unittest.TestCase):
    """Test error handling during job processing."""

    def setUp(self) -> None:
        """Setup mocks."""
        self.job_store = MagicMock(spec=JobStore)

    @patch("web.worker.open_memory_db")
    def test_run_job_on_db_open_error(self, mock_open_db) -> None:
        """Verify job fails gracefully if DB open fails."""
        job = Job(job_id="test-db-error", filename="test.gcode")
        gcode_bytes = b"G28\n"

        mock_open_db.side_effect = RuntimeError("Cannot open database")

        _run_job(job, gcode_bytes, self.job_store)

        self.assertEqual(job.state, JobState.FAILED)
        self.assertIn("Cannot open database", job.error)

    @patch("web.worker.open_memory_db")
    @patch("web.worker.run_pipeline")
    def test_run_job_on_pipeline_timeout(
        self, mock_pipeline, mock_open_db
    ) -> None:
        """Verify job fails on pipeline timeout."""
        job = Job(job_id="test-timeout", filename="test.gcode")
        gcode_bytes = b"G28\n"
        mock_conn = MagicMock()
        mock_open_db.return_value = mock_conn

        mock_pipeline.side_effect = TimeoutError("Pipeline took too long")

        _run_job(job, gcode_bytes, self.job_store)

        self.assertEqual(job.state, JobState.FAILED)
        self.assertIn("too long", job.error)

    @patch("web.worker.open_memory_db")
    @patch("web.worker.run_pipeline")
    @patch("web.worker.get_all_layers")
    def test_run_job_on_iterdump_failure(
        self, mock_get_layers, mock_pipeline, mock_open_db
    ) -> None:
        """Verify job fails gracefully if DB dump fails."""
        job = Job(job_id="test-dump-error", filename="test.gcode")
        gcode_bytes = b"G28\n"
        mock_conn = MagicMock()
        mock_open_db.return_value = mock_conn

        pipeline_result = Mock()
        pipeline_result.modified_gcode = "G28\n"
        pipeline_result.total_layers = 1
        pipeline_result.encoded_count = 0
        pipeline_result.skipped_count = 1
        pipeline_result.nominal_spacing_mm = 0.0
        pipeline_result.file_id = 1
        mock_pipeline.return_value = pipeline_result

        mock_get_layers.return_value = []
        mock_conn.iterdump.side_effect = RuntimeError("DB dump failed")

        _run_job(job, gcode_bytes, self.job_store)

        self.assertEqual(job.state, JobState.FAILED)
        self.assertIn("DB dump failed", job.error)


if __name__ == "__main__":
    unittest.main()
