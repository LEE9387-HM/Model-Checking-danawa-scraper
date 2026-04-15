"""
test_batch.py — 배치 프로세서 단위 테스트
실제 크롤링 없이 BatchProcessor의 상태 관리·체크포인트·ETA 로직 검증
"""
import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from batch_processor import (
    BatchProcessor,
    JobCheckpoint,
    JobStatus,
    ModelItem,
    JOBS_DIR,
    OUTPUT_DIR,
)


# ─── ModelItem ───────────────────────────────────────────────────────────────

class TestModelItem:
    def test_required_field(self):
        item = ModelItem(model_name="KQ65QC80AFXKR")
        assert item.model_name == "KQ65QC80AFXKR"

    def test_optional_fields_default(self):
        item = ModelItem(model_name="TEST")
        assert item.category_hint == ""
        assert item.release_year_filter == ""


# ─── JobCheckpoint ───────────────────────────────────────────────────────────

class TestJobCheckpoint:
    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr("batch_processor.JOBS_DIR", tmp_path)
        cp = JobCheckpoint(
            job_id="test-abc",
            total=10,
            processed=3,
            status=JobStatus.RUNNING,
        )
        cp.save()
        loaded = JobCheckpoint.load("test-abc")
        assert loaded is not None
        assert loaded.job_id == "test-abc"
        assert loaded.total == 10

    def test_save_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("batch_processor.JOBS_DIR", tmp_path)
        cp = JobCheckpoint(job_id="save-test", total=5, processed=2, status=JobStatus.RUNNING)
        # 직접 경로 저장
        path = tmp_path / "save-test.json"
        cp.updated_at = time.time()
        import dataclasses
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dataclasses.asdict(cp), f)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["job_id"] == "save-test"
        assert data["total"] == 5

    def test_load_returns_none_for_missing(self):
        result = JobCheckpoint.load("nonexistent-job-id-xyz")
        assert result is None

    def test_backward_compat_defaults(self, tmp_path):
        """구버전 체크포인트(current_model 없음)도 로드 가능해야 한다."""
        path = tmp_path / "old-job.json"
        old_data = {
            "job_id": "old-job", "total": 5, "processed": 1,
            "status": "RUNNING", "results": [], "errors": [],
            "created_at": time.time(), "updated_at": time.time(),
            # current_model, start_time 없음
        }
        path.write_text(json.dumps(old_data))

        import dataclasses
        old_data["current_model"] = ""
        old_data["start_time"] = old_data["created_at"]
        cp = JobCheckpoint(**old_data)
        assert cp.current_model == ""
        assert cp.start_time > 0


# ─── BatchProcessor 상태 관리 ─────────────────────────────────────────────────

