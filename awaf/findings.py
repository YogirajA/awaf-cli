from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "on",
        "in",
        "to",
        "is",
        "are",
        "no",
        "not",
        "for",
        "and",
        "with",
        "without",
    }
)


def normalize_title(text: str) -> str:
    """Lowercase, drop punctuation and stopwords, sort tokens, join with '-'.

    Makes reworded phrasings of the same issue collapse to the same string so
    fingerprints match across runs (e.g. 'missing auth on admin' and
    'admin auth missing' both normalize to 'admin-auth-missing').
    """
    tokens = [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t and t not in _STOPWORDS]
    return "-".join(sorted(tokens))


def fingerprint(pillar: str, title: str, file: str = "") -> str:
    """Stable 12-hex-char identity for a finding: sha1(pillar | normalized title | file)."""
    basis = f"{pillar}|{normalize_title(title)}|{file}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def finding_signature(finding: dict[str, Any]) -> str:
    """Return a finding's fingerprint, computing one if absent (legacy rows)."""
    fp = finding.get("fingerprint")
    if isinstance(fp, str) and fp:
        return fp
    pillar = str(finding.get("pillar", ""))
    file = str(finding.get("file", ""))
    # Legacy findings have no title; fall back to the free-text detail.
    title = str(finding.get("title", "")) or str(finding.get("detail", ""))
    return fingerprint(pillar, title, file)


@dataclass
class LifecycleResult:
    statuses: dict[str, str] = field(default_factory=dict)  # signature -> "new" | "recurring"
    new: list[dict[str, Any]] = field(default_factory=list)
    recurring: list[dict[str, Any]] = field(default_factory=list)
    resolved: list[dict[str, Any]] = field(default_factory=list)

    @property
    def counts(self) -> tuple[int, int, int]:
        return (len(self.new), len(self.recurring), len(self.resolved))


def classify_findings(
    current: list[dict[str, Any]], previous: list[dict[str, Any]]
) -> LifecycleResult:
    """Tag each current finding new/recurring vs *previous*, and list resolved ones."""
    prev_by_sig = {finding_signature(f): f for f in previous}
    result = LifecycleResult()
    seen: set[str] = set()
    for f in current:
        sig = finding_signature(f)
        seen.add(sig)
        if sig in prev_by_sig:
            result.statuses[sig] = "recurring"
            result.recurring.append(f)
        else:
            result.statuses[sig] = "new"
            result.new.append(f)
    for sig, f in prev_by_sig.items():
        if sig not in seen:
            result.resolved.append(f)
    return result
