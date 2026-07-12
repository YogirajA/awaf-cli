from __future__ import annotations

from awaf import reportcheck as rc

_GOOD = """\
AWAF Assessment: demo
AWAF v1.4 | 2026-07-10 | anthropic / claude-opus-4-5
Overall Score: 78/100 -- Near Ready
Scale: Production Ready 85-100 | Near Ready 70-84 | Needs Work 50-69
| Foundation | 88 | PASS |
| Op. Excellence | 70 |
| Security | 65 |
| Reliability | 60 |
| Performance | 62 |
| Cost Optim. | 55 |
| Sustainability | 58 |
| Reasoning Integ. | 40 |
| Controllability | 72 |
| Context Integrity | 68 |
FINDINGS (ordered by severity)
  [Critical]  Security  no auth
  [High    ]  Cost Optim.  no budget cap
  [Medium  ]  Performance  slow
RECOMMENDATIONS
TO IMPROVE THIS ASSESSMENT
"""


def test_banner_version_ok() -> None:
    assert rc.has_banner_version(_GOOD).ok
    assert not rc.has_banner_version("AWAF v1.0 report").ok


def test_mentions_all_pillars_ok() -> None:
    assert rc.mentions_all_pillars(_GOOD).ok


def test_mentions_all_pillars_accepts_full_names() -> None:
    full = (
        _GOOD.replace("Op. Excellence", "Operational Excellence")
        .replace("Reasoning Integ.", "Reasoning Integrity")
        .replace("Cost Optim.", "Cost Optimization")
    )
    assert rc.mentions_all_pillars(full).ok


def test_mentions_all_pillars_detects_missing() -> None:
    res = rc.mentions_all_pillars(_GOOD.replace("Context Integrity", "Ctx"))
    assert not res.ok
    assert "Context Integrity" in res.detail


def test_label_matches_score_ok() -> None:
    assert rc.label_matches_score(_GOOD).ok


def test_label_matches_score_detects_mismatch() -> None:
    bad = _GOOD.replace(
        "Overall Score: 78/100 -- Near Ready", "Overall Score: 78/100 -- Production Ready"
    )
    assert not rc.label_matches_score(bad).ok


def test_required_sections_ok() -> None:
    assert rc.has_required_sections(_GOOD).ok


def test_required_sections_detects_missing() -> None:
    assert not rc.has_required_sections("AWAF v1.4 no sections here").ok


def test_findings_severity_ordered_ok() -> None:
    assert rc.findings_severity_ordered(_GOOD).ok


def test_findings_severity_out_of_order() -> None:
    bad = "[Medium  ] a\n[Critical] b\n"
    assert not rc.findings_severity_ordered(bad).ok


def test_label_matches_score_prefers_slash_100_form() -> None:
    # A stray leading integer on the overall line must not be misread as the score.
    text = "Overall Score (run 3): 88/100 -- Production Ready"
    assert rc.label_matches_score(text).ok


def test_label_matches_score_ignores_lines_without_slash_100() -> None:
    # No N/100 form on the overall line: a stray number (a version fragment or a finding
    # count) must NOT be misread as the score and fail an otherwise-correct report.
    assert rc.label_matches_score("Overall readiness: Near Ready (AWAF v1.4)").ok
    assert rc.label_matches_score("Overall Readiness: Needs Work (3 High findings)").ok


def test_pillar_aliases_cover_ten_pillars() -> None:
    assert len(rc.PILLAR_ALIASES) == 10
