from __future__ import annotations

from datetime import datetime
from typing import Any

from click.testing import CliRunner

from awaf import db
from awaf.cli import cli
from awaf.db import AssessmentRecord


def _rec(**kw: Any) -> AssessmentRecord:
    base: dict[str, Any] = dict(
        id=1,
        project_name="demo",
        created_at=datetime(2026, 7, 11),
        commit_hash="abc1234",
        branch="main",
        pr_number="",
        overall_score=66.0,
        provider="anthropic",
        model="claude-opus-4-5",
        note="",
        foundation_score=88.0,
        findings='[{"severity": "High", "pillar": "Security", "detail": "no auth"}]',
    )
    base.update(kw)
    return AssessmentRecord(**base)


def test_report_format_html_emits_document(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(db, "get_recent_assessments", lambda *a, **k: [_rec()])
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["report", "--format", "html"])
    assert result.exit_code == 0, result.output
    assert result.output.lstrip().lower().startswith("<!doctype html")
    assert "no auth" in result.output
    assert "</html>" in result.output
