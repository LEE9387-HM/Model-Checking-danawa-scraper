# TV DB Operations

## Current Mode
- Collection mode: conservative cleaning
- Primary goal: maximize raw evidence capture while removing only obvious noise
- Persistence model:
  - `tv_products`: latest product snapshot
  - `tv_price_history`: append-only monthly history
  - `raw_specs`: source-of-truth payload for later re-normalization
  - `other_specs`: minimally filtered overflow specs

## Recommended Monthly Schedule
- Recommended run time: first day of each month at 03:00 Asia/Seoul
- Recommended command:
  - `powershell -ExecutionPolicy Bypass -File C:\WorkSpace\Coding\runners\Run-TVDBMonthly.ps1`
- Recommended mode:
  - normal monthly run: no `-Force`
  - retry after an interrupted run: `-Force`

## Recommended Preflight Before Long Runs
- Read-only scope estimate:
  - `.\venv\Scripts\python.exe .\backend\tv_db\crawler.py --preflight --preflight-sample-pages 5`
- Monthly runner estimate only:
  - `.\venv\Scripts\python.exe .\backend\tv_db\monthly_runner.py --preflight-only`
- Monthly runner estimate plus actual run:
  - `.\venv\Scripts\python.exe .\backend\tv_db\monthly_runner.py --preflight`
- Check:
  - estimated product count
  - estimated list-page count
  - optimistic/baseline/pessimistic ETA
  - estimated finish time before committing to the crawl

## Recommended Progress ETA During Long Runs
- Direct crawl with periodic ETA updates:
  - `.\venv\Scripts\python.exe .\backend\tv_db\crawler.py --progress-every 25`
- Monthly runner with periodic ETA updates:
  - `.\venv\Scripts\python.exe .\backend\tv_db\monthly_runner.py --preflight --progress-every 25`
- Progress output is emitted as:
  - saved product count
  - observed detail pages per minute
  - remaining ETA range
  - estimated finish time

## Calibration Without A Full Rerun
- If a long full crawl already finished once, register it as a calibration report:
  - `.\venv\Scripts\python.exe .\backend\tv_db\register_calibration_run.py --label 2026-04-22-full-crawl --started-at 2026-04-22T07:30:56+09:00 --ended-at 2026-04-22T11:19:33+09:00 --saved-count 1980`
- Registered calibration reports are stored under `backend/tv_db/monthly_runs/`.
- `--preflight` will automatically use the newest calibration report before falling back to the default throughput.

## Why Conservative Cleaning
- It removes only clear noise such as pricing blobs, "자세히보기", and content-rights footers.
- It keeps ambiguous values in `raw_specs` so later domain study can correct them without losing source evidence.
- It reduces the risk of inventing wrong mappings while the term system is still incomplete.

## Next Refinement Loop
1. Collect a few monthly snapshots under conservative mode.
2. Study repeated brand-specific labels and shifted value patterns.
3. Update `backend/tv_db/spec_glossary.template.json`.
4. Run `backend/tv_db/re_normalize.py` in preview mode.
5. Review the generated report before building any destructive normalization path.

## Suggested Windows Task Scheduler Setup
- Program/script:
  - `powershell.exe`
- Arguments:
  - `-ExecutionPolicy Bypass -File C:\WorkSpace\Coding\runners\Run-TVDBMonthly.ps1`
- Start in:
  - `C:\WorkSpace\Coding\코딩\danawa-scraper`

## Review Checklist
- Did the run create or update `backend/tv_db/tv_products.db`?
- Did `tv_price_history` append new rows instead of replacing existing history?
- Did the monthly run skip correctly when already completed for the month?
- Did the run report contain low or zero failed detail pages?
- Are suspicious values still preserved in `raw_specs` for later study?