class TestBatchProcessorStatus:
    def setup_method(self):
        self.bp = BatchProcessor()

    def _make_cp(self, processed, total, status=JobStatus.RUNNING, elapsed=60.0):
        cp = JobCheckpoint(
            job_id="test-job",
            total=total,
            processed=processed,
            status=status,
            start_time=time.time() - elapsed,
        )
        self.bp._jobs["test-job"] = cp
        return cp

    def test_get_status_progress_pct(self):
        self._make_cp(processed=4, total=10)
        st = self.bp.get_status("test-job")
        assert st["progress_pct"] == 40.0

    def test_get_status_eta_calculation(self):
        # 4개 처리에 60초 → 남은 6개 예상 90초
        self._make_cp(processed=4, total=10, elapsed=60.0)
        st = self.bp.get_status("test-job")
        assert st["eta_seconds"] == pytest.approx(90, abs=2)

    def test_get_status_no_eta_when_not_running(self):
        self._make_cp(processed=4, total=10, status=JobStatus.PAUSED)
        st = self.bp.get_status("test-job")
        assert st["eta_seconds"] is None

    def test_get_status_no_eta_when_zero_processed(self):
        self._make_cp(processed=0, total=10)
        st = self.bp.get_status("test-job")
        assert st["eta_seconds"] is None

    def test_get_status_returns_none_for_unknown(self):
        assert self.bp.get_status("unknown-job-xyz") is None

    def test_cancel_job(self):
        self._make_cp(processed=2, total=10)
        result = self.bp.cancel_job("test-job")
        assert result is True
        assert self.bp._cancel_flags["test-job"] is True

    def test_cancel_unknown_job_returns_false(self):
        assert self.bp.cancel_job("no-such-job") is False

    def test_get_status_error_count(self):
        cp = self._make_cp(processed=3, total=10)
        cp.errors = [
            {"model_name": "A", "error": "timeout"},
            {"model_name": "B", "error": "not found"},
        ]
        st = self.bp.get_status("test-job")
        assert st["error_count"] == 2
        assert len(st["errors"]) == 2

    def test_get_status_errors_capped_at_10(self):
        cp = self._make_cp(processed=15, total=20)
        cp.errors = [{"model_name": f"M{i}", "error": "err"} for i in range(15)]
        st = self.bp.get_status("test-job")
        assert len(st["errors"]) == 10

    def test_get_status_current_model(self):
        cp = self._make_cp(processed=3, total=10)
        cp.current_model = "KQ65QC80AFXKR"
        st = self.bp.get_status("test-job")
        assert st["current_model"] == "KQ65QC80AFXKR"


# ─── create_job ──────────────────────────────────────────────────────────────

class TestCreateJob:
    def test_create_job_returns_uuid(self):
        bp = BatchProcessor(queue_maxsize=10)
        items = [ModelItem(model_name="TEST")]
        job_id = bp.create_job(items)
        assert len(job_id) == 36  # UUID 형식

    def test_create_job_status_queued(self):
        bp = BatchProcessor(queue_maxsize=10)
        items = [ModelItem(model_name="TEST")]
        job_id = bp.create_job(items)
        st = bp.get_status(job_id)
        assert st["status"] == JobStatus.QUEUED
        assert st["total"] == 1

    def test_create_job_queue_full_marks_failed(self):
        # maxsize=1로 큐 생성 후 미리 1개를 채워서 QueueFull 유도
        bp = BatchProcessor(queue_maxsize=1)
        bp._queue.put_nowait("dummy-job")  # 큐를 꽉 채움
        items = [ModelItem(model_name="TEST")]
        job_id = bp.create_job(items)
        st = bp.get_status(job_id)
        assert st["status"] == JobStatus.FAILED


# ─── _recover_stale_jobs ─────────────────────────────────────────────────────

class TestRecoverStaleJobs:
    def test_running_jobs_become_paused(self, tmp_path, monkeypatch):
        monkeypatch.setattr("batch_processor.JOBS_DIR", tmp_path)

        stale = {
            "job_id": "stale-123", "total": 10, "processed": 3,
            "status": "RUNNING", "results": [], "errors": [],
            "current_model": "SOME_MODEL", "start_time": time.time() - 100,
            "created_at": time.time(), "updated_at": time.time(),
        }
        (tmp_path / "stale-123.json").write_text(json.dumps(stale))

        bp = BatchProcessor()
        bp._recover_stale_jobs()

        recovered = json.loads((tmp_path / "stale-123.json").read_text())
        assert recovered["status"] == "PAUSED"
        assert recovered["current_model"] == ""

    def test_non_running_jobs_not_touched(self, tmp_path, monkeypatch):
        monkeypatch.setattr("batch_processor.JOBS_DIR", tmp_path)

        done = {
            "job_id": "done-456", "total": 5, "processed": 5,
            "status": "DONE", "results": [], "errors": [],
            "current_model": "", "start_time": time.time(),
            "created_at": time.time(), "updated_at": time.time(),
        }
        (tmp_path / "done-456.json").write_text(json.dumps(done))

        bp = BatchProcessor()
        bp._recover_stale_jobs()

        recovered = json.loads((tmp_path / "done-456.json").read_text())
        assert recovered["status"] == "DONE"
