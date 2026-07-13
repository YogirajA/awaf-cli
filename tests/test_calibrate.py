"""Tests for the calibration harness parsing (scripts/calibrate.py).

The harness parses `awaf run`'s own VARIANCE summary rather than re-implementing
scoring, so the only thing that can silently break is the regex drifting away
from the real output format produced by awaf/cli.py::_print_variance_table.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import calibrate  # noqa: E402

# Mirrors the exact format string in awaf/cli.py::_print_variance_table:
#   f"  {'Overall':<22} {mean:>6.1f}  ±{stdev:>8.1f}"
_REAL_OUTPUT = """
  VARIANCE  (5 runs)
  Pillar                   Mean   ± Std Dev
  ────────────────────────────────────────────
  Foundation               72.0  ±     3.2
  ────────────────────────────────────────────
  Overall                  88.0  ±     2.0
Readiness: Production Ready
  Estimated cost: $0.42
"""


def test_overall_regex_matches_real_variance_line():
    m = calibrate._OVERALL_RE.search(_REAL_OUTPUT)
    assert m is not None
    assert float(m.group(1)) == 88.0
    assert float(m.group(2)) == 2.0


def test_band_and_cost_parse():
    assert calibrate._BAND_RE.search(_REAL_OUTPUT).group(0) == "Production Ready"
    assert calibrate._COST_RE.findall(_REAL_OUTPUT) == ["0.42"]


def test_gate_advice_thresholds():
    assert "absolute threshold OK" in calibrate._gate_advice(5.0)
    assert "band-drop gate only" in calibrate._gate_advice(5.1)
    assert calibrate._gate_advice(None) == "n/a"


def test_to_markdown_renders_ok_and_failed_cells():
    cells = [
        calibrate.Cell(
            "claude-haiku-4-5", "examples/good-agent", 5, 88.0, 2.0, "Production Ready", 0.42, True
        ),
        calibrate.Cell(
            "claude-opus-4-6", "examples/bad-agent", 5, None, None, None, None, False, "boom"
        ),
    ]
    md = calibrate.to_markdown(cells, runs=5)
    assert "| `claude-haiku-4-5` | examples/good-agent | 5 | 88.0 | 2.0 |" in md
    assert "FAILED" in md
    assert "absolute threshold OK" in md
