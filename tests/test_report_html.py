from __future__ import annotations

import json as _json
from datetime import datetime
from typing import Any

from awaf import report_html as rh
from awaf.db import AssessmentRecord
from awaf.findings import LifecycleResult, finding_signature


def test_esc_escapes_markup_and_quotes() -> None:
    out = rh._esc('<b> & "x"')
    assert "<b>" not in out
    assert "&lt;b&gt;" in out
    assert "&amp;" in out
    assert "&quot;" in out


def test_load_list_parses_and_degrades() -> None:
    assert rh._load_list("[1, 2, 3]") == [1, 2, 3]
    assert rh._load_list("not json") == []
    assert rh._load_list('{"a": 1}') == []  # non-list JSON degrades to []
    assert rh._load_list("") == []


def test_band_for_maps_score_to_label_and_blurb() -> None:
    label, blurb = rh._band_for(90)
    assert label == "Production Ready"
    assert blurb
    assert rh._band_for(72)[0] == "Near Ready"
    assert rh._band_for(0)[0] == "Not Ready"


def test_severity_bucket_classifies() -> None:
    assert rh._severity_bucket("Critical") == "high"
    assert rh._severity_bucket("HIGH") == "high"
    assert rh._severity_bucket("Medium") == "medium"
    assert rh._severity_bucket("low") == "low"
    assert rh._severity_bucket("informational") == "other"


def test_text_of_handles_str_and_dict() -> None:
    assert rh._text_of("hello") == "hello"
    assert rh._text_of({"detail": "a gap"}) == "a gap"
    assert rh._text_of({"other": "x"})  # falls back to a non-empty string


def test_pillars_in_sync_with_cli() -> None:
    from awaf.cli import _PILLAR_ROWS

    assert len(rh._PILLARS) == len(_PILLAR_ROWS)
    for (name, s_attr, c_attr, tier, _accent), (rname, rs, rc, is_t2) in zip(
        rh._PILLARS, _PILLAR_ROWS, strict=True
    ):
        assert (name, s_attr, c_attr) == (rname, rs, rc)
        assert (tier == 2) == is_t2


def _rec(**kw: Any) -> AssessmentRecord:
    base: dict[str, Any] = dict(
        id=1,
        project_name="demo",
        created_at=datetime(2026, 7, 11),
        commit_hash="abc1234",
        branch="main",
        pr_number="",
        overall_score=66.0,
        provider="anthropic",
        model="claude-opus-4-5",
        note="",
        foundation_score=88.0,
        op_excellence_score=70.0,
        security_score=66.0,
        reliability_score=61.0,
        performance_score=63.0,
        cost_score=55.0,
        sustainability_score=58.0,
        reasoning_score=52.0,
        controllability_score=72.0,
        context_integrity_score=68.0,
        foundation_confidence="partial",
    )
    base.update(kw)
    return AssessmentRecord(**base)


def test_masthead_shows_score_band_and_identity() -> None:
    out = rh._render_masthead(_rec(overall_score=72.0), "demo")
    assert "72" in out
    assert "Near Ready" in out
    assert "demo" in out
    assert "anthropic / claude-opus-4-5" in out


def test_bands_marks_current_band() -> None:
    out = rh._render_bands(72.0)
    assert out.count("bandcell") == 5  # one cell per readiness band
    assert "bandcell here" in out  # the current band is marked
    assert "Near Ready" in out


def test_scorecard_lists_all_pillars_with_tiers() -> None:
    out = rh._render_scorecard(_rec())
    for name, *_ in rh._PILLARS:
        assert name in out
    assert "Tier 0" in out and "Tier 1" in out and "Tier 2" in out


def test_scorecard_foundation_fail_callout() -> None:
    ok = rh._render_scorecard(_rec(foundation_score=88.0))
    assert "foundfail" not in ok
    bad = rh._render_scorecard(_rec(foundation_score=20.0))
    assert "foundfail" in bad
    assert "Foundation" in bad


def test_scorecard_none_score_renders_not_scored() -> None:
    out = rh._render_scorecard(_rec(security_score=None))
    assert "not scored" in out


def test_footer_shows_tokens_and_cost() -> None:
    out = rh._render_footer(
        _rec(total_input_tokens=1234, total_output_tokens=567, estimated_cost_usd=0.0189)
    )
    assert "1,234" in out
    assert "567" in out
    assert "$0.0189" in out


def test_render_html_is_a_valid_document() -> None:
    out = rh.render_html(_rec(overall_score=72.0), None, project_name="demo")
    assert out.lstrip().lower().startswith("<!doctype html")
    assert "</html>" in out
    assert "72" in out
    assert "Near Ready" in out
    assert "demo" in out


def test_action_items_render_detail_location_and_high_highlight() -> None:
    findings = [
        {
            "severity": "High",
            "pillar": "Security",
            "detail": "no rate limit",
            "file": "auth.py",
            "line": 52,
        },
        {"severity": "Low", "pillar": "Performance", "detail": "slow path"},
    ]
    out = rh._render_action_items(findings, None)
    assert "no rate limit" in out
    assert "auth.py:52" in out
    assert "border-left-color:#c4407e" in out  # High highlight border


def test_action_items_escape_model_text() -> None:
    findings = [{"severity": "High", "pillar": "X", "detail": "<script>alert(1)</script> & <b>"}]
    out = rh._render_action_items(findings, None)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "&amp;" in out


def test_action_items_lifecycle_tags() -> None:
    finding = {"severity": "High", "pillar": "X", "detail": "d", "fingerprint": "fp1"}
    life = LifecycleResult(statuses={finding_signature(finding): "new"})
    with_life = rh._render_action_items([finding], life)
    assert "new" in with_life.lower()
    without = rh._render_action_items([finding], None)
    assert 'class="tag"' not in without


def test_empty_sections_render_placeholders_without_crashing() -> None:
    out = rh.render_html(_rec(), None, project_name="demo")
    # findings/recs/evidence/improvements default to "[]"
    assert "No action items recorded." in out
    assert "No recommendations recorded." in out
    assert "None recorded." in out


def test_render_html_handles_populated_blobs() -> None:
    rec = _rec(
        findings=_json.dumps([{"severity": "Medium", "pillar": "Cost Optim.", "detail": "no cap"}]),
        recommendations=_json.dumps([{"pillar": "Security", "detail": "add auth"}]),
        evidence_reviewed=_json.dumps(["README.md", "agent.py"]),
        evidence_gaps=_json.dumps(["no eval report"]),
        improve_suggestions=_json.dumps(["provide eval reports"]),
    )
    out = rh.render_html(rec, None, project_name="demo")
    assert "no cap" in out
    assert "add auth" in out
    assert "README.md" in out
    assert "no eval report" in out
    assert "provide eval reports" in out
