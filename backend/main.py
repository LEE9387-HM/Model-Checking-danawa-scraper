"""
main.py — FastAPI 백엔드 서버
7단계 파이프라인 API + CSV 배치 처리 API + 정적 프론트엔드 서빙
"""
import asyncio
import sys

# Windows에서 Playwright subprocess 실행을 위해 ProactorEventLoop 필수
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import csv
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from batch_processor import batch_processor, ModelItem
from crawler import fetch_model_spec, fetch_competitors, get_category_url
from scoring import score_model, score_pool, load_rules
from similarity import filter_and_rank
from spec_parser import parse_spec
from verifier import verify_samsung, verify_competitor

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
RULES_DIR = Path(__file__).parent / "rules"


# ─── Request / Response 스키마 ───────────────────────────────────────────────

class SearchRequest(BaseModel):
    model_name: str


class VerifyRequest(BaseModel):
    model_name: str
    category: str
    raw_spec: dict[str, str]


class ScoreRequest(BaseModel):
    category: str
    spec: dict[str, Any]


class CompetitorsRequest(BaseModel):
    category: str
    samsung_spec: dict[str, Any]
    primary_spec_filter: dict[str, Any] = {}
    category_url: str = ""
    release_year: int | None = None


class CompetitorVerifyRequest(BaseModel):
    category: str
    competitors: list[dict[str, Any]]
    samsung_spec: dict[str, Any] = {}


# ─── Lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await batch_processor.start_worker()
    yield


# ─── FastAPI 앱 ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="다나와 삼성 스펙 분석기",
    description="삼성 전자제품 스펙 채점 + 경쟁사 비교 웹서비스",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


# ─── 단건 분석 API ───────────────────────────────────────────────────────────

@app.post("/api/search", summary="Step 1: 다나와 모델 검색 + 스펙 크롤링")
async def api_search(req: SearchRequest):
    import traceback
    print(f"[DEBUG] /api/search 요청: {req.model_name}", flush=True)
    try:
        result = await fetch_model_spec(req.model_name)
        print(f"[DEBUG] fetch_model_spec 결과: {list(result.keys())}", flush=True)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@app.post("/api/verify", summary="Step 2: 삼성 공식몰 교차검증")
async def api_verify(req: VerifyRequest):
    spec = parse_spec(req.category, req.raw_spec)
    result = await verify_samsung(req.model_name, spec, req.category)
    return result


@app.post("/api/score", summary="Step 3: 100점 채점")
async def api_score(req: ScoreRequest):
    result = score_model(req.category, req.spec)
    return result


@app.post("/api/competitors", summary="Step 4~5: 경쟁사 탐색 + 유사도 랭킹")
async def api_competitors(req: CompetitorsRequest):
    # category_url이 없으면 카테고리에서 자동 생성
    category_url = req.category_url or get_category_url(req.category)

    competitors_raw = await fetch_competitors(
        category_url=category_url,
        primary_spec_filter=req.primary_spec_filter,
        exclude_brand="삼성전자",
        max_count=20,
        samsung_release_year=req.release_year,
    )

    if not competitors_raw:
        return {"competitors": [], "total_found": 0}

    # 스펙 파싱
    rules = load_rules(req.category)
    grading_spec_names = list(rules["grading_specs"].keys())

    parsed_comps = []
    for comp in competitors_raw:
        spec = parse_spec(req.category, comp["raw_spec"])
        parsed_comps.append({**comp, "spec": spec})

    # 삼성 포함 전체 풀 기준 Min-Max 채점 (공정한 상대 평가)
    all_models = [{"spec": req.samsung_spec}] + parsed_comps
    scored_all = score_pool(req.category, all_models)
    # 첫 번째(삼성)는 제외하고 경쟁사만 추출
    scored_comps = scored_all[1:]
    # score_pool 결과를 parsed_comps와 병합
    competitors = [
        {**parsed_comps[i], "score": scored_comps[i]["score"]}
        for i in range(len(parsed_comps))
    ]

    # 유사도 필터 + 복합 랭킹
    ranked = filter_and_rank(
        samsung_spec=req.samsung_spec,
        competitors=competitors,
        spec_names=grading_spec_names,
        similarity_threshold=0.75,
        top_n=10,
    )
    return {"competitors": ranked, "total_found": len(competitors)}


