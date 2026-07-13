from __future__ import annotations

import re
from dataclasses import dataclass

# The one spec-version banner string. Bump here for a v1.x release; every emitter (run,
# report, artifact, pillar prompts, HTML) and this module's banner check import it.
SPEC_VERSION = "AWAF v1.4"

# Canonical readiness bands (lower_bound, label), highest-first. Single source of truth,
# imported by cli and report_html (dependency-free home so neither creates an import cycle).
READINESS_BANDS: list[tuple[int, str]] = [
    (85, "Production Ready"),
    (70, "Near Ready"),
    (50, "Needs Work"),
    (25, "High Risk"),
    (0, "Not Ready"),
]

# One-line description shown under an overall score, keyed by band label.
READINESS_BLURBS: dict[str, str] = {
    "Production Ready": "Fully ready. Variance within this band is noise.",
    "Near Ready": "Close to production. Address findings before deploying.",
    "Needs Work": "Notable gaps. Resolve High findings before production use.",
    "High Risk": "Significant control failures. Not suitable for production.",
    "Not Ready": "Critical gaps across multiple pillars. Major rework required.",
}


def band_label(score: float) -> str:
    """Readiness band label for a numeric overall score."""
    for lower, label in READINESS_BANDS:
        if score >= lower:
            return label
    return READINESS_BANDS[-1][1]


def band_blurb(label: str) -> str:
    """One-line description for a band label ('' if unknown)."""
    return READINESS_BLURBS.get(label, "")


# Each pillar's accepted surface forms: CLI-abbreviated first, then full spec name.
PILLAR_ALIASES: list[tuple[str, ...]] = [
    ("Foundation",),
    ("Op. Excellence", "Operational Excellence"),
    ("Security",),
    ("Reliability",),
    ("Performance",),
    ("Cost Optim.", "Cost Optimization"),
    ("Sustainability",),
    ("Reasoning Integ.", "Reasoning Integrity"),
    ("Controllability",),
    ("Context Integrity",),
]

_LABELS = tuple(label for _, label in READINESS_BANDS)
_SEV_ORDER = {"critical": 0, "high": 1, "medium": 2}


@dataclass
class CheckResult:
    ok: bool
    detail: str = ""


def has_banner_version(text: str, expected: str = SPEC_VERSION) -> CheckResult:
    ok = expected in text
    return CheckResult(ok, "" if ok else f"missing banner '{expected}'")


def mentions_all_pillars(text: str) -> CheckResult:
    missing = [aliases[0] for aliases in PILLAR_ALIASES if not any(a in text for a in aliases)]
    return CheckResult(not missing, "" if not missing else f"missing pillars: {missing}")


def label_matches_score(text: str) -> CheckResult:
    """On any line binding an overall score to a readiness label, the label must match the band."""
    for line in text.splitlines():
        if "overall" not in line.lower():
            continue
        present = [lab for lab in _LABELS if lab in line]
        # Only the explicit N/100 score form is trusted. A bare number could be a version
        # fragment ('v1.4') or a finding count ('3 High'), which must not be read as the score.
        m = re.search(r"\b(\d{1,3})\s*/\s*100\b", line)
        if len(present) == 1 and m:
            score = int(m.group(1))
            if 0 <= score <= 100:
                expected = band_label(score)
                if present[0] != expected:
                    return CheckResult(
                        False, f"score {score} labelled '{present[0]}', expected '{expected}'"
                    )
    return CheckResult(True)


def has_required_sections(text: str) -> CheckResult:
    low = text.lower()
    missing: list[str] = []
    if "finding" not in low:
        missing.append("findings")
    if "recommendation" not in low:
        missing.append("recommendations")
    if "to improve this assessment" not in low and "evidence gap" not in low:
        missing.append("improve/evidence-gaps")
    return CheckResult(not missing, "" if not missing else f"missing sections: {missing}")


def findings_severity_ordered(text: str) -> CheckResult:
    ranks = [
        _SEV_ORDER[m.group(1).lower()] for m in re.finditer(r"\[\s*(Critical|High|Medium)", text)
    ]
    ok = all(ranks[i] <= ranks[i + 1] for i in range(len(ranks) - 1))
    return CheckResult(ok, "" if ok else f"severities out of order: {ranks}")
