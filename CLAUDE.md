# danawa-scraper — 운영 매뉴얼 & 진척 관리

> **삼성 전자제품 스펙 채점 + 경쟁사 비교 웹서비스**  
> 다나와 크롤링 → 공식몰 교차검증 → 가중 채점 → 경쟁사 랭킹

---

## 📁 프로젝트 경로

```
C:\WorkSpace\Coding\코딩\danawa-scraper\
```

---

## 🎯 프로젝트 목표

다나와에서 삼성 전자제품의 스펙을 크롤링하고, 공식몰 교차검증 후
**가중치 기반 100점 채점 + 경쟁사 코사인 유사도 매칭 + 복합 랭킹 리스팅**을 수행.
CSV 일괄 업로드로 대량 배치 처리도 지원.

---

## 🏗️ 기술 스택

| 영역 | 선택 | 이유 |
|------|------|------|
| 크롤링 | **Playwright (async)** | JS 동적 렌더링 + anti-bot 우회 최적 |
| 백엔드 | **FastAPI + Uvicorn** | 비동기 I/O + Swagger 자동 문서 |
| 데이터 처리 | **pandas + scikit-learn** | MinMaxScaler, cosine_similarity |
| 프론트엔드 | **HTML + Vanilla CSS + JS** | 다크 Glassmorphism UI |
| 설정 관리 | **JSON** (카테고리 룰셋 + CSS Selector 맵) | 코드 변경 없이 수정 가능 |

---

## 📂 파일 구조

```
danawa-scraper/
├── CLAUDE.md                  ← 이 파일 (운영 매뉴얼 & 진척 관리)
├── danawa_crawling_reference.md
├── backend/
│   ├── main.py                # FastAPI 앱 + API 라우트
│   ├── crawler.py             # Playwright 다나와 크롤링
│   ├── verifier.py            # 공식몰 교차검증 엔진
│   ├── scoring.py             # 스펙 정규화 + 가중 점수
│   ├── similarity.py          # 코사인 유사도 + 복합 랭킹
│   ├── spec_parser.py         # 스펙 텍스트 → 구조화 딕셔너리
│   ├── batch_processor.py     # CSV 배치 처리 + 큐 + 체크포인트
│   ├── requirements.txt
│   ├── rules/                 # 카테고리별 채점 룰 (JSON × 11)
│   │   ├── tv.json
│   │   ├── refrigerator.json
│   │   ├── washer.json
│   │   ├── dryer.json
│   │   ├── air_conditioner.json
│   │   ├── dishwasher.json
│   │   ├── air_purifier.json
│   │   ├── vacuum.json
│   │   ├── robot_vacuum.json
│   │   ├── microwave.json
│   │   └── monitor.json
│   ├── selectors/             # CSS Selector 설정 (HTML 구조 변경 시 여기만 수정)
│   │   ├── danawa.json
│   │   ├── samsung.json
│   │   ├── lg.json
│   │   └── naver.json
│   ├── official_malls/        # 제조사별 공식몰 크롤링 어댑터 (확장 용이)
│   │   ├── base_adapter.py
│   │   ├── samsung_adapter.py
│   │   ├── lg_adapter.py
│   │   └── naver_store_adapter.py
│   ├── data/
│   │   ├── input/             # 업로드 CSV
│   │   └── output/            # 결과 CSV
│   └── jobs/                  # 배치 체크포인트 (중단 시 재개용)
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── tests/
    ├── test_scoring.py
    ├── test_verifier.py
    └── test_batch.py
```

---

## ⚙️ 워크플로우 — 7단계 파이프라인

### 단건 분석 흐름 (목표: 2분 이내)

