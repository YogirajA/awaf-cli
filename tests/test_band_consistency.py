from __future__ import annotations

import re
from pathlib import Path

import pytest

from awaf.reportcheck import READINESS_BANDS

_CANONICAL = {label: lower for lower, label in READINESS_BANDS}
_RANGE_RE = re.compile(r"(\d{1,3})\s*(?:to|[–-])\s*(\d{1,3})")

# awaf-cli-local band-table surfaces (relative to repo root = pytest cwd).
_LOCAL = [
    Path("README.md"),
    Path("examples/good-agent/AWAF_SCORE.md"),
    Path("examples/bad-agent/AWAF_SCORE.md"),
]

# Sibling repos when checked out next to awaf-cli; skipped cleanly when absent.
_SIBLING = [
    Path("../awaf/FRAMEWORK.md"),
    Path("../awaf/README.md"),
    Path("../awaf-skill/README.md"),
    Path("../awaf-skill/skills/awaf/SKILL.md"),
    Path("../awaf-skill/skills/awaf/references/output-format.md"),
]


# Bands are contiguous, so pinning every LOWER bound fully determines the partition.
# This helper intentionally checks lower bounds only; an inconsistent upper bound in a
# doc (e.g. "70-89") is cosmetic and is not locked here.
def _bands_from_text(text: str) -> dict[str, int]:
    """Extract {label: lower_bound} from lines that name exactly one band label and a range."""
    out: dict[str, int] = {}
    for line in text.splitlines():
        present = [label for label in _CANONICAL if label in line]
        if len(present) != 1:
            continue
        m = _RANGE_RE.search(line)
        if m:
            out.setdefault(present[0], min(int(m.group(1)), int(m.group(2))))
    return out


@pytest.mark.parametrize("path", _LOCAL, ids=lambda p: str(p))
def test_local_band_tables_canonical(path: Path) -> None:
    bands = _bands_from_text(path.read_text(encoding="utf-8"))
    if not bands:
        pytest.skip(f"no band table found in {path}")
    assert bands == _CANONICAL, f"{path} band table drifted: {bands}"


@pytest.mark.parametrize("path", _SIBLING, ids=lambda p: str(p))
def test_sibling_band_tables_canonical(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"sibling repo not checked out: {path}")
    bands = _bands_from_text(path.read_text(encoding="utf-8"))
    if not bands:
        pytest.skip(f"no band table found in {path}")
    assert bands == _CANONICAL, f"{path} band table drifted: {bands}"
