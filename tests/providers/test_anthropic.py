from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from awaf.providers.anthropic import AnthropicProvider
from awaf.providers.base import (
    ProviderAuthError,
    ProviderConfig,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderTimeoutError,
)


def _cfg(**kwargs) -> ProviderConfig:  # type: ignore[no-untyped-def]
    defaults = dict(
        provider_name="anthropic",
        model="claude-opus-4-5",
        api_key="test-key",
        temperature=0.5,
    )
    defaults.update(kwargs)
    return ProviderConfig(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_complete_happy_path() -> None:
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Hello, world!")]
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 5
    mock_response.model = "claude-opus-4-5"
    mock_response.model_dump.return_value = {}

    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.messages.create.return_value = mock_response

        provider = AnthropicProvider(_cfg())
        result = provider.complete("sys", "usr")

    assert isinstance(result, ProviderResponse)
    assert result.content == "Hello, world!"
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.model == "claude-opus-4-5"
    assert result.provider == "anthropic"
    assert result.latency_ms >= 0


# ---------------------------------------------------------------------------
# 2. Rate limit → ProviderRateLimitError
# ---------------------------------------------------------------------------


def test_complete_rate_limit() -> None:
    import anthropic

    mock_response = MagicMock()
    mock_response.headers = {"retry-after": "30"}
    err = anthropic.APIStatusError("rate limited", response=mock_response, body={})
    err.status_code = 429

    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.messages.create.side_effect = err

        provider = AnthropicProvider(_cfg())
        with pytest.raises(ProviderRateLimitError) as exc_info:
            provider.complete("sys", "usr")

    assert exc_info.value.provider == "anthropic"
    assert exc_info.value.model == "claude-opus-4-5"
    assert exc_info.value.retry_after_seconds == 30


# ---------------------------------------------------------------------------
# 3. Auth error → ProviderAuthError
# ---------------------------------------------------------------------------


def test_complete_auth_error() -> None:
    import anthropic

    mock_response = MagicMock()
    mock_response.headers = {}
    err = anthropic.APIStatusError("unauthorized", response=mock_response, body={})
    err.status_code = 401

    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.messages.create.side_effect = err

        provider = AnthropicProvider(_cfg())
        with pytest.raises(ProviderAuthError) as exc_info:
            provider.complete("sys", "usr")

    assert exc_info.value.provider == "anthropic"


# ---------------------------------------------------------------------------
# 4. Timeout → ProviderTimeoutError
# ---------------------------------------------------------------------------


def test_complete_timeout() -> None:
    import anthropic

    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.messages.create.side_effect = anthropic.APITimeoutError(request=MagicMock())

        provider = AnthropicProvider(_cfg())
        with pytest.raises(ProviderTimeoutError):
            provider.complete("sys", "usr")


# ---------------------------------------------------------------------------
# 5. count_tokens returns positive int
# ---------------------------------------------------------------------------


def test_count_tokens() -> None:
    mock_result = MagicMock()
    mock_result.input_tokens = 3

    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.beta.messages.count_tokens.return_value = mock_result

        provider = AnthropicProvider(_cfg())
        count = provider.count_tokens("hello world")

    assert count > 0


# ---------------------------------------------------------------------------
# 6. validate_config raises on missing api_key
# ---------------------------------------------------------------------------


def test_validate_config_missing_key() -> None:
    from awaf.providers.base import ProviderConfigError

    provider = AnthropicProvider(_cfg(api_key=""))
    with pytest.raises(ProviderConfigError):
        provider.validate_config()


# ---------------------------------------------------------------------------
# 7. Integration test (skipped unless ANTHROPIC_API_KEY is set)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
def test_integration_real_call() -> None:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    provider = AnthropicProvider(_cfg(api_key=api_key, model="claude-haiku-4-5", max_tokens=50))
    result = provider.complete("You are a helpful assistant.", "Say hello in one word.")
    assert result.content
    assert result.input_tokens > 0
    assert result.output_tokens > 0
