from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tv_db.crawler import (
        DEFAULT_DB_PATH,
        DEFAULT_PREFLIGHT_SAMPLE_PAGES,
        DEFAULT_REPORTS_DIR,
        crawl_tv_database,
        format_duration_minutes,
        run_in_event_loop,
        run_preflight_estimate,
    )
    from tv_db.db_manager import TVDatabaseManager, utc_now_iso
else:
    from tv_db.crawler import (
        DEFAULT_DB_PATH,
        DEFAULT_PREFLIGHT_SAMPLE_PAGES,
        DEFAULT_REPORTS_DIR,
        crawl_tv_database,
        format_duration_minutes,
        run_in_event_loop,
        run_preflight_estimate,
    )
    from tv_db.db_manager import TVDatabaseManager, utc_now_iso

DEFAULT_STATE_PATH = Path(__file__).resolve().parent / "monthly_runner_state.json"


@dataclass(slots=True)
class MonthlyRunState:
    last_completed_month: str | None = None
    last_completed_at: str | None = None
    last_report_path: str | None = None


def current_month_key(now: datetime | None = None) -> str:
    dt = now or datetime.now().astimezone()
    return f"{dt.year:04d}-{dt.month:02d}"


def load_state(path: str | Path) -> MonthlyRunState:
    state_path = Path(path)
    if not state_path.exists():
        return MonthlyRunState()
    data = json.loads(state_path.read_text(encoding="utf-8"))
    return MonthlyRunState(**data)


def save_state(path: str | Path, state: MonthlyRunState) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(asdict(state), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def should_run_this_month(state: MonthlyRunState, month_key: str, force: bool) -> bool:
    if force:
        return True
    return state.last_completed_month != month_key


def fetch_db_counts(db_path: str | Path) -> dict[str, int]:
    manager = TVDatabaseManager(db_path)
    try:
        manager.initialize()
        return manager.fetch_summary_counts()
    finally:
        manager.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the monthly TV DB crawl")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORTS_DIR))
    parser.add_argument("--preflight", action="store_true", help="print a scope/ETA estimate before the crawl starts")
    parser.add_argument("--preflight-only", action="store_true", help="estimate scope/ETA and exit without crawling")
    parser.add_argument("--preflight-sample-pages", type=int, default=DEFAULT_PREFLIGHT_SAMPLE_PAGES)
    parser.add_argument("--query", default="TV")
    parser.add_argument("--max-items", type=int, default=0, help="0 means no item cap")
    parser.add_argument("--max-pages", type=int, default=0, help="0 means auto-pagination")
    parser.add_argument("--detail-retries", type=int, default=2)
    parser.add_argument("--detail-timeout-ms", type=int, default=45000)
    parser.add_argument("--max-empty-pages", type=int, default=1)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    month_key = current_month_key()
    state = load_state(args.state_path)

    preflight_payload = None
    if args.preflight or args.preflight_only:
        preflight = run_in_event_loop(
            run_preflight_estimate(
                max_pages=args.max_pages,
                reports_dir=args.reports_dir,
                sample_pages=args.preflight_sample_pages,
            )
        )
        preflight_payload = {
            "status": "preflight",
            "month_key": month_key,
            "estimated_products": preflight.estimated_products,
            "estimated_list_pages": preflight.estimated_list_pages,
            "estimated_detail_fetches": preflight.estimated_detail_fetches,
            "throughput_source": preflight.throughput_source,
            "observed_detail_pages_per_minute": preflight.observed_detail_pages_per_minute,
            "eta_minutes": {
                "optimistic": preflight.eta_optimistic_minutes,
                "baseline": preflight.eta_baseline_minutes,
                "pessimistic": preflight.eta_pessimistic_minutes,
            },
            "eta_human": {
                "optimistic": format_duration_minutes(preflight.eta_optimistic_minutes),
                "baseline": format_duration_minutes(preflight.eta_baseline_minutes),
                "pessimistic": format_duration_minutes(preflight.eta_pessimistic_minutes),
            },
            "estimated_finish_time_kst": preflight.estimated_finish_time_kst,
            "estimate_status": preflight.estimate_status,
            "notes": preflight.notes,
        }
        print(json.dumps(preflight_payload, ensure_ascii=False, indent=2))
        if args.preflight_only:
            return 0

    if not should_run_this_month(state, month_key, args.force):
        payload = {
            "status": "skipped",
            "reason": "already_completed_this_month",
            "month_key": month_key,
            "last_completed_at": state.last_completed_at,
            "last_report_path": state.last_report_path,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    started_at = utc_now_iso()
    run = run_in_event_loop(
        crawl_tv_database(
            db_path=args.db_path,
            max_items=args.max_items,
            max_pages=args.max_pages,
            brand_keywords=[],
            release_year=None,
            search_query=args.query,
            detail_retries=args.detail_retries,
            detail_timeout_ms=args.detail_timeout_ms,
            max_empty_pages=max(1, args.max_empty_pages),
            progress_every=max(0, args.progress_every),
            progress_enabled=args.progress_every > 0,
        )
    )
    ended_at = utc_now_iso()

    counts = fetch_db_counts(args.db_path)
    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"monthly-run-{month_key}.json"
    report = {
        "status": "completed",
        "month_key": month_key,
        "started_at": started_at,
        "ended_at": ended_at,
        "db_path": str(Path(args.db_path).resolve()),
        "saved_count": len(run.results),
        "failed_count": len(run.failures),
        "candidate_count": run.candidates_seen,
        "pages_visited": run.pages_visited,
        "source_used": run.source_used,
        "preflight": preflight_payload,
        "progress_updates": run.progress_updates[-10:],
        "db_counts": counts,
        "sample_items": [asdict(result) for result in run.results[:5]],
        "failures": [asdict(failure) for failure in run.failures[:20]],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    save_state(
        args.state_path,
        MonthlyRunState(
            last_completed_month=month_key,
            last_completed_at=ended_at,
            last_report_path=str(report_path.resolve()),
        ),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
