# TV DB Preflight And ETA Design

## Purpose
- Estimate crawl scope before starting a full TV DB run.
- Show an expected duration window before operators commit to a long crawl.
- Keep the estimation step read-only so it is safe to run before the main crawler.

## Why This Is Needed
- The full-category TV crawl can run for hours.
- Operators need early visibility into:
  - estimated product count
  - estimated list-page count
  - expected detail fetch volume
  - expected finish time
- The estimator should reduce surprises without changing crawl data.

## Non-Goals
- Do not write to `backend/tv_db/tv_products.db`.
- Do not modify `tv_price_history`.
- Do not perform destructive normalization.
- Do not guarantee an exact completion time.

## Proposed CLI Surface
- `crawler.py --preflight`
  - list-only estimation mode
  - exits after reporting estimated scope
- `crawler.py --preflight --output-json <path>`
  - same as above, plus machine-readable report
- `monthly_runner.py --preflight`
  - runs estimation first
  - prints ETA summary before the real monthly crawl starts
- `monthly_runner.py --preflight-only`
  - estimation only, no crawl

## Preflight Phases
1. Category discovery
- Open the TV category root.
- Detect reachable pagination count.
- Count visible product cards per page.
- Stop after either:
  - last page discovered
  - configured sampling cap reached

2. Product estimate
- Build an estimated total candidate count from sampled category pages.
- Track:
  - sampled pages
  - average candidates per page
  - min candidates per page
  - max candidates per page

3. Detail workload estimate
- Use estimated candidate count as the base detail-request volume.
- Subtract a small duplicate discount if duplicate `pcode` values are seen in the sample.
- Emit:
  - estimated detail fetches
  - duplicate-rate estimate

4. ETA estimate
- Use recent observed throughput if available.
- Fallback to static defaults if no recent run history exists.
- Return three ranges:
  - optimistic
  - baseline
  - pessimistic

## Throughput Inputs
- Preferred source:
  - recent monthly-run report files under `backend/tv_db/monthly_runs/`
- Secondary source:
  - lightweight run-state file, for example `monthly_runner_state.json`
- Fallback defaults:
  - list-page throughput default
  - detail-page throughput default

## Proposed Metrics
- `estimated_products`
- `estimated_list_pages`
- `sampled_pages`
- `avg_products_per_page`
- `duplicate_rate_estimate`
- `estimated_detail_fetches`
- `observed_detail_pages_per_minute`
- `eta_optimistic_minutes`
- `eta_baseline_minutes`
- `eta_pessimistic_minutes`
- `estimated_finish_time_kst`

## Suggested Output
```text
TV DB Preflight
Target products: 1240
List pages: 42
Sampled pages: 5
Estimated detail fetches: 1187
Observed throughput: 38 detail pages / 10 min
ETA:
  optimistic: 4h 50m
  baseline:   5h 30m
  pessimistic: 6h 40m
Estimated finish: 2026-04-22 15:40 KST
```

## JSON Report Shape
```json
{
  "mode": "preflight",
  "generated_at": "2026-04-22T09:30:00+09:00",
  "category_url": "https://prod.danawa.com/list/?cate=10248425",
  "sampled_pages": 5,
  "estimated_list_pages": 42,
  "estimated_products": 1240,
  "duplicate_rate_estimate": 0.043,
  "estimated_detail_fetches": 1187,
  "throughput_source": "monthly_runs",
  "observed_detail_pages_per_minute": 3.8,
  "eta_minutes": {
    "optimistic": 290,
    "baseline": 330,
    "pessimistic": 400
  },
  "estimated_finish_time_kst": "2026-04-22T15:40:00+09:00",
  "notes": [
    "Estimate only",
    "Detail-page timeout variance can widen the ETA band"
  ]
}
```

## Sampling Strategy
- Default sample:
  - first 3 pages
  - one mid-range page if pagination is large
  - last reachable page if cheap to resolve
- If pagination count cannot be known cheaply:
  - sample the first N pages
  - extrapolate from observed density
- Keep preflight faster than the main crawl by avoiding product-detail navigation.

## ETA Calculation Strategy
- Baseline:
  - `estimated_detail_fetches / observed_detail_pages_per_minute`
- Optimistic:
  - baseline reduced by 10 to 15 percent
- Pessimistic:
  - baseline increased by 20 to 30 percent
- Add a fixed overhead for:
  - browser startup
  - category-page traversal
  - intermittent retry cost

## Failure Handling
- If category sampling fails:
  - return `estimate_status=degraded`
  - emit only what was safely observed
- If no throughput history exists:
  - mark ETA as `default_based`
  - show the fallback assumption in notes
- If pagination shape changes:
  - prefer partial estimate over blocking the crawl

## Integration Plan
1. Add a read-only preflight mode to `backend/tv_db/crawler.py`.
2. Add ETA formatting helpers shared by `crawler.py` and `monthly_runner.py`.
3. Save optional JSON reports under `backend/tv_db/monthly_runs/`.
4. Print preflight summary before long runs.
5. Later, add in-run remaining ETA updates every N products.

## Guardrails While Current Crawl Is Running
- Do not edit `backend/tv_db/crawler.py` yet.
- Do not touch the live `tv_products.db` schema.
- Keep this design as documentation only until the current full crawl exits.
