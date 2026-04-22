from tv_db.re_normalize import (
    APPROVED_PREVIEW_RULE_NAMES,
    SuspiciousValue,
    apply_proposed_reassignments,
    build_approved_rule_snapshot,
    build_conflict_rule_analysis,
    build_preview_record,
    build_rule_candidates,
    build_rule_effectiveness,
    build_rule_recommendations,
    summarize_remaining_work,
    categorize_rule,
    classify_target_slot,
    is_placeholder_value,
    iter_matching_rules,
    normalize_key,
    normalize_value,
    value_type,
    suggest_target_label,
    summarize_proposed_reassignments,
    summarize_reassignments,
    summarize_suspicious_values,
)


def test_normalize_key_uses_glossary_alias():
    glossary = {"label_aliases": {"OS": "operating_system"}}
    assert normalize_key("OS", glossary) == "operating_system"
    assert normalize_key("해상도", glossary) == "해상도"


def test_normalize_value_uses_value_alias():
    glossary = {"value_aliases": {"operating_system": {"타이젠": "Tizen"}}}
    assert normalize_value("operating_system", "타이젠", glossary) == "Tizen"
    assert normalize_value("operating_system", "webOS", glossary) == "webOS"


def test_build_preview_record_collects_suspicious_values():
    glossary = {
        "label_aliases": {"OS": "operating_system"},
        "value_aliases": {"operating_system": {"타이젠": "Tizen"}},
        "suspicious_value_rules": [
            {"label": "operating_system", "reject_exact": ["○"], "reason": "invalid os marker"}
        ],
    }
    normalized, suspicious = build_preview_record({"OS": "○", "해상도": "4K UHD"}, glossary)
    assert normalized["operating_system"] == "○"
    assert normalized["해상도"] == "4K UHD"
    assert suspicious == [("OS", "operating_system", "○", "invalid os marker", None)]


def test_iter_matching_rules_returns_expected_targets():
    channel_rules = list(iter_matching_rules("youtube_or_shifted_value", "2.0채널"))
    assert [rule.target_label for rule in channel_rules] == ["speaker_config"]

    watt_rules = list(iter_matching_rules("voice_feature_or_shifted_value", "20W"))
    assert [rule.target_label for rule in watt_rules] == ["speaker_output"]

    count_rules = list(iter_matching_rules("voice_feature_or_shifted_value", "4개"))
    assert [rule.target_label for rule in count_rules] == ["speaker_unit_count"]


def test_suggest_target_label_maps_shifted_speaker_values():
    assert suggest_target_label("youtube_or_shifted_value", "20W") == "speaker_output"
    assert suggest_target_label("voice_feature_or_shifted_value", "2.0채널") == "speaker_config"
    assert suggest_target_label("voice_feature_or_shifted_value", "4개") == "speaker_unit_count"
    assert suggest_target_label("operating_system", "Tizen") == "operating_system"


def test_classify_target_slot_handles_placeholder_match_and_conflict():
    assert classify_target_slot("○", "2.0채널", rule_name="유튜브->speaker_config", target_label="speaker_config") == (
        True,
        "filled_placeholder",
        None,
    )
    assert classify_target_slot("20W", "20W", rule_name="유튜브->speaker_output", target_label="speaker_output") == (
        True,
        "matched_existing",
        None,
    )
    assert classify_target_slot("40W", "20W", rule_name="유튜브->speaker_output", target_label="speaker_output") == (
        False,
        "kept_existing_value",
        "target_has_different_value",
    )


def test_classify_target_slot_can_replace_misaligned_existing_value():
    assert classify_target_slot(
        "3개",
        "20W",
        rule_name="AI음성인식->speaker_output",
        target_label="speaker_output",
    ) == (True, "replaced_misaligned_existing", None)
    assert value_type("4개") == "count"


def test_apply_proposed_reassignments_fills_placeholder_targets():
    normalized = {
        "youtube_or_shifted_value": "2.0채널",
        "speaker_config": "○",
    }
    suspicious = [
        ("유튜브", "youtube_or_shifted_value", "2.0채널", "shifted", "speaker_config"),
    ]
    proposed_preview, reassignments = apply_proposed_reassignments(normalized, suspicious)
    assert proposed_preview["speaker_config"] == "2.0채널"
    assert reassignments[0].applied is True
    assert reassignments[0].decision == "filled_placeholder"
    assert reassignments[0].rule_name == "유튜브->speaker_config"
    assert is_placeholder_value("○") is True


