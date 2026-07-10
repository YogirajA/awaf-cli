from __future__ import annotations

import re
from dataclasses import dataclass

# Canonical readiness bands (lower_bound, label), highest-first.
# Single source of truth; cli._READINESS must equal this (locked by test_band_consistency).
READINESS_BANDS: list[tuple[int, str]] = [
    (85, "Production Ready"),
    (70, "Near Ready"),
    (50, "Needs Work"),
    (25, "High Risk"),
    (0, "Not Ready"),
]

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


def _expected_label(score: int) -> str:
    for lower, label in READINESS_BANDS:
        if score >= lower:
            return label
    return "Not Ready"


def has_banner_version(text: str, expected: str = "AWAF v1.4") -> CheckResult:
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
        m = re.search(r"\b(\d{1,3})\s*/\s*100\b", line) or re.search(r"\b(\d{1,3})\b", line)
        if len(present) == 1 and m:
            score = int(m.group(1))
            if 0 <= score <= 100:
                expected = _expected_label(score)
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
