from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_REPORTS_DIR = Path(__file__).resolve().parent / "monthly_runs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Register a completed crawl as a calibration run report")
    parser.add_argument("--reports-dir", default=str(DEFAULT_REPORTS_DIR))
    parser.add_argument("--label", required=True, help="short label for the calibration report filename")
    parser.add_argument("--started-at", required=True, help="ISO8601 datetime with timezone")
    parser.add_argument("--ended-at", required=True, help="ISO8601 datetime with timezone")
    parser.add_argument("--saved-count", type=int, required=True)
    parser.add_argument("--candidate-count", type=int, default=0)
    parser.add_argument("--pages-visited", type=int, default=0)
    parser.add_argument("--source-used", default="category")
    parser.add_argument("--notes", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"calibration-run-{args.label}.json"
    report = {
        "status": "completed",
        "report_type": "calibration",
        "label": args.label,
        "started_at": args.started_at,
        "ended_at": args.ended_at,
        "saved_count": max(0, args.saved_count),
        "candidate_count": max(0, args.candidate_count),
        "pages_visited": max(0, args.pages_visited),
        "source_used": args.source_used,
        "notes": args.notes,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "registered", "report_path": str(report_path.resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
