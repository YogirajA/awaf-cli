# tests/test_graph_config.py
from __future__ import annotations

from awaf.config import GraphConfig, resolve_graph_config


def test_default_enabled_true(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AWAF_GRAPH", raising=False)
    cfg = resolve_graph_config(toml_path=str(tmp_path / "none.toml"))
    assert isinstance(cfg, GraphConfig)
    assert cfg.enabled is True
    assert cfg.extract_tokens == 150_000
    assert cfg.slice_budget == 12_000


def test_cli_no_graph_wins_over_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AWAF_GRAPH", "1")
    cfg = resolve_graph_config(cli_graph=False, toml_path=str(tmp_path / "none.toml"))
    assert cfg.enabled is False


def test_env_disables_when_no_cli(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AWAF_GRAPH", "0")
    cfg = resolve_graph_config(toml_path=str(tmp_path / "none.toml"))
    assert cfg.enabled is False


def test_toml_used_when_no_cli_or_env(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("AWAF_GRAPH", raising=False)
    p = tmp_path / "awaf.toml"
    p.write_text("[graph]\nenabled = false\nslice_budget = 5000\n", encoding="utf-8")
    cfg = resolve_graph_config(toml_path=str(p))
    assert cfg.enabled is False
    assert cfg.slice_budget == 5000


def test_refresh_flag(tmp_path) -> None:
    cfg = resolve_graph_config(cli_refresh=True, toml_path=str(tmp_path / "none.toml"))
    assert cfg.refresh is True


def test_malformed_env_int_falls_back_instead_of_crashing(monkeypatch, tmp_path) -> None:
    # Graph evidence must degrade gracefully; a set-but-empty or non-numeric env var
    # (e.g. from a CI 'env:' block) must not crash resolution with a ValueError.
    monkeypatch.setenv("AWAF_GRAPH_EXTRACT_TOKENS", "")  # set but empty
    monkeypatch.setenv("AWAF_GRAPH_SLICE_BUDGET", "150k")  # non-numeric
    monkeypatch.setenv("AWAF_GRAPH_CACHE_MAX", "  ")  # whitespace only
    cfg = resolve_graph_config(toml_path=str(tmp_path / "none.toml"))
    assert cfg.extract_tokens == 150_000
    assert cfg.slice_budget == 12_000
    assert cfg.cache_max == 8


def test_valid_env_int_is_used(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AWAF_GRAPH_EXTRACT_TOKENS", "90000")
    cfg = resolve_graph_config(toml_path=str(tmp_path / "none.toml"))
    assert cfg.extract_tokens == 90000
