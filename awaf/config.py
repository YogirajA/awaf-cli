from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field

from awaf.providers.base import ProviderConfig


@dataclass
class CiConfig:
    """Configuration for CI-mode scheduling and change detection (awaf.toml [ci] section)."""

    enabled: bool = True
    schedule: str | None = None  # cron expression; None means always run
    change_detection: bool = False
    watch_paths: list[str] = field(default_factory=list)


@dataclass
class TelemetryConfig:
    """Opt-in run telemetry (awaf.toml [telemetry] section). Disabled by default."""

    enabled: bool = False
    trace_path: str = ""


@dataclass
class GraphConfig:
    """Code-graph evidence settings (awaf.toml [graph] section). Enabled by default."""

    enabled: bool = True
    refresh: bool = False
    extract_tokens: int = 150_000
    slice_budget: int = 12_000
    context_lines: int = 20
    cache_max: int = 8
    starvation_retry: bool = True


# Environment variable names per provider
_API_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "litellm": "",  # varies by backend; user sets their own
}


def _resolve_int(env_name: str, fallback: object) -> int:
    """Return int(env value) when the env var is set to a parseable number, else int(fallback).

    Tolerates a set-but-empty or non-numeric env var (e.g. a CI 'env:' block with an unset
    secret) so graph config resolution degrades gracefully instead of raising ValueError.
    """
    raw = os.environ.get(env_name)
    if raw is not None and raw.strip():
        try:
            return int(raw.strip())
        except ValueError:
            pass
    if isinstance(fallback, int):
        return fallback
    try:
        return int(str(fallback))
    except (ValueError, TypeError):
        return 0


def _read_toml(path: str) -> dict:  # type: ignore[type-arg]
    """Read awaf.toml from *path*. Returns empty dict if the file doesn't exist."""
    if not os.path.exists(path):
        return {}

    with open(path, "rb") as fh:
        return tomllib.load(fh)


def resolve_provider_config(
    cli_provider: str | None = None,
    cli_model: str | None = None,
    toml_path: str = "awaf.toml",
) -> ProviderConfig:
    """
    Build a ProviderConfig from all config sources in priority order:

    1. CLI flags  (cli_provider, cli_model)
    2. Environment variables (AWAF_PROVIDER, AWAF_MODEL, provider key vars)
    3. awaf.toml [provider] section
    4. Provider defaults

    Never raises; returns a config object. validate_config() on the adapter raises.
    """
    toml_data = _read_toml(toml_path)
    toml_provider: dict = toml_data.get("provider", {})  # type: ignore[type-arg]

    # --- provider name ---
    provider_name: str = (
        cli_provider
        or os.environ.get("AWAF_PROVIDER", "")
        or toml_provider.get("name", "")
        or "anthropic"
    )

    # --- model ---
    model: str = (
        cli_model or os.environ.get("AWAF_MODEL", "") or toml_provider.get("model", "") or ""
    )

    # --- api key ---
    # awaf.toml can specify a custom env var name via api_key_env
    # Priority: env var (via api_key_env or the provider default) > literal api_key in toml.
    api_key_env_name: str = toml_provider.get("api_key_env", "") or _API_KEY_ENV.get(
        provider_name, ""
    )
    api_key: str = (
        os.environ.get(api_key_env_name, "") if api_key_env_name else ""
    ) or toml_provider.get("api_key", "")

    # --- optional params ---
    max_tokens: int = int(toml_provider.get("max_tokens", 4096))
    temperature: float = float(toml_provider.get("temperature", 0.0))
    timeout_seconds: int = int(toml_provider.get("timeout", 120))

    # --- Azure-specific ---
    azure_endpoint: str | None = (
        os.environ.get("AZURE_OPENAI_ENDPOINT") or toml_provider.get("azure_endpoint") or None
    )
    azure_deployment: str | None = (
        os.environ.get("AZURE_OPENAI_DEPLOYMENT") or toml_provider.get("azure_deployment") or None
    )
    azure_api_version: str = (
        os.environ.get("AZURE_OPENAI_API_VERSION")
        or toml_provider.get("azure_api_version")
        or "2025-01-01-preview"
    )

    return ProviderConfig(
        provider_name=provider_name,
        model=model,
        api_key=api_key,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
        azure_endpoint=azure_endpoint,
        azure_deployment=azure_deployment,
        azure_api_version=azure_api_version,
    )


def resolve_ci_config(toml_path: str = "awaf.toml") -> CiConfig:
    """
    Read the [ci] section from awaf.toml and return a CiConfig.

    Fields:
      enabled         — set to false to disable CI-mode checks entirely (default: true)
      schedule        — cron expression; if set, awaf skips unless current time matches
      change_detection — whether to check git diff before running (default: false)
      watch_paths     — directories to watch; any changed file under them triggers a run
    """
    toml_data = _read_toml(toml_path)
    ci = toml_data.get("ci", {})
    return CiConfig(
        enabled=bool(ci.get("enabled", True)),
        schedule=ci.get("schedule") or None,
        change_detection=bool(ci.get("change_detection", False)),
        watch_paths=list(ci.get("watch_paths", [])),
    )


def resolve_telemetry_config(
    cli_trace: str | None = None, toml_path: str = "awaf.toml"
) -> TelemetryConfig:
    """Resolve telemetry settings. Precedence: CLI flag > env > awaf.toml > default (off).

    A bare enable with no path falls back to 'awaf-trace.jsonl'.
    """
    toml_data = _read_toml(toml_path)
    tel = toml_data.get("telemetry", {})

    env_enabled = os.environ.get("AWAF_TELEMETRY_ENABLED", "")
    env_path = os.environ.get("AWAF_TELEMETRY_PATH", "")

    path = cli_trace or env_path or str(tel.get("path", "")) or ""
    if cli_trace:
        enabled = True
    elif env_enabled:  # env explicitly set: it wins over toml, on or off
        enabled = env_enabled.lower() in {"1", "true", "yes"}
    else:
        enabled = bool(tel.get("enabled", False))
    if enabled and not path:
        path = "awaf-trace.jsonl"
    return TelemetryConfig(enabled=enabled, trace_path=path)


def resolve_graph_config(
    cli_graph: bool | None = None,
    cli_refresh: bool = False,
    toml_path: str = "awaf.toml",
) -> GraphConfig:
    """Resolve graph settings. Precedence for `enabled`: CLI > env > awaf.toml > default (True)."""
    toml_data = _read_toml(toml_path)
    table = toml_data.get("graph", {})
    cfg = GraphConfig()

    env_enabled = os.environ.get("AWAF_GRAPH")
    if cli_graph is not None:
        cfg.enabled = cli_graph
    elif env_enabled is not None:
        cfg.enabled = env_enabled.strip().lower() in {"1", "true", "yes"}
    else:
        cfg.enabled = bool(table.get("enabled", True))

    cfg.refresh = bool(cli_refresh)
    cfg.extract_tokens = _resolve_int(
        "AWAF_GRAPH_EXTRACT_TOKENS", table.get("extract_tokens", 150_000)
    )
    cfg.slice_budget = _resolve_int("AWAF_GRAPH_SLICE_BUDGET", table.get("slice_budget", 12_000))
    cfg.cache_max = _resolve_int("AWAF_GRAPH_CACHE_MAX", table.get("cache_max", 8))
    cfg.context_lines = _resolve_int("AWAF_GRAPH_CONTEXT_LINES", table.get("context_lines", 20))
    cfg.starvation_retry = bool(table.get("starvation_retry", True))
    return cfg