def test_apply_proposed_reassignments_can_filter_to_approved_rules():
    normalized = {
        "voice_feature_or_shifted_value": "2.0채널",
        "netflix_or_shifted_value": "20W",
        "operating_system": "2.0채널",
        "speaker_config": "○",
        "speaker_output": "○",
    }
    suspicious = [
        ("AI음성인식", "voice_feature_or_shifted_value", "2.0채널", "shifted", "speaker_config"),
        ("넷플릭스", "netflix_or_shifted_value", "20W", "shifted", "speaker_output"),
        ("유튜브", "youtube_or_shifted_value", "2.0채널", "shifted", "speaker_config"),
        ("OS", "operating_system", "2.0채널", "shifted", "speaker_config"),
    ]
    approved_preview, approved_reassignments = apply_proposed_reassignments(
        normalized,
        suspicious,
        allowed_rule_names=APPROVED_PREVIEW_RULE_NAMES,
    )
    assert approved_preview["speaker_config"] == "2.0채널"
    assert approved_preview["speaker_output"] == "20W"
    assert [item.rule_name for item in approved_reassignments] == [
        "AI음성인식->speaker_config",
        "넷플릭스->speaker_output",
        "유튜브->speaker_config",
        "OS->speaker_config",
    ]


def test_apply_proposed_reassignments_tracks_conflicts():
    normalized = {
        "voice_feature_or_shifted_value": "20W",
        "speaker_output": "40W",
    }
    suspicious = [
        ("AI음성인식", "voice_feature_or_shifted_value", "20W", "shifted", "speaker_output"),
    ]
    proposed_preview, reassignments = apply_proposed_reassignments(normalized, suspicious)
    assert proposed_preview["speaker_output"] == "40W"
    assert reassignments[0].applied is False
    assert reassignments[0].decision == "kept_existing_value"
    assert reassignments[0].rule_name == "AI음성인식->speaker_output"
    assert reassignments[0].conflict_type == "target_has_different_value"
    assert reassignments[0].existing_value == "40W"


def test_summarize_suspicious_values_groups_by_label_and_reason():
    suspicious = [
        SuspiciousValue(model_name="A", raw_label="OS", label="operating_system", value="○", reason="invalid os marker"),
        SuspiciousValue(
            model_name="B",
            raw_label="OS",
            label="operating_system",
            value="20W",
            reason="invalid os marker",
            suggested_target_label="speaker_output",
        ),
        SuspiciousValue(
            model_name="C",
            raw_label="유튜브",
            label="voice_feature_or_shifted_value",
            value="2.0채널",
            reason="shifted speaker",
            suggested_target_label="speaker_config",
        ),
    ]
    summary = summarize_suspicious_values(suspicious)
    assert summary["by_label"]["operating_system"] == 2
    assert summary["by_raw_label"]["OS"] == 2
    assert summary["by_reason"]["invalid os marker"] == 2
    assert summary["by_suggested_target"]["speaker_output"] == 1
    assert summary["examples_by_label"]["voice_feature_or_shifted_value"][0]["value"] == "2.0채널"


def test_build_rule_candidates_ranks_suggested_moves():
    suspicious = [
        SuspiciousValue(
            model_name="A",
            raw_label="유튜브",
            label="youtube_or_shifted_value",
            value="2.0채널",
            reason="shifted",
            suggested_target_label="speaker_config",
        ),
        SuspiciousValue(
            model_name="B",
            raw_label="유튜브",
            label="youtube_or_shifted_value",
            value="2.1채널",
            reason="shifted",
            suggested_target_label="speaker_config",
        ),
        SuspiciousValue(
            model_name="C",
            raw_label="넷플릭스",
            label="netflix_or_shifted_value",
            value="20W",
            reason="shifted",
            suggested_target_label="speaker_output",
        ),
    ]
    candidates = build_rule_candidates(suspicious)
    assert candidates[0]["raw_label"] == "유튜브"
    assert candidates[0]["suggested_target_label"] == "speaker_config"
    assert candidates[0]["count"] == 2
    assert candidates[1]["suggested_target_label"] == "speaker_output"


