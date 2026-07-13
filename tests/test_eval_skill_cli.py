from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from awaf import evalgrader
from awaf.cli import cli


def _fake_summary(pass_rate: float, det_ok: bool = True) -> evalgrader.GradeSummary:
    return evalgrader.GradeSummary(
        pass_rate=pass_rate,
        deterministic_ok=det_ok,
        total_expectations=10,
        passed_expectations=int(round(pass_rate * 10)),
        cases=[],
    )


def test_eval_skill_passes_gate(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("awaf.cli.get_provider", lambda cfg: _StubProvider())
    monkeypatch.setattr("awaf.evalgrader.grade_all", lambda *a, **k: _fake_summary(0.9))
    out = tmp_path / "metrics.json"
    result = CliRunner().invoke(
        cli, ["eval-skill", "--skill-dir", str(tmp_path), "--output", str(out), "--gate", "0.85"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text())["pass_rate"] == 0.9


def test_eval_skill_fails_below_gate(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("awaf.cli.get_provider", lambda cfg: _StubProvider())
    monkeypatch.setattr("awaf.evalgrader.grade_all", lambda *a, **k: _fake_summary(0.5))
    result = CliRunner().invoke(
        cli, ["eval-skill", "--skill-dir", str(tmp_path), "--output", str(tmp_path / "m.json")]
    )
    assert result.exit_code == 1


def test_eval_skill_fails_on_deterministic_failure(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    # pass_rate is well above the gate, but a deterministic check failed -> must exit 1.
    monkeypatch.setattr("awaf.cli.get_provider", lambda cfg: _StubProvider())
    monkeypatch.setattr(
        "awaf.evalgrader.grade_all", lambda *a, **k: _fake_summary(0.99, det_ok=False)
    )
    result = CliRunner().invoke(
        cli, ["eval-skill", "--skill-dir", str(tmp_path), "--output", str(tmp_path / "m.json")]
    )
    assert result.exit_code == 1


class _StubProvider:
    def validate_config(self) -> None:
        return None
