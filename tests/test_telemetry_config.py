from __future__ import annotations

from awaf.config import resolve_telemetry_config


def test_default_is_disabled(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("AWAF_TELEMETRY_ENABLED", raising=False)
    monkeypatch.delenv("AWAF_TELEMETRY_PATH", raising=False)
    cfg = resolve_telemetry_config(toml_path=str(tmp_path / "none.toml"))
    assert cfg.enabled is False
    assert cfg.trace_path == ""


def test_cli_trace_enables_and_sets_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cfg = resolve_telemetry_config(cli_trace="run.jsonl", toml_path=str(tmp_path / "none.toml"))
    assert cfg.enabled is True
    assert cfg.trace_path == "run.jsonl"


def test_env_enables_with_default_path(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWAF_TELEMETRY_ENABLED", "true")
    monkeypatch.delenv("AWAF_TELEMETRY_PATH", raising=False)
    cfg = resolve_telemetry_config(toml_path=str(tmp_path / "none.toml"))
    assert cfg.enabled is True
    assert cfg.trace_path == "awaf-trace.jsonl"


def test_toml_enables(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("AWAF_TELEMETRY_ENABLED", raising=False)
    monkeypatch.delenv("AWAF_TELEMETRY_PATH", raising=False)
    toml = tmp_path / "awaf.toml"
    toml.write_text('[telemetry]\nenabled = true\npath = "t.jsonl"\n', encoding="utf-8")
    cfg = resolve_telemetry_config(toml_path=str(toml))
    assert cfg.enabled is True
    assert cfg.trace_path == "t.jsonl"


def test_cli_overrides_env_and_toml(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AWAF_TELEMETRY_PATH", "env.jsonl")
    toml = tmp_path / "awaf.toml"
    toml.write_text('[telemetry]\nenabled = true\npath = "toml.jsonl"\n', encoding="utf-8")
    cfg = resolve_telemetry_config(cli_trace="cli.jsonl", toml_path=str(toml))
    assert cfg.trace_path == "cli.jsonl"
