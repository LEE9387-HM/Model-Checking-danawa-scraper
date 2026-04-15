"""
batch_processor.py — CSV 배치 처리 + asyncio.Queue + 체크포인트 저장
"""
import asyncio
import csv
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
JOBS_DIR = Path(__file__).parent / "jobs"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"

for d in [DATA_DIR, JOBS_DIR, INPUT_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 배치 모델 간 딜레이 (초)
BATCH_DELAY_MIN = 5
BATCH_DELAY_MAX = 10


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class ModelItem:
    model_name: str
    category_hint: str = ""
    release_year_filter: str = ""


@dataclass
class JobCheckpoint:
    job_id: str
    total: int
    processed: int
    status: str
    results: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def save(self):
        path = JOBS_DIR / f"{self.job_id}.json"
        self.updated_at = time.time()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, job_id: str) -> "JobCheckpoint | None":
        path = JOBS_DIR / f"{job_id}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)


class BatchProcessor:
    """단일 백그라운드 워커 + asyncio.Queue 기반 배치 처리"""

    def __init__(self, queue_maxsize: int = 5):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
        self._jobs: dict[str, JobCheckpoint] = {}
        self._cancel_flags: dict[str, bool] = {}
        self._running = False

    async def start_worker(self):
        """FastAPI lifespan에서 호출"""
        self._running = True
        asyncio.create_task(self._worker_loop())

    async def _worker_loop(self):
        while self._running:
            try:
                job_id, items = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._process_job(job_id, items)
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[batch] 워커 오류: {e}")

    async def _process_job(self, job_id: str, items: list[ModelItem]):
        """단일 Job 처리"""
        # 지연 import (순환 방지)
        from crawler import fetch_model_spec
        from verifier import verify_samsung
        from scoring import score_model
        from spec_parser import parse_spec

        cp = self._jobs[job_id]
        cp.status = JobStatus.RUNNING
        cp.save()

        for item in items[cp.processed:]:
            if self._cancel_flags.get(job_id):
                cp.status = JobStatus.CANCELLED
                cp.save()
                return

            try:
                # Step 1: 크롤링
                raw_data = await fetch_model_spec(item.model_name)
                if "error" in raw_data:
                    raise ValueError(raw_data["error"])

                category = item.category_hint or raw_data.get("category", "tv")
                spec = parse_spec(category, raw_data["raw_spec"])

                # Step 2: 삼성 공식몰 검증
                verify_result = await verify_samsung(item.model_name, spec, category)
                final_spec = verify_result["corrected_spec"]

                # Step 3: 채점
                score_result = score_model(category, final_spec)

                cp.results.append({
                    "model_name": item.model_name,
                    "category": category,
                    "price": raw_data.get("price", 0),
                    "release_year": final_spec.get("release_year"),
                    "total_score": score_result["total_score"],
                    "verification": verify_result["status"],
                })

            except Exception as e:
                cp.errors.append({
                    "model_name": item.model_name,
                    "error": str(e),
                })
                print(f"[batch] 처리 실패 ({item.model_name}): {e}")

            cp.processed += 1
            cp.save()

            # 모델 간 딜레이
            import random
            delay = random.uniform(BATCH_DELAY_MIN, BATCH_DELAY_MAX)
            await asyncio.sleep(delay)

        cp.status = JobStatus.DONE
        cp.save()
        await self._export_csv(job_id)

    async def _export_csv(self, job_id: str):
        """결과를 CSV로 저장"""
        cp = self._jobs[job_id]
        if not cp.results:
            return
        out_path = OUTPUT_DIR / f"{job_id}.csv"
        keys = list(cp.results[0].keys())
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(cp.results)
        print(f"[batch] CSV 저장 완료: {out_path}")

    def create_job(self, items: list[ModelItem]) -> str:
        job_id = str(uuid.uuid4())
        cp = JobCheckpoint(
            job_id=job_id,
            total=len(items),
            processed=0,
            status=JobStatus.QUEUED,
        )
        self._jobs[job_id] = cp
        cp.save()
        # 큐에 적재
        try:
            self._queue.put_nowait((job_id, items))
        except asyncio.QueueFull:
            cp.status = JobStatus.FAILED
            cp.save()
        return job_id

    def get_status(self, job_id: str) -> dict | None:
        cp = self._jobs.get(job_id) or JobCheckpoint.load(job_id)
        if not cp:
            return None
        return {
            "job_id": cp.job_id,
            "status": cp.status,
            "total": cp.total,
            "processed": cp.processed,
            "progress_pct": round(cp.processed / max(cp.total, 1) * 100, 1),
            "error_count": len(cp.errors),
        }

    def cancel_job(self, job_id: str) -> bool:
        if job_id in self._jobs:
            self._cancel_flags[job_id] = True
            return True
        return False

    def resume_job(self, job_id: str, items: list[ModelItem]) -> bool:
        cp = JobCheckpoint.load(job_id)
        if not cp:
            return False
        self._jobs[job_id] = cp
        self._cancel_flags[job_id] = False
        try:
            self._queue.put_nowait((job_id, items))
            return True
        except asyncio.QueueFull:
            return False

    def get_result_path(self, job_id: str) -> Path | None:
        path = OUTPUT_DIR / f"{job_id}.csv"
        return path if path.exists() else None


# 싱글턴 인스턴스 (main.py에서 import)
batch_processor = BatchProcessor()
