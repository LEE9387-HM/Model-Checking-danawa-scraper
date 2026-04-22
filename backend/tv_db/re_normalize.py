from __future__ import annotations

import argparse
import collections
import json
import sqlite3
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Iterable

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "tv_products.db"
DEFAULT_GLOSSARY_PATH = Path(__file__).resolve().parent / "spec_glossary.template.json"
DEFAULT_REPORT_PATH = Path(__file__).resolve().parent / "re_normalize_report.json"

KNOWN_OS_VALUES = {
    "Tizen",
    "webOS",
    "Google TV",
    "Android TV",
}

APPROVED_PREVIEW_RULE_NAMES = frozenset(
    {
        "AI음성인식->speaker_config",
        "AI음성인식->speaker_output",
        "AI음성인식->speaker_unit_count",
        "넷플릭스->speaker_config",
        "넷플릭스->speaker_output",
        "OS->speaker_config",
        "유튜브->speaker_config",
        "유튜브->speaker_output",
    }
)

COMPARISON_POLICY_RULE_NAMES = frozenset(
    {
        "AI음성인식->speaker_output",
        "넷플릭스->speaker_config",
        "OS->speaker_config",
        "유튜브->speaker_config",
        "유튜브->speaker_output",
    }
)


@dataclass(slots=True, frozen=True)
class ReassignmentRule:
    source_label: str
    target_label: str
    value_pattern: str

    @property
    def rule_name(self) -> str:
        return f"{self.source_label}->{self.target_label}"


@dataclass(slots=True)
class SuspiciousValue:
    model_name: str
    raw_label: str
    label: str
    value: str
    reason: str
    suggested_target_label: str | None = None


@dataclass(slots=True)
class ProposedReassignment:
    rule_name: str
    raw_label: str
    current_label: str
    value: str
    target_label: str
    applied: bool
    decision: str
    existing_value: str | None = None
    conflict_type: str | None = None


REASSIGNMENT_RULES: tuple[ReassignmentRule, ...] = (
    ReassignmentRule("voice_feature_or_shifted_value", "speaker_config", "channel"),
    ReassignmentRule("voice_feature_or_shifted_value", "speaker_output", "watts"),
    ReassignmentRule("voice_feature_or_shifted_value", "speaker_unit_count", "count"),
    ReassignmentRule("youtube_or_shifted_value", "speaker_config", "channel"),
    ReassignmentRule("youtube_or_shifted_value", "speaker_output", "watts"),
    ReassignmentRule("youtube_or_shifted_value", "speaker_unit_count", "count"),
    ReassignmentRule("netflix_or_shifted_value", "speaker_config", "channel"),
    ReassignmentRule("netflix_or_shifted_value", "speaker_output", "watts"),
    ReassignmentRule("netflix_or_shifted_value", "speaker_unit_count", "count"),
    ReassignmentRule("operating_system", "operating_system", "os_value"),
    ReassignmentRule("operating_system", "speaker_config", "channel"),
    ReassignmentRule("operating_system", "speaker_output", "watts"),
    ReassignmentRule("operating_system", "speaker_unit_count", "count"),
)


def load_glossary(path: str | Path) -> dict[str, Any]:
    glossary_path = Path(path)
    with open(glossary_path, encoding="utf-8") as file:
        return json.load(file)


def normalize_key(label: str, glossary: dict[str, Any]) -> str:
    aliases = glossary.get("label_aliases", {})
    return aliases.get(label, label)


def normalize_value(label: str, value: str, glossary: dict[str, Any]) -> str:
    value_aliases = glossary.get("value_aliases", {}).get(label, {})
    return value_aliases.get(value, value)


def is_suspicious(label: str, value: str, glossary: dict[str, Any]) -> str | None:
    for rule in glossary.get("suspicious_value_rules", []):
        if rule.get("label") != label:
            continue
        if value in rule.get("reject_exact", []):
            return rule.get("reason", "exact value rejected")
        if any(token in value for token in rule.get("contains_any", [])):
            return rule.get("reason", "value contains suspicious token")
    return None


