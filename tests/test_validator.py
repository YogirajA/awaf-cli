from __future__ import annotations

from awaf.pillars.base import PillarResult
from awaf.validator import (
    SUSPECT_SCORES,
    validate_assessment_cluster,
    validate_pillar_result,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pr(
    score: float,
    *,
    name: str = "Pillar",
    confidence: str = "partial",
    findings: list[dict[str, object]] | None = None,
    output_tokens: int = 0,
    skipped: bool = False,
    not_applicable: bool = False,
    suspect: bool = False,
    suspect_reason: str = "",
) -> PillarResult:
    """Construct a real PillarResult with the fields these validators read."""
    return PillarResult(
        name=name,
        score=score,
        confidence=confidence,
        findings=findings if findings is not None else [],
        output_tokens=output_tokens,
        skipped=skipped,
        not_applicable=not_applicable,
        suspect=suspect,
        suspect_reason=suspect_reason,
    )


# ---------------------------------------------------------------------------
# validate_pillar_result - skip / not-applicable short-circuit
# ---------------------------------------------------------------------------


def test_pillar_result_skipped_is_not_checked() -> None:
    # score 42 would normally flag, but skipped results short-circuit entirely.
    r = _pr(42, skipped=True)
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out is r
    assert out.suspect is False
    assert out.suspect_reason == ""


def test_pillar_result_not_applicable_is_not_checked() -> None:
    r = _pr(42, not_applicable=True)
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out.suspect is False
    assert out.suspect_reason == ""


# ---------------------------------------------------------------------------
# validate_pillar_result - Rule 1: truncation (output near token limit)
# ---------------------------------------------------------------------------


def test_pillar_result_truncation_fires_at_threshold() -> None:
    # int(1000 * 0.90) == 900; >= threshold fires.
    r = _pr(75, output_tokens=900)
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out.suspect is True
    assert "truncated" in out.suspect_reason
    assert "output tokens" in out.suspect_reason


def test_pillar_result_truncation_does_not_fire_below_threshold() -> None:
    r = _pr(75, output_tokens=899)
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out.suspect is False
    assert out.suspect_reason == ""


def test_pillar_result_truncation_skipped_when_max_is_zero() -> None:
    # max_output_tokens == 0 disables the truncation check (guarded by `> 0`).
    r = _pr(75, output_tokens=10_000)
    out = validate_pillar_result(r, max_output_tokens=0)
    assert out.suspect is False


def test_pillar_result_truncation_well_above_threshold_fires() -> None:
    r = _pr(75, output_tokens=1000)
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out.suspect is True
    assert "truncated" in out.suspect_reason


# ---------------------------------------------------------------------------
# validate_pillar_result - Rule 2: known pathological score (42)
# ---------------------------------------------------------------------------


def test_pillar_result_pathological_score_42_fires() -> None:
    assert 42 in SUSPECT_SCORES
    r = _pr(42)
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out.suspect is True
    assert "pathology" in out.suspect_reason


def test_pillar_result_non_pathological_score_does_not_fire() -> None:
    r = _pr(50)
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out.suspect is False
    assert out.suspect_reason == ""


def test_pillar_result_pathological_check_rounds_score() -> None:
    # Score rounds to the nearest int: 41.6 -> 42 (flagged), 42.6 -> 43 (clean).
    flagged = validate_pillar_result(_pr(41.6), max_output_tokens=1000)
    assert flagged.suspect is True
    assert "pathology" in flagged.suspect_reason
    clean = validate_pillar_result(_pr(42.6), max_output_tokens=1000)
    assert clean.suspect is False


# ---------------------------------------------------------------------------
# validate_pillar_result - Rule 3: verified + score 0 + no findings
# ---------------------------------------------------------------------------


def test_pillar_result_verified_zero_no_findings_is_contradiction() -> None:
    r = _pr(0, confidence="verified", findings=[])
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out.suspect is True
    assert "contradiction" in out.suspect_reason


def test_pillar_result_verified_zero_with_findings_is_not_flagged() -> None:
    r = _pr(0, confidence="verified", findings=[{"detail": "something"}])
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out.suspect is False
    assert out.suspect_reason == ""


def test_pillar_result_zero_score_non_verified_is_not_flagged() -> None:
    r = _pr(0, confidence="self_reported", findings=[])
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out.suspect is False


# ---------------------------------------------------------------------------
# validate_pillar_result - clean result, accumulation, identity
# ---------------------------------------------------------------------------


def test_pillar_result_clean_stays_unflagged() -> None:
    r = _pr(75, confidence="verified", findings=[{"detail": "x"}], output_tokens=100)
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out.suspect is False
    assert out.suspect_reason == ""


def test_pillar_result_returns_same_object() -> None:
    r = _pr(42)
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out is r


def test_pillar_result_preserves_existing_suspect_reason() -> None:
    # A pre-existing suspect_reason is kept and the new reason is appended after it.
    r = _pr(42, suspect=True, suspect_reason="prior reason")
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out.suspect is True
    assert out.suspect_reason.startswith("prior reason; ")
    assert "pathology" in out.suspect_reason


def test_pillar_result_multiple_rules_combine_with_semicolon() -> None:
    # Truncation (Rule 1) + pathological score (Rule 2) both fire and are joined by "; ".
    r = _pr(42, output_tokens=900)
    out = validate_pillar_result(r, max_output_tokens=1000)
    assert out.suspect is True
    assert "truncated" in out.suspect_reason
    assert "pathology" in out.suspect_reason
    assert "; " in out.suspect_reason


# ---------------------------------------------------------------------------
# validate_assessment_cluster - size gate / trivial inputs
# ---------------------------------------------------------------------------


def test_cluster_empty_list_returns_no_warnings() -> None:
    assert validate_assessment_cluster([]) == []


def test_cluster_single_result_returns_no_warnings() -> None:
    assert validate_assessment_cluster([_pr(50)]) == []


def test_cluster_two_results_below_min_returns_no_warnings() -> None:
    # Fewer than 3 scored pillars => the cluster path is never entered.
    assert validate_assessment_cluster([_pr(50), _pr(50)]) == []


def test_cluster_skipped_and_na_excluded_from_scored_count() -> None:
    # Three identical-score results, but two are skipped/na, so only one is "scored".
    results = [
        _pr(50),
        _pr(50, skipped=True),
        _pr(50, not_applicable=True),
    ]
    assert validate_assessment_cluster(results) == []
    # excluded results are never mutated
    assert results[1].suspect is False
    assert results[2].suspect is False


# ---------------------------------------------------------------------------
# validate_assessment_cluster - shared-score cluster rule (non-100)
# ---------------------------------------------------------------------------


def test_cluster_three_identical_scores_fires() -> None:
    results = [_pr(50), _pr(50), _pr(50)]
    warnings = validate_assessment_cluster(results)
    assert len(warnings) == 1
    assert "3 pillars returned score 50" in warnings[0]
    for r in results:
        assert r.suspect is True
        assert "cluster pattern" in r.suspect_reason


def test_cluster_does_not_fire_when_all_scores_distinct() -> None:
    results = [_pr(10), _pr(20), _pr(30)]
    warnings = validate_assessment_cluster(results)
    assert warnings == []
    assert all(not r.suspect for r in results)


def test_cluster_only_the_shared_score_pillars_are_flagged() -> None:
    # Three pillars share 50; a fourth at 20 must not be flagged.
    shared_a, shared_b, shared_c = _pr(50), _pr(50), _pr(50)
    other = _pr(20)
    warnings = validate_assessment_cluster([shared_a, shared_b, shared_c, other])
    assert len(warnings) == 1
    assert shared_a.suspect and shared_b.suspect and shared_c.suspect
    assert other.suspect is False
    assert other.suspect_reason == ""


def test_cluster_rounds_float_scores() -> None:
    # Scores round to the nearest int before clustering: 49.6, 50.0, 50.4 all -> 50.
    results = [_pr(49.6), _pr(50.0), _pr(50.4)]
    warnings = validate_assessment_cluster(results)
    assert len(warnings) == 1
    assert "score 50" in warnings[0]


def test_cluster_appends_reason_to_already_suspect_result() -> None:
    # A pillar already suspect (e.g. from validate_pillar_result) accumulates the
    # cluster reason rather than overwriting it.
    already = _pr(50, suspect=True, suspect_reason="prior")
    warnings = validate_assessment_cluster([already, _pr(50), _pr(50)])
    assert len(warnings) == 1
    assert already.suspect_reason.startswith("prior; ")
    assert "cluster pattern" in already.suspect_reason


# ---------------------------------------------------------------------------
# validate_assessment_cluster - score == 100 special-cased message
# ---------------------------------------------------------------------------


def test_cluster_score_100_uses_special_message() -> None:
    results = [_pr(100), _pr(100), _pr(100)]
    warnings = validate_assessment_cluster(results)
    assert len(warnings) == 1
    # The 100 branch has distinct wording (not the "anchoring or guessing" text).
    assert "score 100" in warnings[0]
    assert "difficult to achieve" in warnings[0]
    assert "anchoring or guessing" not in warnings[0]
    for r in results:
        assert r.suspect is True
        assert "multi-run average" in r.suspect_reason


# ---------------------------------------------------------------------------
# validate_assessment_cluster - low-variance rule (>= 5 scored pillars)
# ---------------------------------------------------------------------------


def test_cluster_low_variance_fires_without_score_cluster() -> None:
    # Five distinct-but-tight scores: no shared-score cluster, but stdev < 5.
    results = [_pr(70), _pr(71), _pr(72), _pr(73), _pr(74)]
    warnings = validate_assessment_cluster(results)
    assert len(warnings) == 1
    assert "variance" in warnings[0].lower()
    # The low-variance rule does NOT mutate suspect flags.
    assert all(not r.suspect for r in results)


def test_cluster_high_variance_does_not_fire() -> None:
    results = [_pr(10), _pr(30), _pr(50), _pr(70), _pr(90)]
    warnings = validate_assessment_cluster(results)
    assert warnings == []


def test_cluster_low_variance_requires_five_scored_pillars() -> None:
    # Four tight scores: below the >=5 gate, so the variance rule never runs.
    results = [_pr(70), _pr(71), _pr(72), _pr(73)]
    warnings = validate_assessment_cluster(results)
    assert warnings == []


def test_cluster_all_identical_five_fires_both_rules() -> None:
    # Five identical scores trip BOTH the shared-score cluster and the low-variance rule.
    results = [_pr(60), _pr(60), _pr(60), _pr(60), _pr(60)]
    warnings = validate_assessment_cluster(results)
    assert len(warnings) == 2
    assert any("5 pillars returned score 60" in w for w in warnings)
    assert any("variance" in w.lower() for w in warnings)


def test_cluster_all_100_five_fires_cluster_and_variance() -> None:
    results = [_pr(100), _pr(100), _pr(100), _pr(100), _pr(100)]
    warnings = validate_assessment_cluster(results)
    assert len(warnings) == 2
    assert any("difficult to achieve" in w for w in warnings)
    assert any("variance" in w.lower() for w in warnings)
