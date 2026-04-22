# Phase 3 아키텍처 설계 — 삼성 TV 가격 경쟁력 평가 엔진

> 작성: claude-leader | 2026-04-22

---

## 1. 목표

`tv_products.db` (약 1,900건)를 활용하여 특정 삼성 TV 모델에 대해:
1. 스펙 체급이 가장 가까운 타사 경쟁 모델 1~5개를 탐색
2. 연식 감가상각을 반영한 가격 정규화 후 CPI 산출
3. 삼성 제품의 현행 가격 책정이 시장에서 경쟁력 있는지 종합 판정

---

## 2. 신규 파일 목록

```
backend/tv_db/
├── depreciation.py     ← 감가상각 가중치/가격 정규화 순수 함수
├── match_engine.py     ← DB 조회 → 필터 → 채점 → 랭킹 → 평가 파이프라인
└── tv_matching.py      ← CLI 진입점 + 터미널/JSON 출력 포매터

tests/
└── test_tv_matching.py ← 단위 테스트 (최소 8개 케이스)
```

### 기존 재사용 파일 (수정 없음)

| 파일 | 재사용 방식 |
|------|------------|
| `backend/scoring.py` | `score_pool()` — 동일 풀 기반 100점 채점 |
| `backend/price_intelligence.py` | `get_price_adequacy_verdict()` — 7단계 판정 |
| `backend/similarity.py` | `cosine_similarity()` — 스펙 벡터 유사도 |
| `backend/rules/tv.json` | grading_specs 가중치 기준 |
| `backend/tv_db/db_manager.py` | `TVDatabaseManager` — SQLite 조회 |

---

## 3. 데이터 플로우

```
[CLI] python tv_matching.py --target "QN65QN90D" --top 5
         │
         ▼
[1] find_samsung_model(db, query)
    → tv_products WHERE manufacturer='삼성전자' AND model_name LIKE '%query%'
    → 없으면 "모델을 찾을 수 없음" 오류 출력 후 종료
         │
         ▼
[2] find_candidates(db, samsung_row, size_tol=3.0, max_year_delta=2)
    필터 조건 (AND):
    ① brand NOT LIKE '%삼성%' AND manufacturer != '삼성전자'
    ② ABS(screen_size_inch - target_size) <= 3.0
    ③ resolution = target_resolution (동일 티어만)
    ④ ABS(release_year - target_year) <= 2
    ⑤ current_price > 0
         │
         ▼
[3] score_candidates(samsung_row, candidate_rows)
    → row_to_spec() 로 DB 컬럼 → scoring 스펙 dict 변환
    → score_pool("tv", [삼성 + 경쟁사 전체]) 로 동일 풀 채점
    → 각 row에 "score" 키 추가
         │
         ▼
[4] rank_candidates(samsung_scored, candidates_scored, top_n=5)
    매칭 점수 공식:
      match_score =
        cosine_similarity(samsung_spec_vec, comp_spec_vec) × 0.40
        + year_proximity_weight(sam_year, comp_year)        × 0.35
        + size_closeness                                    × 0.15
        + (1.0 if panel_type 일치 else 0.0)               × 0.10

    size_closeness = 1.0 - abs(comp_size - sam_size) / 3.0  (하한 0.0)
    → 상위 top_n개 반환
         │
         ▼
[5] evaluate_competitiveness(samsung_scored, top_candidates)
    각 경쟁사에 대해:
      raw_cpi      = (samsung_price / comp_price) × 100
      adj_price    = depreciation_adjusted_price(comp_price, sam_year, comp_year)
      adjusted_cpi = (samsung_price / adj_price) × 100
      score_diff   = samsung_total_score - comp_total_score
      verdict      = get_price_adequacy_verdict(adjusted_cpi, score_diff)

    종합 판정:
      weighted_cpi = Σ(adj_cpi × match_score) / Σ(match_score)
      OVERPRICED   : weighted_cpi > 115
      SLIGHT_HIGH  : 105 < weighted_cpi ≤ 115
      FAIR         : 95  < weighted_cpi ≤ 105
      GOOD_VALUE   : 85  < weighted_cpi ≤ 95
      COMPETITIVE  : weighted_cpi ≤ 85
         │
         ▼
[6] 출력
    --json  : JSON stdout
    (기본값): 터미널 테이블 (구분선 + 색상 없는 텍스트)
```

---

## 4. 감가상각 모델 상세

### 핵심 가정

- **연간 잔존가치율**: 85% (15% 연간 가치 감소)
- **최대 비교 허용 연식 차이**: ±2년

### 연식 근접성 가중치 (매칭 점수용)

| year_delta | weight |
|-----------|--------|
| 0 (동일 연도) | 1.00 |
| ±1년 | 0.70 |
| ±2년 | 0.40 |
| ±3년 이상 | 0.00 (매칭 제외) |

### 가격 정규화 공식 (CPI 평가용)

