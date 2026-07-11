from __future__ import annotations

import json
from pathlib import Path

from awaf.findings import classify_findings


def test_lifecycle_summary_and_tags_are_computed() -> None:
    # Unit-level check of the classification the run command will surface.
    prev = [
        {
            "pillar": "Security",
            "title": "missing-auth",
            "fingerprint": __import__("awaf.findings", fromlist=["fingerprint"]).fingerprint(
                "Security", "missing-auth"
            ),
        }
    ]
    curr = [
        {
            "pillar": "Security",
            "title": "missing-auth",
            "fingerprint": __import__("awaf.findings", fromlist=["fingerprint"]).fingerprint(
                "Security", "missing-auth"
            ),
        },
        {
            "pillar": "Reliability",
            "title": "no-retries",
            "fingerprint": __import__("awaf.findings", fromlist=["fingerprint"]).fingerprint(
                "Reliability", "no-retries"
            ),
        },
    ]
    result = classify_findings(curr, prev)
    assert result.counts == (1, 1, 0)


def test_trace_file_written_when_enabled(tmp_path: Path) -> None:
    # Drive the TraceWriter + config path the run command uses, without a full assessment.
    from awaf.config import resolve_telemetry_config
    from awaf.pillars.base import PillarResult
    from awaf.telemetry import TraceWriter, new_run_id

    trace = tmp_path / "t.jsonl"
    cfg = resolve_telemetry_config(cli_trace=str(trace), toml_path=str(tmp_path / "none.toml"))
    assert cfg.enabled
    w = TraceWriter(cfg.trace_path)
    rid = new_run_id()
    w.pillar(rid, PillarResult(name="Security", score=60.0, confidence="partial"))
    w.run(
        rid,
        {
            "project": "demo",
            "overall_score": 60.0,
            "new_findings": 0,
            "recurring_findings": 0,
            "resolved_findings": 0,
        },
    )
    events = [json.loads(x) for x in trace.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert {e["event"] for e in events} == {"pillar", "run"}
