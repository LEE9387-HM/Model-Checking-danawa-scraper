"""
batch_processor.py — CSV 배치 처리 + asyncio.Queue + 체크포인트 저장
"""
import asyncio
import csv
import json
import random
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

DATA_DIR   = Path(__file__).parent / "data"
JOBS_DIR   = Path(__file__).parent / "jobs"
INPUT_DIR  = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"

for _d in [DATA_DIR, JOBS_DIR, INPUT_DIR, OUTPUT_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

BATCH_DELAY_MIN = 5
BATCH_DELAY_MAX = 10


# ─── 상태 Enum ───────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    QUEUED    = "QUEUED"
    RUNNING   = "RUNNING"
    PAUSED    = "PAUSED"
    DONE      = "DONE"
    FAILED    = "FAILED"
    CANCELLED = "CANCELLED"


# ─── 데이터 클래스 ────────────────────────────────────────────────────────────

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
    errors: list[dict]  = field(default_factory=list)
    current_model: str  = ""
    start_time: float   = field(default_factory=time.time)
    created_at: float   = field(default_factory=time.time)
    updated_at: float   = field(default_factory=time.time)

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
        # 구버전 체크포인트 호환 (current_model, start_time 없을 수 있음)
        data.setdefault("current_model", "")
        data.setdefault("start_time", data.get("created_at", time.time()))
        return cls(**data)


# ─── 배치 프로세서 ────────────────────────────────────────────────────────────

class BatchProcessor:
    """단일 백그라운드 워커 + asyncio.Queue 기반 배치 처리"""

    def __init__(self, queue_maxsize: int = 5):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
        self._jobs: dict[str, JobCheckpoint] = {}
        self._cancel_flags: dict[str, bool] = {}
        self._running = False

    async def start_worker(self):
        """FastAPI lifespan에서 호출. RUNNING 상태 잔여 Job을 PAUSED로 복구."""
        self._running = True
        self._recover_stale_jobs()
        asyncio.create_task(self._worker_loop())

    def _recover_stale_jobs(self):
        """서버 재시작 시 RUNNING 상태로 남은 Job을 PAUSED로 변경."""
        for cp_path in JOBS_DIR.glob("*.json"):
            try:
                with open(cp_path, encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("status") == JobStatus.RUNNING:
                    data["status"] = JobStatus.PAUSED
                    data["current_model"] = ""
                    with open(cp_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    print(f"[batch] 재시작 복구: {data['job_id']} → PAUSED")
            except Exception as e:
                print(f"[batch] 복구 오류 {cp_path}: {e}")

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
        """단일 Job 처리 — 크롤링 → 검증 → 채점 → 경쟁사 분석 → 체크포인트 저장."""
        from crawler import fetch_model_spec, fetch_competitors, get_category_url
        from verifier import verify_samsung
        from scoring import score_model, load_rules, score_pool
        from spec_parser import parse_spec
        from similarity import filter_and_rank
        from price_intelligence import get_price_adequacy_verdict

        cp = self._jobs[job_id]
        cp.status = JobStatus.RUNNING
        cp.start_time = time.time()
        cp.save()

        for item in items[cp.processed:]:
            if self._cancel_flags.get(job_id):
                cp.status = JobStatus.CANCELLED
                cp.current_model = ""
                cp.save()
                return

            cp.current_model = item.model_name
            cp.save()

            try:
                # 1) 삼성 모델 크롤링 및 파싱
                raw_data = await fetch_model_spec(item.model_name)
                if "error" in raw_data:
                    raise ValueError(raw_data["error"])

                category = item.category_hint or "tv"
                rules = load_rules(category)
                spec = parse_spec(category, raw_data["raw_spec"])

                # 2) 삼성 공식몰 검증 (Waterfall)
                verify_result = await verify_samsung(item.model_name, spec, category)
                final_samsung_spec = verify_result["corrected_spec"]

                # 3) 삼성 모델 채점
                samsung_score_res = score_model(category, final_samsung_spec)
                s_total_score = samsung_score_res["total_score"]

                # 4) [신규] 경쟁사 탐색 및 분석 (CPI/Verdict)
                # 동일 출시연도 모델 위주로 탐색
                s_release_year = final_samsung_spec.get("release_year")
                cat_url = get_category_url(category)
                
                # 다나와에서 경쟁사 검색
                comps_raw = await fetch_competitors(
                    category_url=cat_url,
                    primary_spec_filter={}, # 필요 시 확장
                    exclude_brand="삼성전자",
                    max_count=10,
                    samsung_release_year=s_release_year
                )
                
                top_comp_data = {}
                if comps_raw:
                    # 경쟁사 스펙 파싱 및 채점 (삼성과 동일 풀)
                    parsed_comps = []
                    for c in comps_raw:
                        c_spec = parse_spec(category, c["raw_spec"])
                        parsed_comps.append({**c, "spec": c_spec})
                    
                    all_models = [{"spec": final_samsung_spec}] + parsed_comps
                    scored_all = score_pool(category, all_models)
                    
                    # 랭킹 산출 (CPI 포함)
                    ranked_comps = filter_and_rank(
                        samsung_data={
                            "spec": final_samsung_spec,
                            "price": raw_data.get("price", 0),
                            "score": {"total_score": s_total_score}
                        },
                        competitors=scored_all[1:],
                        rules=rules,
                        similarity_threshold=0.0, # 배치 시에는 가장 유사한 것 1개라도 무조건 찾기
                        top_n=1
                    )
                    
                    if ranked_comps:
                        top_c = ranked_comps[0]
                        analysis = get_price_adequacy_verdict(
                            cpi=top_c["cpi"],
                            score_diff=s_total_score - top_c["score"]["total_score"]
                        )
                        top_comp_data = {
                            "comp_model":  top_c["model_name"],
                            "comp_price":  top_c["price"],
                            "comp_score":  top_c["score"]["total_score"],
                            "comp_sim":    top_c["similarity"],
                            "cpi":         top_c["cpi"],
                            "verdict":     analysis["verdict"],
                            "verdict_msg": analysis["reason"]
                        }

                # CSV 행 구성
                row: dict = {
                    "model_name":   item.model_name,
                    "category":     category,
                    "brand":        raw_data.get("brand", ""),
                    "price":        raw_data.get("price", 0),
                    "release_year": final_samsung_spec.get("release_year", ""),
                    "review_count": raw_data.get("review_count", 0),
                    "total_score":  s_total_score,
                    "verification": verify_result["status"],
                    "verify_src":   verify_result.get("source", ""),
                }
                
                # 경쟁사 분석 결과 병합
                row.update(top_comp_data)
                
                # 스펙 점수 상세 추가
                for k, v in samsung_score_res.get("breakdown", {}).items():
                    row[f"score_{k}"] = v

                cp.results.append(row)
                verdict_str = top_comp_data.get('verdict', 'N/A')
                print(f"[batch] ({cp.processed + 1}/{cp.total}) {item.model_name}: {s_total_score}점 | Verdict: {verdict_str}")

            except Exception as e:
                cp.errors.append({
                    "model_name": item.model_name,
                    "error":      str(e),
                    "timestamp":  time.strftime("%Y-%m-%d %H:%M:%S"),
                })
                print(f"[batch] 처리 실패 ({item.model_name}): {e}")

            cp.processed += 1
            cp.save()

            delay = random.uniform(BATCH_DELAY_MIN, BATCH_DELAY_MAX)
            await asyncio.sleep(delay)

        cp.status = JobStatus.DONE
        cp.current_model = ""
        cp.save()
        await self._export_csv(job_id)

    async def _export_csv(self, job_id: str):
        """결과를 UTF-8 BOM CSV로 저장 (Excel 한글 호환)."""
        cp = self._jobs[job_id]
        if not cp.results:
            return

        out_path = OUTPUT_DIR / f"{job_id}.csv"

        # 전체 열 목록 (결과 행의 합집합)
        all_keys: list[str] = []
        seen: set[str] = set()
        for row in cp.results:
            for k in row:
                if k not in seen:
                    all_keys.append(k)
                    seen.add(k)

        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            for row in cp.results:
                writer.writerow({k: row.get(k, "") for k in all_keys})

        print(f"[batch] CSV 저장 완료: {out_path} ({len(cp.results)}행)")

    # ─── 공개 API ────────────────────────────────────────────────────────────

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

        processed = cp.processed
        total     = max(cp.total, 1)
        elapsed   = time.time() - cp.start_time if cp.start_time else 0
        remaining = total - processed

        # ETA 계산 (처리 속도 기반)
        eta_seconds: int | None = None
        if processed > 0 and cp.status == JobStatus.RUNNING:
            avg_per_item = elapsed / processed
            eta_seconds  = int(avg_per_item * remaining)

        return {
            "job_id":        cp.job_id,
            "status":        cp.status,
            "total":         cp.total,
            "processed":     processed,
            "progress_pct":  round(processed / total * 100, 1),
            "current_model": cp.current_model,
            "error_count":   len(cp.errors),
            "errors":        cp.errors[-10:],   # 최근 10개만
            "eta_seconds":   eta_seconds,
            "elapsed_sec":   int(elapsed),
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
        cp.status = JobStatus.QUEUED
        self._jobs[job_id] = cp
        self._cancel_flags[job_id] = False
        try:
            self._queue.put_nowait((job_id, items))
            cp.save()
            return True
        except asyncio.QueueFull:
            return False

    def get_result_path(self, job_id: str) -> Path | None:
        path = OUTPUT_DIR / f"{job_id}.csv"
        return path if path.exists() else None


# 싱글턴 인스턴스
batch_processor = BatchProcessor()