```
year_delta = competitor_year - samsung_year

경쟁사가 구형 (year_delta < 0):
  adjusted_price = competitor_price / (0.85 ^ |year_delta|)
  해석: 구형 모델은 이미 시장에서 할인가 → 삼성 연도 기준으로 환산하면 더 비싼 가격

경쟁사가 신형 (year_delta > 0):
  adjusted_price = competitor_price × (0.85 ^ year_delta)
  해석: 신형 프리미엄 제거 → 삼성 연도 기준으로 환산하면 더 저렴한 가격

동일 연도 (year_delta = 0):
  adjusted_price = competitor_price
```

### 예시

| 케이스 | 삼성 | 경쟁사 | 원가 CPI | 보정 CPI | 해석 |
|--------|------|--------|---------|---------|------|
| 동일 연도 | 2024년 1,500,000원 | 2024년 1,200,000원 | 125 | 125 | 삼성 25% 고가 |
| 경쟁사 1년 구형 | 2024년 1,500,000원 | 2023년 1,200,000원 | 125 | 106 | 연식 보정 후 6% 고가 |
| 경쟁사 1년 신형 | 2024년 1,500,000원 | 2025년 1,800,000원 | 83 | 98 | 연식 보정 후 거의 동등 |

---

## 5. DB 컬럼 → 스펙 딕셔너리 매핑

`scoring.py`의 `grading_specs` 키와 DB 필드 간 매핑:

| scoring 키 | DB 소스 | 설명 |
|-----------|---------|------|
| `refresh_rate` | `refresh_rate_hz` (float) | 주사율 Hz |
| `hdr` | `other_specs["hdr"]` | HDR 등급 문자열 |
| `smart_features` | `other_specs["smart_features"]` | 스마트 기능 등급 |
| `speaker_output` | `other_specs["speaker_output"]` | 스피커 출력 W |
| `dolby_atmos` | `other_specs["dolby_atmos"]` | bool |
| `energy_rating` | `other_specs["energy_rating"]` | 에너지 등급 문자열 |
| `design_thinness` | `other_specs["design_thinness"]` | 두께 mm |

---

## 6. CLI 출력 예시

### 터미널 모드 (기본)

```
═══════════════════════════════════════════════════════════
  삼성 TV 가격 경쟁력 평가 리포트
═══════════════════════════════════════════════════════════
  [기준] QN65QN90DAAFXKR  (2024 | 65인치 | 4K | Neo QLED)
  스펙점수: 87.4/100  |  현재가: 2,350,000원

  ─── 경쟁 모델 매칭 결과 ──────────────────────────────────
  순위  브랜드  모델                  연도  가격         매칭점수  CPI(보정)  판정
  ────  ──────  ──────────────────    ────  ──────────   ────────  ─────────  ──────
  #1    LG      OLED65C4KNA           2024  2,180,000원  0.923     107.8      가격 열세
  #2    LG      OLED65C3KNA           2023  1,890,000원  0.847     105.7      가격 평형
  #3    소니    XR-65A80L             2023  2,050,000원  0.812     101.3      가격 평형
  #4    TCL     65C845K               2024  1,650,000원  0.761     142.4      과항 고가
  #5    하이센스 65U8N                 2024  1,720,000원  0.734     136.6      고가 프리미엄

  ─── 종합 경쟁력 평가 ─────────────────────────────────────
  가중 평균 CPI (감가보정): 108.2
  최종 판정: SLIGHT_HIGH  ★★★☆☆
  요약: 삼성 QN65QN90D는 동급 경쟁사 대비 약 8.2% 고가 책정.
        LG/소니 고급형 대비 프리미엄 수준은 스펙 우위로 일부 정당화되나,
        TCL/하이센스 대비 가격 경쟁력 열위.
═══════════════════════════════════════════════════════════
```

### JSON 모드 (`--json`)

```json
{
  "samsung": {
    "model_name": "QN65QN90DAAFXKR",
    "year": 2024,
    "price": 2350000,
    "score": 87.4,
    "size_inch": 65.0,
    "resolution": "4K",
    "panel_type": "Neo QLED"
  },
  "matches": [...],
  "aggregate": {
    "weighted_cpi": 108.2,
    "overall_verdict": "SLIGHT_HIGH",
    "summary": "..."
  }
}
```

---

## 7. 테스트 전략

| # | 테스트 | 방식 |
|---|--------|------|
| 1 | `year_proximity_weight()` 경계값 | 순수 함수 단위 테스트 |
| 2 | `depreciation_adjusted_price()` 3케이스 | 순수 함수 단위 테스트 |
| 3 | `row_to_spec()` 매핑 | mock dict 입력 |
| 4 | `find_candidates()` 필터 | SQLite in-memory DB |
| 5 | 연식 ±2 경계 확인 | SQLite in-memory DB |
| 6 | `rank_candidates()` 동년도 우선 | mock 데이터 |
| 7 | `evaluate_competitiveness()` 판정 | mock scored data |
| 8 | CLI --json 출력 스키마 | subprocess + json.loads |
| (E2E) | 실제 DB 스모크 | `DANAWA_E2E=1` 환경변수 |

---

## 8. 기존 테스트 회귀 체크리스트

구현 완료 후 반드시 확인:

```bash
python -m pytest tests/ -v --ignore=tests/test_e2e_crawler.py
# 기존 117 passed 유지 + test_tv_matching.py N passed 추가
```
