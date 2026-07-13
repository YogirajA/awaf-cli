from __future__ import annotations

from unittest.mock import MagicMock

from click.testing import CliRunner

from awaf.cli import cli
from awaf.graph import ArchitectureGraph, FileEntry, GraphNode
from awaf.ingestor import IngestorResult
from awaf.pillars import ALL_AGENTS, AssessmentResult
from awaf.pillars.base import PillarResult


def _truncated_ingest(**_kw: object) -> IngestorResult:
    # Simulates a repo whose raw dump overflowed the token budget.
    return IngestorResult(
        content="RAW DUMP",
        files_scanned=["a.py"],
        files_skipped=["big.py  (token limit reached)"],
        total_tokens=999_999,
        truncated=True,
    )


def _graph() -> ArchitectureGraph:
    g = ArchitectureGraph(
        nodes=[GraphNode(id="a:p", type="agent", name="P", file="a.py", line=1)],
        files=[FileEntry(path="a.py", role="agent", summary="p")],
        content_hash="h",
    )
    g.extract_input_tokens = 1000
    g.extract_output_tokens = 200
    return g


def _fake_assessment() -> AssessmentResult:
    return AssessmentResult(
        pillar_results=[
            PillarResult(name=a.name, score=70.0, confidence="verified") for a in ALL_AGENTS
        ],
        overall_score=70.0,
        foundation_passed=True,
        total_input_tokens=100,
        total_output_tokens=50,
        estimated_cost_usd=0.01,
    )


def _wire(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    prov = MagicMock()
    prov.count_tokens.side_effect = lambda s: len(s.split())
    prov.default_model = "claude-opus-4-5"
    monkeypatch.setenv("AWAF_MODEL", "claude-opus-4-5")
    monkeypatch.setattr("awaf.cli.get_provider", lambda cfg: prov)
    monkeypatch.setattr("awaf.ingestor.ingest", _truncated_ingest)
    monkeypatch.setattr("awaf.ingestor.ingest_files", lambda **k: [("a.py", "x = 1\ny = 2\n")])
    monkeypatch.setattr("awaf.pillars.run_assessment", lambda **k: _fake_assessment())
    monkeypatch.setattr("awaf.db.save_assessment", lambda **k: 1)
    monkeypatch.setattr("awaf.db.get_recent_assessments", lambda *a, **k: [])


def test_graph_mode_survives_raw_dump_truncation(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # The raw dump truncated, but a usable graph is available: the run must NOT abort, and
    # coverage/cost must reflect the graph evidence, not the truncated raw dump.
    _wire(monkeypatch)
    monkeypatch.setattr("awaf.cli.get_graph", lambda *a, **k: _graph())
    r = CliRunner().invoke(cli, ["run", "--paths", str(tmp_path), "--no-artifact"])
    assert r.exit_code == 0, r.output
    assert "code-graph evidence" in r.output  # coverage aligned to graph
    assert "Graph extract" in r.output  # extraction cost surfaced in preflight


def test_no_graph_still_aborts_on_raw_dump_truncation(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # With graph mode off, a truncated raw dump is still fatal (unchanged safety behavior).
    _wire(monkeypatch)
    r = CliRunner().invoke(cli, ["run", "--paths", str(tmp_path), "--no-graph", "--no-artifact"])
    assert r.exit_code == 2
    assert "Token budget exhausted" in r.output
