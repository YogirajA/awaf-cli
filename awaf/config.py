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


# Environment variable names per provider
_API_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "litellm": "",  # varies by backend; user sets their own
}


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
    api_key_env_name: str = toml_provider.get("api_key_env", "") or _API_KEY_ENV.get(
        provider_name, ""
    )
    api_key: str = os.environ.get(api_key_env_name, "") if api_key_env_name else ""

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