```
[입력: 삼성 모델명]
    │
    ▼ Step 1 (~15초)
┌─────────────────────────────────────┐
│  다나와 검색 + 스펙 크롤링           │
│  URL: search.danawa.com/dsearch.php │
│  출력: 카테고리, 필수스펙, 등급스펙, │
│        가격, 출시년도, 리뷰수        │
└─────────────────────────────────────┘
    │
    ▼ Step 2 (~10초)  ★ 채점 전 필수
┌─────────────────────────────────────┐
│  삼성 공식몰 교차검증                │
│  URL: samsung.com/sec               │
│  출력: 보정된 스펙                   │
│        VERIFIED / CORRECTED / UNVERIFIED │
└─────────────────────────────────────┘
    │
    ▼ Step 3 (<1초)
┌─────────────────────────────────────┐
│  삼성 모델 채점 (100점 만점)          │
│  룰: rules/{category}.json          │
│  출력: 항목별 점수 + 총점            │
└─────────────────────────────────────┘
    │
    ▼ Step 4 (~60초)
┌─────────────────────────────────────┐
│  경쟁사 모델 탐색 (다나와 인기순)     │
│  삼성 제외 상위 20개 크롤링          │
│  필수스펙 필터 + 출시년도 ±2년 필터  │
└─────────────────────────────────────┘
    │
    ▼ Step 5 (<2초)
┌─────────────────────────────────────┐
│  채점 + 코사인 유사도 필터 (≥0.75)   │
│  복합 랭킹 = 인기순×0.5 + 리뷰수×0.3│
│              + 유사도×0.2           │
│  출력: 상위 10개 경쟁사              │
└─────────────────────────────────────┘
    │
    ▼ Step 6 (~30초)  ★ 매칭 후 상위만
┌─────────────────────────────────────┐
│  경쟁사 공식몰 교차검증              │
│  LG: lgelectronics.co.kr            │
│  기타: 네이버 브랜드스토어           │
│  보정 시 점수 재계산 + 랭킹 재정렬   │
└─────────────────────────────────────┘
    │
    ▼ Step 7 (<1초)
┌─────────────────────────────────────┐
│  최종 결과 출력                      │
│  UI: 삼성 카드 + 레이더 차트         │
│      경쟁사 비교 테이블              │
│  또는 CSV 행 추가 (배치 모드)        │
└─────────────────────────────────────┘

총 소요: ~2분
```

---

## 📏 핵심 룰셋 & 제약

### 채점 룰

| 항목 | 값 |
|------|-----|
| 필수 스펙 | 채점 제외 (필터링 용도만) |
| 출시년도 | 채점 제외 (표시 + ±2년 필터) |
| 등급 스펙 가중치 합 | **정확히 1.0** |
| 총점 범위 | **0 ~ 100점** |
| 정규화 방식 | Min-Max (같은 카테고리 내 상대 평가) |
| 설정 파일 | `rules/{category}.json` × 11개 |

### 크롤링 제약

| 항목 | 값 |
|------|-----|
| 요청 속도 | **1회/초 이하** (봇 차단 방지) |
| 모델 간 딜레이 | **5~10초** 랜덤 (배치) |
| 단건 분석 목표 | **2분 이내** |
| CSV 100개 목표 | **3~5시간** |

### 유사도 룰

| 항목 | 값 |
|------|-----|
| 알고리즘 | 코사인 유사도 |
| 임계값 | **≥ 0.75** |
| 최대 리스팅 | **10개** |
| 랭킹 공식 | `인기순×0.5 + 리뷰수×0.3 + 유사도×0.2` |

### 교차검증 상태

| 상태 | 의미 | 표시색 |
|------|------|--------|
| ✅ VERIFIED | 다나와 = 공식몰 일치 | 초록 |
| ⚠️ CORRECTED | 공식몰 기준으로 보정됨 | 노랑 |
| ❓ UNVERIFIED | 공식몰 미존재/검색 실패 | 회색 |

---

## 📦 대상 카테고리 11개

| # | 품목 | 필수 스펙 (필터) | 등급 스펙 (채점) |
|---|------|----------------|----------------|
| 1 | TV | 화면크기, 패널종류, 해상도 | 주사율, HDR, 스마트, 스피커출력, 돌비, 에너지등급, 디자인 |
| 2 | 냉장고 | 용량(L), 도어형태 | 에너지등급, 인버터, 냉각방식, 탈취/항균, 스마트, 소음 |
| 3 | 세탁기 | 용량(kg), 형태 | 에너지등급, 탈수RPM, 모드수, 스팀, 소음, 스마트 |
| 4 | 건조기 | 용량(kg), 방식 | 에너지등급, 모드수, 필터종류, 소음, 스마트 |
| 5 | 에어컨 | 냉방능력, 형태 | 에너지등급, 냉난방겸용, 필터, 소음, 풍량, 스마트 |
| 6 | 식기세척기 | 설치방식, 용량 | 에너지등급, 모드수, 건조방식, 소음, 스마트 |
| 7 | 공기청정기 | 적용면적, 필터 | CADR, 소음, 센서, 교체주기, 스마트 |
| 8 | 청소기 | 형태, 유무선 | 흡입력, 배터리, 먼지통, 소음, 부속품수 |
| 9 | 로봇청소기 | 흡입력(Pa), 물걸레 | 매핑방식, 배터리, 자동비움, 소음, 스마트 |
| 10 | 전자레인지 | 용량(L), 형태 | 출력(W), 모드수, 내부코팅, 에너지등급 |
| 11 | 모니터 | 화면크기, 패널, 해상도 | 주사율, 응답속도, HDR, 색재현율, 피벗, 스피커 |

