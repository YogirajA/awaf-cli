"""
Post-call integrity checks for pillar results (dead letter pattern).

Rules applied per-pillar:
  - Output near token limit → response may be truncated
  - Score matches known pathological values (e.g., 42 for Haiku)
  - verified confidence + score 0 + no findings → contradiction

Cross-pillar cluster detection (run after all pillars complete):
  - ≥3 pillars share the same integer score → anchoring / guessing
  - Score std-dev < 5 across ≥5 scored pillars → suspiciously uniform
"""

from __future__ import annotations

import statistics
from collections import Counter

from awaf.pillars.base import PillarResult

# Known model pathology scores — add more as discovered in the wild
SUSPECT_SCORES: set[int] = {42}

_TRUNCATION_THRESHOLD = 0.90  # flag if output_tokens >= 90% of max_output_tokens
_CLUSTER_MIN_COUNT = 3  # ≥N pillars with same integer score = suspect
_LOW_VARIANCE_STD = 5.0  # std dev below this = suspect (requires ≥5 pillars)


def validate_pillar_result(result: PillarResult, max_output_tokens: int) -> PillarResult:
    """
    Apply dead-letter checks to a single pillar result.

    Mutates and returns the result for chaining convenience.
    Skipped and not-applicable results are not checked — no meaningful score to validate.
    Already-suspect results accumulate additional reasons rather than being overwritten.
    """
    if result.skipped or result.not_applicable:
        return result

    reasons: list[str] = []

    # Rule 1: output near token limit → possible mid-stream truncation
    if max_output_tokens > 0 and result.output_tokens >= int(
        max_output_tokens * _TRUNCATION_THRESHOLD
    ):
        reasons.append(
            f"output tokens {result.output_tokens} ≥ {_TRUNCATION_THRESHOLD:.0%}"
            f" of max ({max_output_tokens}) — response may be truncated"
        )

    # Rule 2: known pathological scores
    if int(result.score) in SUSPECT_SCORES:
        reasons.append(f"score {int(result.score)} matches known model pathology pattern")

    # Rule 3: verified confidence + score 0 + empty findings (contradiction)
    if result.confidence == "verified" and result.score == 0 and not result.findings:
        reasons.append("verified confidence with score 0 and no findings — contradiction")

    if reasons:
        result.suspect = True
        combined = "; ".join(reasons)
        result.suspect_reason = (
            f"{result.suspect_reason}; {combined}" if result.suspect_reason else combined
        )

    return result


def validate_assessment_cluster(results: list[PillarResult]) -> list[str]:
    """
    Cross-pillar cluster detection. Mutates suspect flags on results in-place.
    Returns a list of human-readable warning strings for log/display output.
    """
    warnings: list[str] = []
    scored = [r for r in results if not r.skipped and not r.not_applicable]
    if len(scored) < 3:
        return warnings

    # Rule: ≥N pillars share the same integer score
    score_counts: Counter[int] = Counter(int(r.score) for r in scored)
    for score_val, count in score_counts.items():
        if count >= _CLUSTER_MIN_COUNT:
            msg = (
                f"{count} pillars returned score {score_val} — possible model anchoring or guessing"
            )
            warnings.append(msg)
            for r in scored:
                if int(r.score) == score_val:
                    cluster_reason = (
                        f"score {score_val} shared by {count} pillars (cluster pattern)"
                    )
                    if not r.suspect:
                        r.suspect = True
                        r.suspect_reason = cluster_reason
                    elif cluster_reason not in r.suspect_reason:
                        r.suspect_reason = f"{r.suspect_reason}; {cluster_reason}"

    # Rule: low score variance across ≥5 scored pillars
    if len(scored) >= 5:
        std = statistics.stdev(r.score for r in scored)
        if std < _LOW_VARIANCE_STD:
            warnings.append(
                f"Score variance unusually low (σ={std:.1f}) — "
                "assessment may not reflect actual codebase variation"
            )

    return warnings


__all__ = [
    "SUSPECT_SCORES",
    "validate_assessment_cluster",
    "validate_pillar_result",
]
