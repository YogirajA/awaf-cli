from __future__ import annotations

import pytest

from awaf import reportcheck as rc
from awaf.cli import _pillar_table_lines, _readiness_label, _write_artifact
from awaf.pillars import AssessmentResult
from awaf.pillars.base import PillarResult

# (display_name, score) using the abbreviated CLI names the renderers emit.
_PILLARS = [
    ("Foundation", 88.0),
    ("Op. Excellence", 70.0),
    ("Security", 66.0),
    ("Reliability", 61.0),
    ("Performance", 63.0),
    ("Cost Optim.", 55.0),
    ("Sustainability", 58.0),
    ("Reasoning Integ.", 52.0),
    ("Controllability", 72.0),
    ("Context Integrity", 68.0),
]


def _make_assessment(foundation_score: float = 88.0) -> AssessmentResult:
    results = []
    for name, score in _PILLARS:
        s = foundation_score if name == "Foundation" else score
        results.append(PillarResult(name=name, score=s, confidence="partial"))
    overall = 66.0
    return AssessmentResult(
        pillar_results=results,
        overall_score=overall,
        foundation_passed=foundation_score >= 40,
        total_input_tokens=1000,
        total_output_tokens=500,
        estimated_cost_usd=0.01,
    )


def test_pillar_table_mentions_all_pillars() -> None:
    text = "\n".join(_pillar_table_lines(_make_assessment()))
    assert rc.mentions_all_pillars(text).ok


def test_pillar_table_foundation_pass_and_fail() -> None:
    passing = "\n".join(_pillar_table_lines(_make_assessment(88.0)))
    assert "PASS" in passing
    failing = "\n".join(_pillar_table_lines(_make_assessment(20.0)))
    assert "FAIL" in failing


def test_write_artifact_passes_all_shape_checks(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = str(tmp_path / "report.txt")
    findings = [
        {"severity": "Critical", "pillar": "Security", "detail": "no auth"},
        {"severity": "High", "pillar": "Cost Optim.", "detail": "no budget cap"},
        {"severity": "Medium", "pillar": "Performance", "detail": "slow"},
    ]
    recs = [{"pillar": "Security", "detail": "add auth"}]
    gaps = ["no eval report"]
    improvements = ["provide eval reports"]
    _write_artifact(
        path,
        "demo",
        "2026-07-10",
        _make_assessment(),
        ["a.py"],
        [],
        findings,
        recs,
        gaps,
        improvements,
        "anthropic",
        "claude-opus-4-5",
    )
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert rc.has_banner_version(text).ok
    assert rc.mentions_all_pillars(text).ok
    assert rc.label_matches_score(text).ok
    assert rc.has_required_sections(text).ok
    assert rc.findings_severity_ordered(text).ok


@pytest.mark.parametrize(
    "score,label",
    [
        (24, "Not Ready"),
        (25, "High Risk"),
        (49, "High Risk"),
        (50, "Needs Work"),
        (69, "Needs Work"),
        (70, "Near Ready"),
        (84, "Near Ready"),
        (85, "Production Ready"),
    ],
)
def test_readiness_label_band_edges(score: int, label: str) -> None:
    assert _readiness_label(score) == label