def is_placeholder_value(value: str | None) -> bool:
    if value is None:
        return True
    normalized = value.strip()
    return normalized in {"", "○"}


def matches_value_pattern(pattern: str, value: str) -> bool:
    if pattern == "channel":
        return "채널" in value
    if pattern == "watts":
        return "W" in value
    if pattern == "count":
        return value.endswith("개")
    if pattern == "os_value":
        return value in KNOWN_OS_VALUES
    raise ValueError(f"Unsupported value pattern: {pattern}")


def iter_matching_rules(label: str, value: str) -> Iterable[ReassignmentRule]:
    for rule in REASSIGNMENT_RULES:
        if rule.source_label != label:
            continue
        if matches_value_pattern(rule.value_pattern, value):
            yield rule


def suggest_target_label(label: str, value: str) -> str | None:
    rule = next(iter(iter_matching_rules(label, value)), None)
    if rule is None:
        return None
    return rule.target_label


def value_type(value: str | None) -> str:
    if is_placeholder_value(value):
        return "placeholder"
    if value is None:
        return "unknown"
    if "채널" in value:
        return "channel"
    if "W" in value:
        return "watts"
    if value.endswith("개"):
        return "count"
    return "other"


def expected_value_type(target_label: str) -> str | None:
    if target_label == "speaker_config":
        return "channel"
    if target_label == "speaker_output":
        return "watts"
    if target_label == "speaker_unit_count":
        return "count"
    return None


def classify_target_slot(
    existing_value: str | None,
    incoming_value: str,
    *,
    rule_name: str,
    target_label: str,
) -> tuple[bool, str, str | None]:
    if is_placeholder_value(existing_value):
        return True, "filled_placeholder", None
    if existing_value == incoming_value:
        return True, "matched_existing", None
    expected_type = expected_value_type(target_label)
    incoming_type = value_type(incoming_value)
    existing_type = value_type(existing_value)
    if (
        rule_name in COMPARISON_POLICY_RULE_NAMES
        and expected_type is not None
        and incoming_type == expected_type
        and existing_type != expected_type
    ):
        return True, "replaced_misaligned_existing", None
    return False, "kept_existing_value", "target_has_different_value"


def apply_proposed_reassignments(
    normalized: dict[str, str],
    suspicious: list[tuple[str, str, str, str, str | None]],
    allowed_rule_names: frozenset[str] | None = None,
) -> tuple[dict[str, str], list[ProposedReassignment]]:
    proposed_preview = dict(normalized)
    reassignments: list[ProposedReassignment] = []

    for raw_label, current_label, value, _reason, suggested_target_label in suspicious:
        if not suggested_target_label:
            continue

        rule_name = f"{raw_label}->{suggested_target_label}"
        if allowed_rule_names is not None and rule_name not in allowed_rule_names:
            continue

        existing_value = proposed_preview.get(suggested_target_label)
        applied, decision, conflict_type = classify_target_slot(
            existing_value,
            value,
            rule_name=rule_name,
            target_label=suggested_target_label,
        )

        if applied and existing_value != value:
            proposed_preview[suggested_target_label] = value

        reassignments.append(
            ProposedReassignment(
                rule_name=rule_name,
                raw_label=raw_label,
                current_label=current_label,
                value=value,
                target_label=suggested_target_label,
                applied=applied,
                decision=decision,
                existing_value=existing_value,
                conflict_type=conflict_type,
            )
        )

    return proposed_preview, reassignments


def build_preview_record(
    raw_specs: dict[str, str],
    glossary: dict[str, Any],
) -> tuple[dict[str, str], list[tuple[str, str, str, str, str | None]]]:
    normalized: dict[str, str] = {}
    suspicious: list[tuple[str, str, str, str, str | None]] = []
    for raw_label, raw_value in raw_specs.items():
        normalized_label = normalize_key(raw_label, glossary)
        normalized_value = normalize_value(normalized_label, raw_value, glossary)
        normalized[normalized_label] = normalized_value
        reason = is_suspicious(normalized_label, normalized_value, glossary)
        if reason is not None:
            suspicious.append(
                (
                    raw_label,
                    normalized_label,
                    normalized_value,
                    reason,
                    suggest_target_label(normalized_label, normalized_value),
                )
            )
    return normalized, suspicious