def test_summarize_reassignments_counts_applied_and_conflicts():
    preview = [
        {
            "approved_reassignments": [
                {
                    "rule_name": "AI음성인식->speaker_config",
                    "target_label": "speaker_config",
                    "applied": True,
                    "decision": "filled_placeholder",
                    "conflict_type": None,
                },
                {
                    "rule_name": "넷플릭스->speaker_output",
                    "target_label": "speaker_output",
                    "applied": False,
                    "decision": "kept_existing_value",
                    "conflict_type": "target_has_different_value",
                },
            ]
        },
        {
            "approved_reassignments": [
                {
                    "rule_name": "AI음성인식->speaker_config",
                    "target_label": "speaker_config",
                    "applied": True,
                    "decision": "matched_existing",
                    "conflict_type": None,
                },
            ]
        },
    ]
    summary = summarize_reassignments(preview, field_name="approved_reassignments")
    assert summary["applied_by_target"]["speaker_config"] == 2
    assert summary["conflicts_by_target"]["speaker_output"] == 1
    assert summary["applied_by_rule"]["AI음성인식->speaker_config"] == 2
    assert summary["conflicts_by_rule"]["넷플릭스->speaker_output"] == 1
    assert summary["decisions"]["filled_placeholder"] == 1
    assert summary["conflicts_by_type"]["target_has_different_value"] == 1


def test_summarize_proposed_reassignments_uses_default_field_name():
    preview = [
        {
            "proposed_reassignments": [
                {
                    "rule_name": "유튜브->speaker_config",
                    "target_label": "speaker_config",
                    "applied": True,
                    "decision": "filled_placeholder",
                    "conflict_type": None,
                }
            ]
        }
    ]
    summary = summarize_proposed_reassignments(preview)
    assert summary["applied_by_rule"]["유튜브->speaker_config"] == 1


def test_build_rule_effectiveness_reports_apply_rate_and_conflict_types():
    preview = [
        {
            "proposed_reassignments": [
                {
                    "rule_name": "유튜브->speaker_config",
                    "target_label": "speaker_config",
                    "value": "2.0채널",
                    "applied": True,
                    "decision": "filled_placeholder",
                    "conflict_type": None,
                },
                {
                    "rule_name": "유튜브->speaker_config",
                    "target_label": "speaker_config",
                    "value": "2.1채널",
                    "applied": False,
                    "decision": "kept_existing_value",
                    "conflict_type": "target_has_different_value",
                },
                {
                    "rule_name": "AI음성인식->speaker_output",
                    "target_label": "speaker_output",
                    "value": "20W",
                    "applied": True,
                    "decision": "matched_existing",
                    "conflict_type": None,
                },
            ]
        }
    ]
    effectiveness = build_rule_effectiveness(preview)
    youtube_rule = next(item for item in effectiveness if item["rule_name"] == "유튜브->speaker_config")
    assert youtube_rule["total_count"] == 2
    assert youtube_rule["applied_count"] == 1
    assert youtube_rule["conflict_count"] == 1
    assert youtube_rule["apply_rate"] == 0.5
    assert youtube_rule["conflict_types"]["target_has_different_value"] == 1


def test_categorize_rule_marks_safe_and_conflict_heavy_cases():
    safe_category, safe_reason = categorize_rule(
        {
            "rule_name": "AI음성인식->speaker_config",
            "target_label": "speaker_config",
            "total_count": 5,
            "applied_count": 5,
            "conflict_count": 0,
            "apply_rate": 1.0,
            "sample_values": ["2.0채널"],
        }
    )
    assert safe_category == "safe_to_promote"
    assert "without conflicts" in safe_reason

    heavy_category, heavy_reason = categorize_rule(
        {
            "rule_name": "AI음성인식->speaker_output",
            "target_label": "speaker_output",
            "total_count": 5,
            "applied_count": 1,
            "conflict_count": 4,
            "apply_rate": 0.2,
            "sample_values": ["20W"],
        }
    )
    assert heavy_category == "conflict_heavy"
    assert "conflicts dominate" in heavy_reason