---

## 🔌 API 엔드포인트

### 단건 분석

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/search` | 모델 검색 + 스펙 추출 |
| POST | `/api/verify` | 삼성 공식몰 교차검증 |
| POST | `/api/score` | 100점 채점 |
| POST | `/api/competitors` | 경쟁사 탐색 + 랭킹 |
| POST | `/api/competitors/verify` | 경쟁사 검증 |
| GET | `/api/rules/{category}` | 룰셋 조회 |

### 배치 처리

| Method | Endpoint | 설명 |
|--------|----------|------|
| POST | `/api/batch/upload` | CSV 업로드 → job_id 반환 |
| GET | `/api/batch/{job_id}/status` | 진행률 조회 |
| GET | `/api/batch/{job_id}/result` | 결과 CSV 다운로드 |
| POST | `/api/batch/{job_id}/resume` | 중단된 작업 재개 |
| DELETE | `/api/batch/{job_id}` | 작업 취소 |

---

## 🚀 실행 방법

```powershell
# 1. 가상환경 활성화
cd C:\WorkSpace\Coding\코딩\danawa-scraper
.\venv\Scripts\activate

# 2. 백엔드 서버 실행
cd backend
uvicorn main:app --reload --port 8000

# 3. 프론트엔드 접속
# 브라우저에서 http://localhost:8000 접속
# (FastAPI가 frontend/ 정적 파일 서빙)

