from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from awaf import evalgrader
from awaf.cli import _load_findings_list, cli


def test_load_findings_list_tolerates_bad_shapes() -> None:
    # A legacy/hand-edited findings blob that is valid JSON but not a list of dicts must
    # degrade to [] instead of crashing classify_findings with AttributeError.
    assert _load_findings_list('["missing auth"]') == []  # list of strings
    assert _load_findings_list('{"a": 1}') == []  # bare object
    assert _load_findings_list("not json") == []
    assert _load_findings_list('[{"pillar": "X", "title": "t"}, "junk"]') == [
        {"pillar": "X", "title": "t"}
    ]


class _Stub:
    def validate_config(self) -> None:
        return None


def test_eval_skill_config_error_exits_2(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from awaf.providers.base import ProviderConfigError

    def _raise(cfg):  # type: ignore[no-untyped-def]
        raise ProviderConfigError("requires an API key", "anthropic", "")

    monkeypatch.setattr("awaf.cli.get_provider", _raise)
    r = CliRunner().invoke(
        cli, ["eval-skill", "--skill-dir", str(tmp_path), "--output", str(tmp_path / "m.json")]
    )
    # A config error must be a clean exit 2, NOT exit 1 (which reads as an eval regression).
    assert r.exit_code == 2
    assert "Configuration error" in r.output


def test_eval_skill_zero_expectations_exits_2(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("awaf.cli.get_provider", lambda cfg: _Stub())
    monkeypatch.setattr(
        "awaf.evalgrader.grade_all",
        lambda *a, **k: evalgrader.GradeSummary(
            pass_rate=0.0,
            deterministic_ok=True,
            total_expectations=0,
            passed_expectations=0,
            cases=[],
        ),
    )
    r = CliRunner().invoke(
        cli, ["eval-skill", "--skill-dir", str(tmp_path), "--output", str(tmp_path / "m.json")]
    )
    # Nothing was evaluated: distinct exit 2 with a clear message, not a misleading gate FAIL.
    assert r.exit_code == 2
    assert "no expectations" in r.output.lower()