def test_build_rule_recommendations_groups_effectiveness():
    rule_effectiveness = [
        {
            "rule_name": "AI음성인식->speaker_config",
            "target_label": "speaker_config",
            "total_count": 5,
            "applied_count": 5,
            "conflict_count": 0,
            "apply_rate": 1.0,
            "sample_values": ["2.0채널"],
        },
        {
            "rule_name": "AI음성인식->speaker_output",
            "target_label": "speaker_output",
            "total_count": 5,
            "applied_count": 5,
            "conflict_count": 0,
            "apply_rate": 1.0,
            "sample_values": ["20W"],
        },
    ]
    recommendations = build_rule_recommendations(rule_effectiveness)
    assert recommendations["safe_to_promote"][0]["rule_name"] == "AI음성인식->speaker_config"
    assert recommendations["safe_to_promote"][1]["rule_name"] == "AI음성인식->speaker_output"


def test_build_approved_rule_snapshot_filters_to_approved_rules():
    rule_effectiveness = [
        {
            "rule_name": "AI음성인식->speaker_config",
            "target_label": "speaker_config",
            "total_count": 5,
            "applied_count": 5,
            "conflict_count": 0,
            "apply_rate": 1.0,
            "sample_values": ["2.0채널"],
        },
        {
            "rule_name": "유튜브->speaker_output",
            "target_label": "speaker_output",
            "total_count": 5,
            "applied_count": 5,
            "conflict_count": 0,
            "apply_rate": 1.0,
            "sample_values": ["20W"],
        },
        {
            "rule_name": "OS->speaker_config",
            "target_label": "speaker_config",
            "total_count": 2,
            "applied_count": 2,
            "conflict_count": 0,
            "apply_rate": 1.0,
            "sample_values": ["2.0채널"],
        },
    ]
    snapshot = build_approved_rule_snapshot(rule_effectiveness)
    assert snapshot[0]["rule_name"] == "AI음성인식->speaker_config"
    assert {item["rule_name"] for item in snapshot} == {
        "AI음성인식->speaker_config",
        "유튜브->speaker_output",
        "OS->speaker_config",
    }


def test_build_conflict_rule_analysis_summarizes_existing_and_incoming_values():
    preview = [
        {
            "model_name": "A",
            "proposed_reassignments": [
                {
                    "rule_name": "유튜브->speaker_config",
                    "target_label": "speaker_config",
                    "value": "2.0채널",
                    "existing_value": "4.2채널",
                    "applied": False,
                    "conflict_type": "target_has_different_value",
                },
                {
                    "rule_name": "유튜브->speaker_config",
                    "target_label": "speaker_config",
                    "value": "2.1채널",
                    "existing_value": "4.2채널",
                    "applied": False,
                    "conflict_type": "target_has_different_value",
                },
            ],
        },
        {
            "model_name": "B",
            "proposed_reassignments": [
                {
                    "rule_name": "AI음성인식->speaker_output",
                    "target_label": "speaker_output",
                    "value": "20W",
                    "existing_value": "40W",
                    "applied": False,
                    "conflict_type": "target_has_different_value",
                }
            ],
        },
    ]
    analysis = build_conflict_rule_analysis(preview)
    youtube_rule = next(item for item in analysis if item["rule_name"] == "유튜브->speaker_config")
    assert youtube_rule["conflict_count"] == 2
    assert youtube_rule["top_existing_values"]["4.2채널"] == 2
    assert youtube_rule["likely_duplicate_conflicts"] is True
    assert youtube_rule["suggested_policy"] == "compare_existing_vs_incoming"


def test_summarize_remaining_work_counts_conflict_rules():
    rule_recommendations = {
        "safe_to_promote": [{"rule_name": "AI음성인식->speaker_config"}],
        "conflict_heavy": [],
    }
    conflict_analysis = []
    summary = summarize_remaining_work(rule_recommendations, conflict_analysis)
    assert summary["approved_rule_count"] == 1
    assert summary["remaining_conflict_rule_count"] == 0
    assert summary["conflict_rules_with_comparison_policy_candidates"] == []
    assert summary["conflict_rules_still_manual_review"] == []
