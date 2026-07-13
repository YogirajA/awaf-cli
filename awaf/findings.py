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
    """Stable 12-hex-char identity for a finding: sha1(pillar | normalized title | file).

    The file component is canonicalized to forward slashes so the same file spelled with
    backslashes (Windows) or forward slashes yields one identity across runs and platforms.
    """
    file_posix = file.replace("\\", "/")
    basis = f"{pillar}|{normalize_title(title)}|{file_posix}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def finding_signature(finding: dict[str, Any]) -> str:
    """Return a finding's fingerprint, computing one if absent (legacy rows)."""
    fp = finding.get("fingerprint")
    if isinstance(fp, str) and fp:
        return fp
    # `or ""` guards against a JSON null value (key present, value None), where
    # str(None) would otherwise yield the literal "None".
    pillar = str(finding.get("pillar") or "")
    file = str(finding.get("file") or "")
    # Legacy findings have no title; fall back to the free-text detail.
    title = str(finding.get("title") or "") or str(finding.get("detail") or "")
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


def filter_by_pillars(findings: list[dict[str, Any]], pillars: set[str]) -> list[dict[str, Any]]:
    """Keep only findings whose pillar is in *pillars*.

    Used to scope a lifecycle diff to the pillars evaluated in BOTH the current and previous
    runs, so a single-pillar (`--pillar`) run is not diffed against a full run (which would
    falsely report every other pillar's findings as resolved)."""
    return [f for f in findings if str(f.get("pillar") or "") in pillars]


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
