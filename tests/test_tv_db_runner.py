import json
from pathlib import Path

from datetime import datetime

from tv_db.crawler import (
    build_progress_estimate,
    compute_duplicate_rate,
    compute_observed_throughput,
    estimate_detail_fetches,
    estimate_eta_minutes,
    estimate_total_products,
    format_duration_minutes,
    iter_recent_run_reports,
    load_recent_throughput,
    normalize_limit,
    should_stop,
)
from tv_db.monthly_runner import MonthlyRunState, current_month_key, load_state, should_run_this_month


def test_normalize_limit_zero_means_unlimited():
    assert normalize_limit(0) is None
    assert normalize_limit(-1) is None
    assert normalize_limit(10) == 10


def test_should_stop_respects_unlimited():
    assert should_stop(100, None) is False
    assert should_stop(10, 10) is True
    assert should_stop(9, 10) is False


def test_current_month_key_format():
    key = current_month_key()
    assert len(key) == 7
    assert key[4] == "-"


def test_load_state_defaults_when_missing(tmp_path):
    state = load_state(tmp_path / "missing.json")
    assert state == MonthlyRunState()


def test_should_run_this_month_respects_force():
    state = MonthlyRunState(last_completed_month="2026-04")
    assert should_run_this_month(state, "2026-04", force=False) is False
    assert should_run_this_month(state, "2026-04", force=True) is True
    assert should_run_this_month(state, "2026-05", force=False) is True


def test_preflight_estimation_helpers():
    duplicate_rate = compute_duplicate_rate(raw_count=100, unique_count=92)
    assert duplicate_rate == 0.08

    estimated_products = estimate_total_products(estimated_list_pages=42, avg_products_per_page=30)
    assert estimated_products == 1260

    detail_fetches = estimate_detail_fetches(estimated_products, duplicate_rate)
    assert detail_fetches == 1159

    optimistic, baseline, pessimistic = estimate_eta_minutes(
        detail_fetches,
        detail_pages_per_minute=3.8,
        estimated_list_pages=42,
    )
    assert optimistic < baseline < pessimistic
    assert baseline > 0
    assert format_duration_minutes(baseline).endswith("m")


def test_load_recent_throughput_prefers_completed_reports(tmp_path):
    reports_dir = tmp_path / "monthly_runs"
    reports_dir.mkdir()
    report_path = reports_dir / "monthly-run-2026-04.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "started_at": "2026-04-22T00:00:00+09:00",
                "ended_at": "2026-04-22T01:00:00+09:00",
                "saved_count": 180,
            }
        ),
        encoding="utf-8",
    )

    throughput = load_recent_throughput(reports_dir)
    assert throughput.source == "monthly_runs"
    assert throughput.detail_pages_per_minute == 3.0


def test_load_recent_throughput_reads_calibration_reports(tmp_path):
    reports_dir = tmp_path / "monthly_runs"
    reports_dir.mkdir()
    report_path = reports_dir / "calibration-run-full-crawl.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "report_type": "calibration",
                "started_at": "2026-04-22T07:30:56+09:00",
                "ended_at": "2026-04-22T11:19:33+09:00",
                "saved_count": 1980,
            }
        ),
        encoding="utf-8",
    )

    reports = iter_recent_run_reports(reports_dir)
    assert report_path in reports

    throughput = load_recent_throughput(reports_dir)
    assert throughput.source == "calibration_runs"
    assert throughput.detail_pages_per_minute > 8.0


def test_progress_estimate_uses_observed_throughput():
    started_at = datetime.fromisoformat("2026-04-22T10:00:00+09:00")
    now = datetime.fromisoformat("2026-04-22T10:10:00+09:00")

    throughput = compute_observed_throughput(50, started_at=started_at, now=now)
    assert throughput == 5.0

    progress = build_progress_estimate(
        processed_candidates=50,
        estimated_total_candidates=200,
        started_at=started_at,
        now=now,
    )
    assert progress.remaining_candidates == 150
    assert progress.observed_detail_pages_per_minute == 5.0
    assert progress.eta_optimistic_minutes < progress.eta_baseline_minutes < progress.eta_pessimistic_minutes
