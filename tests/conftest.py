from __future__ import annotations

import os

import pytest

from awaf.providers.base import ProviderConfig


def _make_config(**kwargs) -> ProviderConfig:  # type: ignore[no-untyped-def]
    """Build a ProviderConfig with test-safe defaults."""
    defaults = dict(
        provider_name="anthropic",
        model="claude-opus-4-5",
        api_key="test-key",
        temperature=0.5,
    )
    defaults.update(kwargs)
    return ProviderConfig(**defaults)  # type: ignore[arg-type]


# Expose helper for test modules
make_config = _make_config


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (requires real API key, skipped in CI)",
    )


def _skip_if_no_key(env_var: str) -> pytest.MarkDecorator:
    """Return a pytest.mark.skipif that skips when *env_var* is not set."""
    return pytest.mark.skipif(
        not os.environ.get(env_var),
        reason=f"{env_var} not set; skipping integration test",
    )


skip_no_anthropic = _skip_if_no_key("ANTHROPIC_API_KEY")
skip_no_openai = _skip_if_no_key("OPENAI_API_KEY")
skip_no_azure = _skip_if_no_key("AZURE_OPENAI_API_KEY")
skip_no_google = _skip_if_no_key("GOOGLE_API_KEY")
