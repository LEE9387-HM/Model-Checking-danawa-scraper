# danawa-scraper

> 삼성 전자제품 스펙 채점 + 경쟁사 비교 웹서비스  
> 다나와 크롤링 → 삼성 공식몰 교차검증 → 100점 채점 → 경쟁사 코사인 유사도 랭킹

---

## 🚀 빠른 시작

```powershell
cd C:\WorkSpace\Coding\코딩\danawa-scraper
.\venv\Scripts\activate
cd backend
uvicorn main:app --reload --port 8001
# 브라우저 → http://localhost:8001
```

---

## 🏗️ 기술 스택

| 영역 | 기술 |
|------|------|
| 크롤링 | Playwright (async, headless Chromium) |
| 백엔드 | FastAPI + Uvicorn |
| 데이터 처리 | pandas + scikit-learn (MinMaxScaler, cosine_similarity) |
| 프론트엔드 | HTML + Vanilla CSS/JS (다크 Glassmorphism) |
| 테스트 | pytest + pytest-asyncio (117 passed) |

---

## ⚙️ 7단계 파이프라인

```
모델명 입력
  │
  ▼ Step 1  다나와 검색 + 스펙 크롤링        (~15초)
  ▼ Step 2  삼성 공식몰 교차검증             (~10초)
  ▼ Step 3  100점 채점 (Min-Max 가중 점수)   (<1초)
  ▼ Step 4  경쟁사 탐색 (다나와 인기순 20개)  (~60초)
  ▼ Step 5  코사인 유사도 필터 ≥0.75 + 랭킹  (<2초)
  ▼ Step 6  경쟁사 공식몰 교차검증           (~30초)
  ▼ Step 7  최종 결과 (레이더 차트 + 비교표)
```

---

## 📂 프로젝트 구조

```
danawa-scraper/
├── backend/
│   ├── main.py               # FastAPI 서버 + API 라우트
│   ├── crawler.py            # Playwright 다나와 크롤러
│   ├── verifier.py           # 공식몰 교차검증 엔진
│   ├── scoring.py            # 가중 점수 계산 (Min-Max)
│   ├── similarity.py         # 코사인 유사도 + 복합 랭킹
│   ├── spec_parser.py        # 스펙 텍스트 → 구조화 (11개 카테고리)
│   ├── batch_processor.py    # CSV 배치 처리 + 체크포인트
│   ├── rules/                # 카테고리별 채점 룰셋 JSON × 11
│   ├── selectors/            # CSS 셀렉터 설정 JSON × 4
│   └── official_malls/       # 공식몰 어댑터 (Samsung / LG / Naver)
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── tests/
    ├── conftest.py
    ├── test_scoring.py       # 룰셋 무결성 + 파서 + 채점 (60개)
    ├── test_verifier.py      # 교차검증 로직 mock 테스트 (27개)
    ├── test_batch.py         # 배치 프로세서 단위 테스트 (19개)
    └── test_e2e_crawler.py   # E2E 크롤러 (DANAWA_E2E=1 필요)
```

---

## ✅ 해결된 이슈 (시계열)

### 2026-04-15
| # | 이슈 | 해결 방법 |
|---|------|----------|
| 1 | venv 없이 실행 시 playwright ModuleNotFoundError | `.\venv\Scripts\activate` 후 실행 |
| 2 | git 초기화 안 됨 | `git init` + `git remote add origin` |

### 2026-04-16 — 개발 단계 (Phase 1~7)
| # | 이슈 | 해결 방법 |
|---|------|----------|
| 3 | `asyncio.Queue(maxsize=0)` = 무한 큐 (테스트 의도와 다름) | `maxsize=1` + pre-fill로 QueueFull 테스트 수정 |
| 4 | `patch("verifier.SamsungAdapter")` AttributeError | 어댑터를 모듈 최상단 import로 이동 |
| 5 | `test_save_and_load` 단언 오류 | monkeypatch 적용 범위 이해 후 `is not None`으로 수정 |