def summarize_suspicious_values(suspicious_values: list[SuspiciousValue]) -> dict[str, Any]:
    by_label: collections.Counter[str] = collections.Counter()
    by_raw_label: collections.Counter[str] = collections.Counter()
    by_reason: collections.Counter[str] = collections.Counter()
    by_suggested_target: collections.Counter[str] = collections.Counter()
    examples_by_label: dict[str, list[dict[str, str]]] = {}

    for item in suspicious_values:
        by_label[item.label] += 1
        by_raw_label[item.raw_label] += 1
        by_reason[item.reason] += 1
        if item.suggested_target_label:
            by_suggested_target[item.suggested_target_label] += 1
        label_examples = examples_by_label.setdefault(item.label, [])
        if len(label_examples) < 5:
            label_examples.append(
                {
                    "model_name": item.model_name,
                    "raw_label": item.raw_label,
                    "value": item.value,
                    "reason": item.reason,
                    "suggested_target_label": item.suggested_target_label or "",
                }
            )

    return {
        "by_label": dict(by_label.most_common()),
        "by_raw_label": dict(by_raw_label.most_common()),
        "by_reason": dict(by_reason.most_common()),
        "by_suggested_target": dict(by_suggested_target.most_common()),
        "examples_by_label": examples_by_label,
    }


def build_rule_candidates(suspicious_values: list[SuspiciousValue]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[SuspiciousValue]] = {}
    for item in suspicious_values:
        if not item.suggested_target_label:
            continue
        key = (item.raw_label, item.label, item.suggested_target_label)
        grouped.setdefault(key, []).append(item)

    ranked: list[dict[str, Any]] = []
    for (raw_label, current_label, suggested_target_label), items in grouped.items():
        value_counter: collections.Counter[str] = collections.Counter(item.value for item in items)
        reason_counter: collections.Counter[str] = collections.Counter(item.reason for item in items)
        ranked.append(
            {
                "raw_label": raw_label,
                "current_label": current_label,
                "suggested_target_label": suggested_target_label,
                "count": len(items),
                "top_values": dict(value_counter.most_common(5)),
                "top_reasons": dict(reason_counter.most_common(3)),
                "sample_models": [item.model_name for item in items[:5]],
            }
        )

    ranked.sort(key=lambda item: item["count"], reverse=True)
    return ranked


def summarize_reassignments(
    preview: list[dict[str, Any]],
    field_name: str = "proposed_reassignments",
) -> dict[str, Any]:
    applied_by_target: collections.Counter[str] = collections.Counter()
    conflicts_by_target: collections.Counter[str] = collections.Counter()
    applied_by_rule: collections.Counter[str] = collections.Counter()
    conflicts_by_rule: collections.Counter[str] = collections.Counter()
    decisions: collections.Counter[str] = collections.Counter()
    conflicts_by_type: collections.Counter[str] = collections.Counter()

    for item in preview:
        for reassignment in item.get(field_name, []):
            target_label = reassignment.get("target_label", "")
            rule_name = reassignment.get("rule_name", "")
            decision = reassignment.get("decision", "")
            conflict_type = reassignment.get("conflict_type")
            if decision:
                decisions[decision] += 1
            if reassignment.get("applied"):
                if target_label:
                    applied_by_target[target_label] += 1
                if rule_name:
                    applied_by_rule[rule_name] += 1
                continue
            if target_label:
                conflicts_by_target[target_label] += 1
            if rule_name:
                conflicts_by_rule[rule_name] += 1
            if conflict_type:
                conflicts_by_type[conflict_type] += 1

    return {
        "applied_by_target": dict(applied_by_target.most_common()),
        "conflicts_by_target": dict(conflicts_by_target.most_common()),
        "applied_by_rule": dict(applied_by_rule.most_common()),
        "conflicts_by_rule": dict(conflicts_by_rule.most_common()),
        "decisions": dict(decisions.most_common()),
        "conflicts_by_type": dict(conflicts_by_type.most_common()),
    }


