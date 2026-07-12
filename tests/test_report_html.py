from __future__ import annotations

from datetime import datetime
from typing import Any

from awaf import report_html as rh
from awaf.db import AssessmentRecord


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
