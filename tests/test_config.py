from __future__ import annotations

import pytest

from awaf.config import (
    CiConfig,
    GraphConfig,
    _read_toml,
    resolve_ci_config,
    resolve_graph_config,
    resolve_provider_config,
)
from awaf.providers.azure import AzureOpenAIProvider
from awaf.providers.base import ProviderConfig, ProviderConfigError

# Every env var that can influence config resolution. Cleared before each test so
# resolution is hermetic regardless of the developer's / CI runner's real environment.
_ENV_VARS = (
    "AWAF_PROVIDER",
    "AWAF_MODEL",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_VERSION",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Delete all AWAF/provider env vars so each test starts from a known-empty base."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _write_toml(tmp_path, body: str) -> str:  # type: ignore[no-untyped-def]
    """Write *body* to an awaf.toml under tmp_path and return its path."""
    path = tmp_path / "awaf.toml"
    path.write_text(body, encoding="utf-8")
    return str(path)


def _missing_toml(tmp_path) -> str:  # type: ignore[no-untyped-def]
    """Path to a toml file that does not exist (forces the defaults branch)."""
    return str(tmp_path / "does-not-exist.toml")


# A toml that sets every precedence-relevant field to a distinctive value.
_FULL_PROVIDER_TOML = (
    "[provider]\n"
    'name = "openai"\n'
    'model = "gpt-4o-toml"\n'
    "max_tokens = 8000\n"
    "temperature = 0.7\n"
    "timeout = 45\n"
)


# ---------------------------------------------------------------------------
# Precedence: CLI > env > toml > default
# ---------------------------------------------------------------------------


def test_cli_wins_over_env_and_toml(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    toml_path = _write_toml(tmp_path, _FULL_PROVIDER_TOML)
    monkeypatch.setenv("AWAF_PROVIDER", "azure")
    monkeypatch.setenv("AWAF_MODEL", "gpt-4o-env")

    cfg = resolve_provider_config(
        cli_provider="google",
        cli_model="gemini-cli",
        toml_path=toml_path,
    )

    assert cfg.provider_name == "google"
    assert cfg.model == "gemini-cli"


def test_env_wins_over_toml_when_no_cli(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    toml_path = _write_toml(tmp_path, _FULL_PROVIDER_TOML)
    monkeypatch.setenv("AWAF_PROVIDER", "azure")
    monkeypatch.setenv("AWAF_MODEL", "gpt-4o-env")

    cfg = resolve_provider_config(toml_path=toml_path)

    assert cfg.provider_name == "azure"
    assert cfg.model == "gpt-4o-env"


def test_toml_wins_when_no_cli_or_env(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # env is cleared by the autouse fixture; no CLI args passed.
    toml_path = _write_toml(tmp_path, _FULL_PROVIDER_TOML)

    cfg = resolve_provider_config(toml_path=toml_path)

    assert cfg.provider_name == "openai"
    assert cfg.model == "gpt-4o-toml"


def test_defaults_when_nothing_set(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cfg = resolve_provider_config(toml_path=_missing_toml(tmp_path))

    # Documented defaults when no CLI arg, env var, or toml is present.
    assert cfg.provider_name == "anthropic"
    assert cfg.model == ""
    assert cfg.temperature == 0.0
    assert cfg.max_tokens == 4096
    assert cfg.timeout_seconds == 120
    assert cfg.api_key == ""  # ANTHROPIC_API_KEY cleared by fixture


# ---------------------------------------------------------------------------
# Provider / model / api-key resolution per provider
# ---------------------------------------------------------------------------


def test_anthropic_api_key_from_env(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xyz")

    cfg = resolve_provider_config(toml_path=_missing_toml(tmp_path))

    assert cfg.provider_name == "anthropic"  # default provider
    assert cfg.api_key == "sk-ant-xyz"


def test_openai_provider_reads_openai_key(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A stray Anthropic key must not leak into the OpenAI config.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-be-ignored")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai-123")

    cfg = resolve_provider_config(cli_provider="openai", toml_path=_missing_toml(tmp_path))

    assert cfg.provider_name == "openai"
    assert cfg.api_key == "sk-oai-123"


def test_google_provider_reads_google_key(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-key")

    cfg = resolve_provider_config(cli_provider="google", toml_path=_missing_toml(tmp_path))

    assert cfg.provider_name == "google"
    assert cfg.api_key == "goog-key"


def test_custom_api_key_env_name_from_toml(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # awaf.toml can redirect the api_key lookup to a custom env var name.
    toml_path = _write_toml(
        tmp_path,
        '[provider]\nname = "openai"\napi_key_env = "MY_CUSTOM_KEY"\n',
    )
    monkeypatch.setenv("MY_CUSTOM_KEY", "custom-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "default-should-be-ignored")

    cfg = resolve_provider_config(toml_path=toml_path)

    assert cfg.api_key == "custom-secret"


def test_toml_optional_params_applied(tmp_path) -> None:  # type: ignore[no-untyped-def]
    toml_path = _write_toml(tmp_path, _FULL_PROVIDER_TOML)

    cfg = resolve_provider_config(toml_path=toml_path)

    assert cfg.max_tokens == 8000
    assert cfg.temperature == 0.7
    assert cfg.timeout_seconds == 45


# ---------------------------------------------------------------------------
# Azure-specific field resolution (endpoint / deployment / api_version)
# ---------------------------------------------------------------------------


def test_azure_fields_from_env(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://env.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "env-deploy")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-envver")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-secret")

    cfg = resolve_provider_config(cli_provider="azure", toml_path=_missing_toml(tmp_path))

    assert cfg.azure_endpoint == "https://env.openai.azure.com"
    assert cfg.azure_deployment == "env-deploy"
    assert cfg.azure_api_version == "2024-envver"
    assert cfg.api_key == "azure-secret"


def test_azure_fields_from_toml_when_no_env(tmp_path) -> None:  # type: ignore[no-untyped-def]
    toml_path = _write_toml(
        tmp_path,
        (
            "[provider]\n"
            'name = "azure"\n'
            'azure_endpoint = "https://toml.openai.azure.com"\n'
            'azure_deployment = "toml-deploy"\n'
            'azure_api_version = "2024-tomlver"\n'
        ),
    )

    cfg = resolve_provider_config(toml_path=toml_path)

    assert cfg.azure_endpoint == "https://toml.openai.azure.com"
    assert cfg.azure_deployment == "toml-deploy"
    assert cfg.azure_api_version == "2024-tomlver"


def test_azure_env_wins_over_toml_endpoint(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    toml_path = _write_toml(
        tmp_path,
        '[provider]\nname = "azure"\nazure_endpoint = "https://toml.example.com"\n',
    )
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://env.example.com")

    cfg = resolve_provider_config(toml_path=toml_path)

    assert cfg.azure_endpoint == "https://env.example.com"


def test_azure_api_version_default(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cfg = resolve_provider_config(cli_provider="azure", toml_path=_missing_toml(tmp_path))

    assert cfg.azure_endpoint is None
    assert cfg.azure_deployment is None
    assert cfg.azure_api_version == "2025-01-01-preview"


# ---------------------------------------------------------------------------
# Azure validate_config ordering: endpoint -> deployment -> api_key
# ---------------------------------------------------------------------------


def _azure_cfg(**kwargs) -> ProviderConfig:  # type: ignore[no-untyped-def]
    defaults = dict(
        provider_name="azure",
        model="gpt-4o",
        api_key="k",
        azure_endpoint="https://x.openai.azure.com",
        azure_deployment="dep",
    )
    defaults.update(kwargs)
    return ProviderConfig(**defaults)  # type: ignore[arg-type]


def test_azure_validate_reports_endpoint_first() -> None:
    # openai must be importable for validate_config to reach the field checks.
    pytest.importorskip("openai")
    # Everything missing at once -> endpoint is the first failure reported.
    provider = AzureOpenAIProvider(
        _azure_cfg(azure_endpoint=None, azure_deployment=None, api_key="")
    )
    with pytest.raises(ProviderConfigError, match="azure_endpoint"):
        provider.validate_config()


def test_azure_validate_reports_deployment_when_endpoint_present() -> None:
    pytest.importorskip("openai")
    # Endpoint present, deployment + key missing -> deployment is next.
    provider = AzureOpenAIProvider(_azure_cfg(azure_deployment=None, api_key=""))
    with pytest.raises(ProviderConfigError, match="azure_deployment"):
        provider.validate_config()


def test_azure_validate_reports_api_key_last() -> None:
    pytest.importorskip("openai")
    # Endpoint + deployment present, only key missing -> api key error.
    provider = AzureOpenAIProvider(_azure_cfg(api_key=""))
    with pytest.raises(ProviderConfigError, match="API key"):
        provider.validate_config()


def test_azure_validate_passes_when_complete() -> None:
    pytest.importorskip("openai")
    provider = AzureOpenAIProvider(_azure_cfg())
    provider.validate_config()  # should not raise


# ---------------------------------------------------------------------------
# _read_toml helper
# ---------------------------------------------------------------------------


def test_read_toml_missing_file_returns_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert _read_toml(_missing_toml(tmp_path)) == {}


def test_read_toml_valid_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    toml_path = _write_toml(tmp_path, _FULL_PROVIDER_TOML)

    data = _read_toml(toml_path)

    assert data["provider"]["name"] == "openai"
    assert data["provider"]["model"] == "gpt-4o-toml"
    assert data["provider"]["max_tokens"] == 8000


# ---------------------------------------------------------------------------
# resolve_ci_config
# ---------------------------------------------------------------------------


def test_ci_config_defaults(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cfg = resolve_ci_config(toml_path=_missing_toml(tmp_path))

    assert isinstance(cfg, CiConfig)
    assert cfg.enabled is True
    assert cfg.schedule is None
    assert cfg.change_detection is False
    assert cfg.watch_paths == []


def test_ci_config_from_toml(tmp_path) -> None:  # type: ignore[no-untyped-def]
    toml_path = _write_toml(
        tmp_path,
        (
            "[ci]\n"
            "enabled = false\n"
            'schedule = "0 3 * * *"\n'
            "change_detection = true\n"
            'watch_paths = ["agents/", "prompts/"]\n'
        ),
    )

    cfg = resolve_ci_config(toml_path=toml_path)

    assert cfg.enabled is False
    assert cfg.schedule == "0 3 * * *"
    assert cfg.change_detection is True
    assert cfg.watch_paths == ["agents/", "prompts/"]


# ---------------------------------------------------------------------------
# resolve_graph_config defaults
# ---------------------------------------------------------------------------


def test_graph_config_defaults(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("AWAF_GRAPH", raising=False)

    cfg = resolve_graph_config(toml_path=_missing_toml(tmp_path))

    assert isinstance(cfg, GraphConfig)
    assert cfg.enabled is True
    assert cfg.refresh is False
    assert cfg.extract_tokens == 150_000
    assert cfg.slice_budget == 12_000
    assert cfg.cache_max == 8
    assert cfg.context_lines == 20
    assert cfg.starvation_retry is True