def summarize_proposed_reassignments(preview: list[dict[str, Any]]) -> dict[str, Any]:
    return summarize_reassignments(preview, field_name="proposed_reassignments")


def build_rule_effectiveness(preview: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for item in preview:
        for reassignment in item.get("proposed_reassignments", []):
            rule_name = reassignment.get("rule_name", "")
            if not rule_name:
                continue
            record = grouped.setdefault(
                rule_name,
                {
                    "rule_name": rule_name,
                    "target_label": reassignment.get("target_label", ""),
                    "total_count": 0,
                    "applied_count": 0,
                    "conflict_count": 0,
                    "decisions": collections.Counter(),
                    "conflict_types": collections.Counter(),
                    "sample_values": [],
                },
            )
            record["total_count"] += 1
            if reassignment.get("applied"):
                record["applied_count"] += 1
            else:
                record["conflict_count"] += 1
            decision = reassignment.get("decision")
            if decision:
                record["decisions"][decision] += 1
            conflict_type = reassignment.get("conflict_type")
            if conflict_type:
                record["conflict_types"][conflict_type] += 1
            value = reassignment.get("value", "")
            if value and value not in record["sample_values"] and len(record["sample_values"]) < 5:
                record["sample_values"].append(value)

    effectiveness: list[dict[str, Any]] = []
    for record in grouped.values():
        total_count = record["total_count"]
        effectiveness.append(
            {
                "rule_name": record["rule_name"],
                "target_label": record["target_label"],
                "total_count": total_count,
                "applied_count": record["applied_count"],
                "conflict_count": record["conflict_count"],
                "apply_rate": round(record["applied_count"] / total_count, 3) if total_count else 0.0,
                "decisions": dict(record["decisions"].most_common()),
                "conflict_types": dict(record["conflict_types"].most_common()),
                "sample_values": record["sample_values"],
            }
        )

    effectiveness.sort(
        key=lambda item: (
            item["apply_rate"],
            item["applied_count"],
            item["total_count"],
        ),
        reverse=True,
    )
    return effectiveness


def categorize_rule(effectiveness: dict[str, Any]) -> tuple[str, str]:
    total_count = effectiveness["total_count"]
    conflict_count = effectiveness["conflict_count"]
    applied_count = effectiveness["applied_count"]
    apply_rate = effectiveness["apply_rate"]

    if applied_count == 0:
        return "insufficient_signal", "no successful applications observed in preview"
    if conflict_count == 0 and applied_count >= 2:
        return "safe_to_promote", "applied cleanly in preview without conflicts"
    if conflict_count == 0 and applied_count == 1:
        return "promising_but_small_sample", "applied cleanly but only once in preview"
    if apply_rate >= 0.5:
        return "review_needed", "works in some rows but conflicts require priority rules"
    if conflict_count >= applied_count:
        return "conflict_heavy", "conflicts dominate over successful applications"
    if total_count < 2:
        return "insufficient_signal", "not enough observations to classify confidently"
    return "review_needed", "mixed results need manual review before promotion"


def build_rule_recommendations(rule_effectiveness: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)

    for item in rule_effectiveness:
        category, rationale = categorize_rule(item)
        grouped[category].append(
            {
                "rule_name": item["rule_name"],
                "target_label": item["target_label"],
                "total_count": item["total_count"],
                "applied_count": item["applied_count"],
                "conflict_count": item["conflict_count"],
                "apply_rate": item["apply_rate"],
                "rationale": rationale,
                "sample_values": item["sample_values"],
            }
        )

    preferred_order = [
        "safe_to_promote",
        "promising_but_small_sample",
        "review_needed",
        "conflict_heavy",
        "insufficient_signal",
    ]
    return {key: grouped.get(key, []) for key in preferred_order if grouped.get(key)}


def build_approved_rule_snapshot(rule_effectiveness: list[dict[str, Any]]) -> list[dict[str, Any]]:
    approved_snapshot: list[dict[str, Any]] = []
    for item in rule_effectiveness:
        if item["rule_name"] not in APPROVED_PREVIEW_RULE_NAMES:
            continue
        approved_snapshot.append(
            {
                "rule_name": item["rule_name"],
                "target_label": item["target_label"],
                "total_count": item["total_count"],
                "applied_count": item["applied_count"],
                "conflict_count": item["conflict_count"],
                "apply_rate": item["apply_rate"],
                "sample_values": item["sample_values"],
            }
        )
    approved_snapshot.sort(key=lambda item: (item["apply_rate"], item["applied_count"]), reverse=True)
    return approved_snapshot


def build_conflict_rule_analysis(preview: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for item in preview:
        model_name = item.get("model_name", "")
        for reassignment in item.get("proposed_reassignments", []):
            if reassignment.get("applied"):
                continue
            rule_name = reassignment.get("rule_name", "")
            if not rule_name:
                continue
            record = grouped.setdefault(
                rule_name,
                {
                    "rule_name": rule_name,
                    "target_label": reassignment.get("target_label", ""),
                    "conflict_count": 0,
                    "incoming_values": collections.Counter(),
                    "existing_values": collections.Counter(),
                    "existing_labels_by_value_type": collections.Counter(),
                    "sample_conflicts": [],
                },
            )
            record["conflict_count"] += 1
            incoming_value = reassignment.get("value", "")
            existing_value = reassignment.get("existing_value", "")
            if incoming_value:
                record["incoming_values"][incoming_value] += 1
            if existing_value:
                record["existing_values"][existing_value] += 1
                existing_type = "placeholder" if is_placeholder_value(existing_value) else "filled_value"
                record["existing_labels_by_value_type"][existing_type] += 1
            if len(record["sample_conflicts"]) < 5:
                record["sample_conflicts"].append(
                    {
                        "model_name": model_name,
                        "incoming_value": incoming_value,
                        "existing_value": existing_value,
                        "conflict_type": reassignment.get("conflict_type"),
                    }
                )

    analysis: list[dict[str, Any]] = []
    for record in grouped.values():
        conflict_count = record["conflict_count"]
        incoming_values = dict(record["incoming_values"].most_common(5))
        existing_values = dict(record["existing_values"].most_common(5))
        recurring_existing = max(record["existing_values"].values(), default=0)
        likely_duplicate = recurring_existing >= 2
        suggested_policy = (
            "compare_existing_vs_incoming"
            if likely_duplicate
            else "keep_existing_until_manual_rule"
        )
        analysis.append(
            {
                "rule_name": record["rule_name"],
                "target_label": record["target_label"],
                "conflict_count": conflict_count,
                "top_incoming_values": incoming_values,
                "top_existing_values": existing_values,
                "existing_value_types": dict(record["existing_labels_by_value_type"].most_common()),
                "likely_duplicate_conflicts": likely_duplicate,
                "suggested_policy": suggested_policy,
                "sample_conflicts": record["sample_conflicts"],
            }
        )

    analysis.sort(key=lambda item: item["conflict_count"], reverse=True)
    return analysis


def summarize_remaining_work(
    rule_recommendations: dict[str, list[dict[str, Any]]],
    conflict_analysis: list[dict[str, Any]],
) -> dict[str, Any]:
    safe_rules = rule_recommendations.get("safe_to_promote", [])
    conflict_rules = rule_recommendations.get("conflict_heavy", [])
    comparable_conflicts = [
        item["rule_name"]
        for item in conflict_analysis
        if item["suggested_policy"] == "compare_existing_vs_incoming"
    ]
    manual_conflicts = [
        item["rule_name"]
        for item in conflict_analysis
        if item["suggested_policy"] == "keep_existing_until_manual_rule"
    ]
    return {
        "approved_rule_count": len(safe_rules),
        "remaining_conflict_rule_count": len(conflict_rules),
        "remaining_conflict_rules": [item["rule_name"] for item in conflict_rules],
        "conflict_rules_with_comparison_policy_candidates": comparable_conflicts,
        "conflict_rules_still_manual_review": manual_conflicts,
    }


def list_supported_rules() -> list[dict[str, str]]:
    return [
        {
            "rule_name": rule.rule_name,
            "source_label": rule.source_label,
            "target_label": rule.target_label,
            "value_pattern": rule.value_pattern,
        }
        for rule in REASSIGNMENT_RULES
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview later-stage TV spec normalization")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--glossary-path", default=str(DEFAULT_GLOSSARY_PATH))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--limit", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    glossary = load_glossary(args.glossary_path)
    connection = sqlite3.connect(args.db_path)
    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute(
            """
            SELECT model_name, raw_specs, other_specs
            FROM tv_products
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()

        preview: list[dict[str, Any]] = []
        suspicious_values: list[SuspiciousValue] = []
        for row in rows:
            raw_specs = json.loads(row["raw_specs"])
            normalized, suspicious = build_preview_record(raw_specs, glossary)
            approved_preview, approved_reassignments = apply_proposed_reassignments(
                normalized,
                suspicious,
                allowed_rule_names=APPROVED_PREVIEW_RULE_NAMES,
            )
            proposed_preview, proposed_reassignments = apply_proposed_reassignments(normalized, suspicious)
            preview.append(
                {
                    "model_name": row["model_name"],
                    "normalized_preview": normalized,
                    "approved_normalized_preview": approved_preview,
                    "approved_reassignments": [asdict(item) for item in approved_reassignments],
                    "proposed_normalized_preview": proposed_preview,
                    "proposed_reassignments": [asdict(item) for item in proposed_reassignments],
                    "raw_spec_count": len(raw_specs),
                }
            )
            for raw_label, label, value, reason, suggested_target_label in suspicious:
                suspicious_values.append(
                    SuspiciousValue(
                        model_name=row["model_name"],
                        raw_label=raw_label,
                        label=label,
                        value=value,
                        reason=reason,
                        suggested_target_label=suggested_target_label,
                    )
                )

        rule_effectiveness = build_rule_effectiveness(preview)
        rule_recommendations = build_rule_recommendations(rule_effectiveness)
        conflict_analysis = build_conflict_rule_analysis(preview)
        report = {
            "db_path": str(Path(args.db_path).resolve()),
            "glossary_path": str(Path(args.glossary_path).resolve()),
            "preview_count": len(preview),
            "suspicious_count": len(suspicious_values),
            "approved_preview_rules": sorted(APPROVED_PREVIEW_RULE_NAMES),
            "supported_reassignment_rules": list_supported_rules(),
            "preview": preview[:20],
            "suspicious_values": [asdict(item) for item in suspicious_values[:100]],
            "suspicious_summary": summarize_suspicious_values(suspicious_values),
            "rule_candidates": build_rule_candidates(suspicious_values)[:20],
            "approved_reassignment_summary": summarize_reassignments(preview, field_name="approved_reassignments"),
            "proposed_reassignment_summary": summarize_proposed_reassignments(preview),
            "rule_effectiveness": rule_effectiveness[:20],
            "rule_recommendations": rule_recommendations,
            "approved_rule_snapshot": build_approved_rule_snapshot(rule_effectiveness),
            "conflict_rule_analysis": conflict_analysis[:20],
            "remaining_work_summary": summarize_remaining_work(rule_recommendations, conflict_analysis),
            "notes": [
                "This script is intentionally non-destructive.",
                "approved_normalized_preview applies only the currently approved preview rules.",
                "proposed_normalized_preview still shows the broader candidate rule set for review.",
                "Current conflict policy keeps the existing value when the target label already has a different non-placeholder value.",
            ],
        }
        Path(args.report_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