### 2026-04-16 — 실서버 구동 디버깅
| # | 이슈 | 원인 | 해결 방법 |
|---|------|------|----------|
| 6 | 검색 버튼 완전 무반응 | `app.js` `.then(r =>)` 콜백에 `async` 누락 → SyntaxError로 스크립트 로딩 실패 | `.then(async r =>)` 5곳 일괄 수정 |
| 7 | `/api/search` 500 (Internal Server Error) | Windows `asyncio.SelectorEventLoop`이 subprocess 미지원 → Playwright `NotImplementedError` | `crawler.py` / `base_adapter.py`: `asyncio.ProactorEventLoop` 전용 스레드에서 실행 |
| 8 | `/api/ping` 404, API 라우트 전체 불도달 | `app.mount("/", StaticFiles(...))` 가 Starlette Mount FULL match로 모든 요청 선점 | `app.mount` 제거 → `GET /{full_path:path}` catch-all 라우트로 교체 |
| 9 | 에러 응답 파싱 `body stream already read` | `.then()` 안에서 `r.json()` 실패 후 `r.text()` 재시도 시 body 소진 | `text = await r.text()` 먼저 읽고 `JSON.parse(text)` fallback |
| 10 | 포트 8000 phantom 프로세스 | Windows 시스템 프로세스(PID 8100)가 포트 점유, `taskkill` 불가 | 포트 8001로 변경 운영 |

---

## 🔧 현재 동작 상태 (2026-04-16 기준)

| 단계 | 상태 | 비고 |
|------|------|------|
| Step 1 다나와 크롤링 | ✅ 정상 | KQ65QNH70AFXKR 등 확인 |
| Step 2 삼성 공식몰 검증 | ✅ 정상 | 셀렉터 업데이트 완료 |
| Step 3 100점 채점 | ✅ 정상 | 레이더 차트 표시 |
| Step 4 경쟁사 탐색 | ✅ 정상 | 셀렉터 업데이트 완료 |
| Step 5 유사도 랭킹 | ✅ 정상 (데이터 있을 때) | |
| Step 6 경쟁사 검증 | ✅ 정상 (데이터 있을 때) | |
| CSV 배치 처리 | ✅ 정상 | ETA·체크포인트·재개 |
| pytest | ✅ 117 passed | 5 skipped (E2E) |

---

## 📋 잔여 과제 리스트

### 🔴 우선순위 높음

| # | 과제 | 파일 | 세부 내용 |
|---|------|------|----------|
| T-1 | 셀렉터 유지보수 자동화 리서치 | `selectors/` | ScrapeGraphAI/AgentQL 도입 검토 |
| T-2 | LLM 기반 크롤링 에이전트 PoC | `browser-use` | Browser-Use 기반 자율 탐색 모델링 |

### 🟡 우선순위 중간

| # | 과제 | 파일 | 세부 내용 |
|---|------|------|----------|
| T-3 | LG 공식몰 셀렉터 검증 | `selectors/lg.json` | `lge.co.kr` 현재 HTML 구조 확인 |
| T-4 | 네이버 쇼핑 셀렉터 검증 | `selectors/naver.json` | 네이버 쇼핑 검색 결과 현재 HTML 확인 |
| T-5 | 포트 8000 충돌 근본 원인 파악 | — | Windows 시스템 프로세스 정체 확인, 포트 정책 수립 |
| T-6 | E2E 테스트 자동화 | `tests/test_e2e_crawler.py` | `DANAWA_E2E=1` 환경에서 실제 크롤링 CI 검증 |

### 🟢 우선순위 낮음

| # | 과제 | 파일 | 세부 내용 |
|---|------|------|----------|
| T-7 | 단건 분석 목표 시간 검증 | — | 2분 이내 완료 여부 실측 |
| T-8 | CSV 배치 100개 성능 측정 | — | 3~5시간 목표 대비 실측 |
| T-9 | 셀렉터 변경 감지 자동화 | `selectors/` | HTML 구조 변경 시 알림 또는 자동 fallback 메커니즘 |

---

## 🧪 테스트 실행

```powershell
cd C:\WorkSpace\Coding\코딩\danawa-scraper
.\venv\Scripts\activate

# 단위 테스트 (네트워크 불필요)
pytest tests/ -v --ignore=tests/test_e2e_crawler.py

# E2E 포함 전체 실행 (실제 크롤링)
$env:DANAWA_E2E="1"; pytest tests/ -v --timeout=120
```

---

## 🔌 API 엔드포인트

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/search` | Step 1: 다나와 모델 검색 |
| POST | `/api/verify` | Step 2: 삼성 공식몰 교차검증 |
| POST | `/api/score` | Step 3: 100점 채점 |
| POST | `/api/competitors` | Step 4~5: 경쟁사 탐색 + 랭킹 |
| POST | `/api/competitors/verify` | Step 6: 경쟁사 검증 + 재채점 |
| POST | `/api/batch/upload` | CSV 배치 업로드 |
| GET | `/api/batch/{job_id}/status` | 배치 진행률 |
| GET | `/api/batch/{job_id}/result` | 결과 CSV 다운로드 |
| GET | `/api/ping` | 헬스체크 |
| GET | `/docs` | Swagger UI |