# 4. Swagger 문서
# http://localhost:8000/docs
```

---

## ⚠️ 기술 리스크 & 대응

| 리스크 | 대응 |
|--------|------|
| 다나와 HTML 구조 변경 | `selectors/danawa.json`에 CSS Selector 분리 → 설정만 수정 |
| 다나와 IP 차단 | 딜레이 5~10초, UA 로테이션, Playwright stealth |
| 공식몰에 모델 미존재 | UNVERIFIED 처리 → 다나와 스펙 그대로 사용 |
| 스펙 텍스트 표기 불일치 | 정규식 + levels 매핑 + fallback 처리 |
| 배치 중 서버 종료 | 모델 1개 완료마다 체크포인트 JSON 저장 |

---

## ✅ 진척 현황

> 마지막 업데이트: 2026-04-16

### Phase 1 — 프로젝트 셋업 + TV 카테고리 파이프라인 ✅ 완료
- [x] 프로젝트 폴더 구조 생성
- [x] Python venv 생성 + requirements.txt 작성 + pip install
- [x] Playwright Chromium 브라우저 설치
- [x] FastAPI main.py 기본 서버 구축 (http://localhost:8000)
- [x] crawler.py — 다나와 모델 검색 + 스펙 추출 (TV)
- [x] spec_parser.py — 스펙 텍스트 정규화 (TV + 냉장고)
- [x] rules/tv.json — TV 채점 룰셋 (가중치 합 1.00)
- [x] scoring.py — 가중 점수 계산 엔진 (Min-Max 정규화)
- [x] similarity.py — 코사인 유사도 + 복합 랭킹
- [x] frontend/ — 프리미엄 다크 Glassmorphism UI (index.html + style.css + app.js)
- [x] 서버 실행 확인 (uvicorn -- port 8000)
- [ ] 단건 분석 E2E 테스트 (TV 모델 1개 실제 크롤링)

### Phase 2 — 삼성 공식몰 교차검증 ✅ 완료
- [x] official_malls/base_adapter.py — 추상 기본 어댑터 (Playwright stealth 공통 유틸 포함)
- [x] official_malls/samsung_adapter.py — 삼성 공식몰 어댑터 (다중 셀렉터 + dt/dd fallback)
- [x] official_malls/lg_adapter.py — LG 어댑터 stub (Phase 4 확장 예정)
- [x] official_malls/naver_store_adapter.py — 네이버 어댑터 stub (Phase 4 확장 예정)
- [x] verifier.py 리팩토링 — 어댑터 패턴 적용, 11개 카테고리 KEY_MAP 추가
- [x] selectors/samsung.json 개선 — 다중 CSS 셀렉터 fallback 배열 구조로 변경
- [x] 검증 결과 UI 표시 (✅⚠️❓) + 보정 항목 diff 목록 표시

### Phase 3 — 경쟁사 탐색 + 랭킹 완성 ✅ 완료
- [x] selectors/danawa.json — 카테고리 코드 매핑 11개 + 인기순 정렬 URL + 다중 셀렉터 배열
- [x] crawler.py — get_category_url() + _extract_release_year() + 출시년도 ±2년 필터 + 필수 스펙 필터 + 다중 셀렉터
- [x] main.py — category_url 자동 생성 + release_year 파라미터 + score_pool() 공정 채점
- [x] 경쟁사 비교 테이블 UI — 유사도 bar 시각화 + 총점 색상 chip (green/yellow/red) + 모델명 줄임

### Phase 4 — 경쟁사 공식몰 교차검증 ✅ 완료
- [x] official_malls/lg_adapter.py — LG전자몰(lge.co.kr) 크롤러 (다중 셀렉터 + dt/dd fallback)
- [x] official_malls/naver_store_adapter.py — 네이버 쇼핑 검색 크롤러 (th/td fallback)
- [x] selectors/lg.json — 다중 CSS 셀렉터 배열 구조로 개선
- [x] selectors/naver.json — 네이버 쇼핑 셀렉터 개선
- [x] main.py /api/competitors/verify — 검증 후 재채점(score_pool) + 재랭킹 적용
- [x] CompetitorVerifyRequest에 samsung_spec 추가
- [x] 검증 상태별 테이블 행 색조 (CORRECTED 노랑, VERIFIED 초록)

### Phase 5 — 11개 카테고리 확장 ✅ 완료
- [x] rules/ 11개 룰셋 JSON 이미 완비 (weight 합 1.00 전수 확인)
- [x] spec_parser.py — 9개 파서 추가 (washer, dryer, air_conditioner, dishwasher, air_purifier, vacuum, robot_vacuum, microwave, monitor)
- [x] _meta() 공통 헬퍼로 메타 스펙 중복 제거
- [x] 11개 카테고리 전수 검증: grading_spec 키 완전 매핑 확인

### Phase 6 — CSV 배치 처리 시스템 ✅ 완료
- [x] batch_processor.py 개선 — current_model·start_time 필드 추가, ETA 계산, 서버 재시작 시 RUNNING→PAUSED 복구
- [x] get_status() — current_model, eta_seconds, elapsed_sec, errors 목록(최근 10건) 반환
- [x] _export_csv() — breakdown 항목별 점수 열(score_*) + diffs + UTF-8 BOM 포함
- [x] 배치 UI 개선 — 현재 처리 모델명 pulse 애니메이션, ETA 표시, 에러 카운트/목록 토글

### Phase 7 — UI 폴리싱 + 최종 테스트 ✅ 완료

### 버그픽스 (2026-04-16) ✅ 완료
- [x] app.js `.then()` 콜백 `async` 누락 문법 오류 → 검색 버튼 완전 무반응 현상 수정
- [x] Windows Python 3.13 `asyncio.SelectorEventLoop` + Playwright `NotImplementedError` 해결
  - crawler.py / base_adapter.py: `ProactorEventLoop` 전용 스레드에서 Playwright 실행
- [x] `app.mount("/", StaticFiles(...))` 가 API 라우트를 가로채는 문제 → catch-all `GET /{path}` 라우트로 교체
- [x] 에러 응답 파싱 개선 (JSON/text 모두 처리, body stream 이중 소비 버그 수정)
- [x] 전역 예외 핸들러 + `/api/ping` 헬스체크 엔드포인트 추가

### 잔여 과제 (셀렉터 업데이트)
- [x] **삼성 공식몰 셀렉터** — `samsung.com/sec` HTML 구조 변경 대응 완료 (2026-04-16)
- [x] **다나와 경쟁사 목록 셀렉터** — `danawa.com` 제품 목록 페이지 HTML 구조 변경 대응 완료 (2026-04-16)
- [x] 레이더 차트 (SVG) — 그리드 레벨 라벨, 포인트별 점수 라벨, SVG `<title>` 툴팁, 애니메이션
- [x] 로딩 UX (단계별 진행 표시기) — ✓ 완료 표시, 그린 그래디언트 100%, connector .done
- [x] pytest 자동화 테스트 — 117 passed, 5 skipped (E2E), 0 failed
  - test_scoring.py: 룰셋 무결성(33개) + 파서(13개) + 채점 엔진(14개)
  - test_verifier.py: VerifyStatus + KEY_MAP + diff/apply + verify_samsung/competitor (mock)
  - test_batch.py: ModelItem + JobCheckpoint + BatchProcessor 상태관리/create_job/복구
  - test_e2e_crawler.py: get_category_url (3개 pass) + 크롤링 5개 skip (DANAWA_E2E=1 필요)
- [x] 전체 E2E 테스트 — get_category_url 11개 카테고리 URL 생성 확인 ✅

---

## 📝 작업 로그

| 날짜 | Phase | 작업 내용 |
|------|-------|---------|
| 2026-04-15 | 계획 | 구현 계획 v4 수립 (7단계 파이프라인, 11개 카테고리, 기술 스택 확정) |
| 2026-04-15 | Phase 1 | CLAUDE.md 생성, 폴더 구조 완성, venv+패키지 설치, Playwright Chromium 설치 |
| 2026-04-15 | Phase 1 | crawler.py, spec_parser.py, scoring.py, similarity.py, verifier.py, batch_processor.py, main.py 작성 |
| 2026-04-15 | Phase 1 | rules/ 11개 카테고리 룰셋 JSON, selectors/ 4개 JSON 작성 |
| 2026-04-15 | Phase 1 | frontend/ 다크 Glassmorphism UI (index.html + style.css + app.js) 완성 |
| 2026-04-15 | Phase 1 | FastAPI 서버 http://localhost:8000 정상 실행 확인 ✅ |
| 2026-04-16 | Phase 2 | official_malls/ 어댑터 패키지 생성 (base, samsung, lg stub, naver stub) |
| 2026-04-16 | Phase 2 | verifier.py 어댑터 패턴 리팩토링 + 11개 카테고리 KEY_MAP 추가 |
| 2026-04-16 | Phase 2 | selectors/samsung.json 다중 셀렉터 배열 구조로 개선 |
| 2026-04-16 | Phase 2 | 프론트엔드 검증 결과 UI — verify badge + diffs 목록 표시 완성 |
| 2026-04-16 | Phase 3 | selectors/danawa.json 카테고리 코드 매핑 + 인기순 URL + 다중 셀렉터 |
| 2026-04-16 | Phase 3 | crawler.py 전면 개선 — 출시년도 필터, 필수스펙 필터, get_category_url() |
| 2026-04-16 | Phase 3 | main.py — release_year 파라미터, score_pool() 공정 채점 적용 |
| 2026-04-16 | Phase 3 | 프론트엔드 경쟁사 테이블 — 유사도 bar, 총점 색상 chip, 자동 출시년도 추출 |
| 2026-04-16 | Phase 4 | lg_adapter.py, naver_store_adapter.py 구현 완료 |
| 2026-04-16 | Phase 4 | selectors/lg.json, selectors/naver.json 다중 셀렉터 배열 구조로 개선 |
| 2026-04-16 | Phase 4 | /api/competitors/verify 재채점+재랭킹 적용, 검증 상태별 행 색조 추가 |
| 2026-04-16 | Phase 5 | spec_parser.py — 9개 카테고리 파서 추가, 11개 전수 검증 OK |
| 2026-04-16 | Phase 6 | batch_processor.py — ETA, 현재 모델, 재시작 복구, breakdown CSV 출력 |
| 2026-04-16 | Phase 6 | 배치 UI — 현재 모델 pulse, ETA, 에러 목록 토글, 상태 chip 색상 |
| 2026-04-16 | Phase 7 | 레이더 차트 SVG 개선 — 그리드 라벨, 포인트 점수, 툴팁, 애니메이션 |
| 2026-04-16 | Phase 7 | 로딩 UX — 단계별 진행 표시기, ✓ 완료 표시, stepPulse 애니메이션 |
| 2026-04-16 | Phase 7 | pytest 자동화 테스트 완성 — 117 passed, 5 skipped (E2E), 0 failed |
| 2026-04-16 | Phase 7 | verifier.py 어댑터 모듈 레벨 import로 개선 (mock 테스트 호환성) |
| 2026-04-16 | Phase 7 | .claude/launch.json — dev 서버 설정 저장 |
| 2026-04-16 | 버그픽스 | app.js .then() async 누락 문법 오류 수정 → 검색 버튼 동작 복구 |
| 2026-04-16 | 버그픽스 | Windows asyncio.SelectorEventLoop + Playwright subprocess NotImplementedError 해결 |
| 2026-04-16 | 버그픽스 | app.mount("/", StaticFiles) → catch-all 라우트 교체 (API 라우트 우선순위 복구) |
| 2026-04-16 | 버그픽스 | base_adapter.py ProactorEventLoop 스레드 fix 적용 (Samsung/LG/Naver 어댑터 공통) |
| 2026-04-16 | E2E 확인 | 실서버 파이프라인 Step 1~5 전 구간 200 OK 확인 (KQ65QNH70AFXKR, KQ55SF8EAEXKR) |