@app.post("/api/competitors/verify", summary="Step 6: 경쟁사 공식몰 교차검증 + 재채점/재랭킹")
async def api_competitors_verify(req: CompetitorVerifyRequest):
    # ─ 1) 공식몰 교차검증 (병렬 처리) ─
    import asyncio as _aio
    async def _verify_one(comp):
        verify_res = await verify_competitor(
            model_name=comp["model_name"],
            brand=comp.get("brand", ""),
            danawa_spec=comp.get("spec", {}),
            category=req.category,
        )
        return {
            **comp,
            "spec":         verify_res["corrected_spec"],
            "verification": verify_res["status"],
            "diffs":        verify_res["diffs"],
        }

    verified = list(await _aio.gather(*[_verify_one(c) for c in req.competitors]))

    # ─ 2) 보정 스펙 기준 재채점 (CORRECTED 항목이 있을 때만 의미 있음) ─
    corrected_any = any(c["verification"] == "CORRECTED" for c in verified)
    if corrected_any and req.samsung_spec:
        rules = load_rules(req.category)
        grading_spec_names = list(rules["grading_specs"].keys())

        # 삼성 포함 전체 풀 재채점
        all_models = [{"spec": req.samsung_spec}] + verified
        scored_all = score_pool(req.category, all_models)
        for i, comp in enumerate(verified):
            comp["score"] = scored_all[i + 1]["score"]

        # 재랭킹
        verified = filter_and_rank(
            samsung_spec=req.samsung_spec,
            competitors=verified,
            spec_names=grading_spec_names,
            similarity_threshold=0.0,   # 이미 1차 필터 통과한 목록
            top_n=len(verified),
        )

    return {"competitors": verified, "rescored": corrected_any}


@app.get("/api/rules/{category}", summary="카테고리 룰셋 조회")
async def api_get_rules(category: str):
    try:
        rules = load_rules(category)
        return rules
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"룰셋 없음: {category}")


@app.get("/api/categories", summary="지원 카테고리 목록")
async def api_categories():
    cats = []
    for f in RULES_DIR.glob("*.json"):
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)
        cats.append({"category": data["category"], "display_name": data["display_name"]})
    return {"categories": sorted(cats, key=lambda x: x["category"])}


# ─── CSV 배치 처리 API ───────────────────────────────────────────────────────

@app.post("/api/batch/upload", summary="CSV 업로드 → job_id 반환")
async def batch_upload(file: UploadFile = File(...)):
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    items: list[ModelItem] = []
    for row in reader:
        model_name = row.get("model_name", "").strip()
        if model_name:
            items.append(ModelItem(
                model_name=model_name,
                category_hint=row.get("category_hint", "").strip(),
                release_year_filter=row.get("release_year_filter", "").strip(),
            ))

    if not items:
        raise HTTPException(status_code=400, detail="유효한 모델이 없습니다")

    job_id = batch_processor.create_job(items)
    return {"job_id": job_id, "total": len(items), "status": "QUEUED"}


@app.get("/api/batch/{job_id}/status", summary="배치 진행률 조회")
async def batch_status(job_id: str):
    status = batch_processor.get_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job 없음")
    return status


@app.get("/api/batch/{job_id}/result", summary="결과 CSV 다운로드")
async def batch_result(job_id: str):
    path = batch_processor.get_result_path(job_id)
    if not path:
        raise HTTPException(status_code=404, detail="결과 없음 (처리 중이거나 실패)")
    return FileResponse(
        path=str(path),
        media_type="text/csv",
        filename=f"result_{job_id[:8]}.csv",
    )


@app.post("/api/batch/{job_id}/resume", summary="중단된 배치 재개")
async def batch_resume(job_id: str, file: UploadFile = File(...)):
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    items = [
        ModelItem(
            model_name=row.get("model_name", "").strip(),
            category_hint=row.get("category_hint", "").strip(),
        )
        for row in reader if row.get("model_name", "").strip()
    ]
    ok = batch_processor.resume_job(job_id, items)
    if not ok:
        raise HTTPException(status_code=404, detail="Job 없음 또는 큐 포화")
    return {"message": "재개 요청 완료", "job_id": job_id}


@app.delete("/api/batch/{job_id}", summary="배치 작업 취소")
async def batch_cancel(job_id: str):
    ok = batch_processor.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job 없음")
    return {"message": "취소 요청 완료", "job_id": job_id}


# ─── 테스트 ─────────────────────────────────────────────────────────────────

@app.get("/api/ping")
async def ping():
    print("[DEBUG] /api/ping 호출됨", flush=True)
    return {"pong": True}


# ─── 헬스체크 ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# ─── 프론트엔드 정적 파일 서빙 (catch-all — 반드시 마지막에) ────────────────

@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """API 경로에 매칭되지 않은 모든 GET 요청 → 정적 파일 or index.html"""
    target = FRONTEND_DIR / full_path
    if target.is_file():
        return FileResponse(str(target))
    # SPA fallback
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    raise HTTPException(status_code=404, detail="Not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
