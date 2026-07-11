from __future__ import annotations

import json
from pathlib import Path

from awaf.pillars.base import PillarResult
from awaf.telemetry import TraceWriter, new_run_id


def _read_events(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_new_run_id_is_hex_string() -> None:
    rid = new_run_id()
    assert isinstance(rid, str) and len(rid) >= 16


def test_writes_pillar_and_run_events(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    w = TraceWriter(str(path))
    r = PillarResult(
        name="Security",
        score=65.0,
        confidence="partial",
        findings=[{"severity": "High", "detail": "x"}],
        input_tokens=100,
        output_tokens=50,
        latency_ms=1234,
    )
    w.pillar("rid1", r)
    w.run("rid1", {"project": "demo", "overall_score": 70.0, "new_findings": 1})
    events = _read_events(path)
    assert events[0]["event"] == "pillar"
    assert events[0]["pillar"] == "Security"
    assert events[0]["latency_ms"] == 1234
    assert events[0]["finding_count"] == 1
    assert events[0]["status"] == "ok"
    assert events[1]["event"] == "run"
    assert events[1]["project"] == "demo"
    assert events[1]["new_findings"] == 1


def test_pillar_status_reflects_flags(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    w = TraceWriter(str(path))
    w.pillar("r", PillarResult(name="A", score=0.0, confidence="self_reported", skipped=True))
    w.pillar("r", PillarResult(name="B", score=0.0, confidence="partial", not_applicable=True))
    events = _read_events(path)
    assert events[0]["status"] == "skipped"
    assert events[1]["status"] == "not_applicable"


def test_write_failure_is_swallowed(tmp_path: Path) -> None:
    # An unwritable path (a directory) must not raise into the caller.
    w = TraceWriter(str(tmp_path))  # tmp_path is a directory, not a file
    w.pillar("r", PillarResult(name="A", score=0.0, confidence="partial"))  # no exception
