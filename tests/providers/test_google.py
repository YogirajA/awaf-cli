from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from awaf.providers.base import (
    ProviderAuthError,
    ProviderConfig,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderTimeoutError,
)
from awaf.providers.google import GoogleProvider


def _cfg(**kwargs) -> ProviderConfig:  # type: ignore[no-untyped-def]
    defaults = dict(
        provider_name="google",
        model="gemini-2.0-flash",
        api_key="test-key",
        temperature=0.5,
    )
    defaults.update(kwargs)
    return ProviderConfig(**defaults)  # type: ignore[arg-type]


def _mock_genai_response(text: str = "Gemini response") -> MagicMock:
    usage = MagicMock()
    usage.prompt_token_count = 10
    usage.candidates_token_count = 5
    candidate = MagicMock()
    response = MagicMock()
    response.text = text
    response.usage_metadata = usage
    response.candidates = [candidate]
    return response


# ---------------------------------------------------------------------------
# SDK-agnostic error stubs (avoids google.api_core dependency in tests)
# ---------------------------------------------------------------------------


class _RateLimitError(Exception):
    code = 429


class _AuthError(Exception):
    code = 401


class _TimeoutError(TimeoutError):
    pass


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_complete_happy_path() -> None:
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.models.generate_content.return_value = _mock_genai_response("Hi from Gemini!")

        provider = GoogleProvider(_cfg())
        result = provider.complete("sys", "usr")

    assert isinstance(result, ProviderResponse)
    assert result.content == "Hi from Gemini!"
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.provider == "google"


# ---------------------------------------------------------------------------
# 2. Rate limit
# ---------------------------------------------------------------------------


def test_complete_rate_limit() -> None:
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.models.generate_content.side_effect = _RateLimitError("quota exceeded")

        provider = GoogleProvider(_cfg())
        with pytest.raises(ProviderRateLimitError) as exc_info:
            provider.complete("sys", "usr")

    assert exc_info.value.provider == "google"


# ---------------------------------------------------------------------------
# 3. Auth error
# ---------------------------------------------------------------------------


def test_complete_auth_error() -> None:
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.models.generate_content.side_effect = _AuthError("bad key")

        provider = GoogleProvider(_cfg())
        with pytest.raises(ProviderAuthError):
            provider.complete("sys", "usr")


# ---------------------------------------------------------------------------
# 4. Timeout
# ---------------------------------------------------------------------------


def test_complete_timeout() -> None:
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.models.generate_content.side_effect = _TimeoutError("timed out")

        provider = GoogleProvider(_cfg())
        with pytest.raises(ProviderTimeoutError):
            provider.complete("sys", "usr")


# ---------------------------------------------------------------------------
# 5. count_tokens
# ---------------------------------------------------------------------------


def test_count_tokens() -> None:
    mock_count = MagicMock()
    mock_count.total_tokens = 4

    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.models.count_tokens.return_value = mock_count

        provider = GoogleProvider(_cfg())
        count = provider.count_tokens("hello world")

    assert count > 0


# ---------------------------------------------------------------------------
# 6. validate_config missing key
# ---------------------------------------------------------------------------


def test_validate_config_missing_key() -> None:
    from awaf.providers.base import ProviderConfigError

    provider = GoogleProvider(_cfg(api_key=""))
    with pytest.raises(ProviderConfigError):
        provider.validate_config()


# ---------------------------------------------------------------------------
# 7. Integration
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set",
)
def test_integration_real_call() -> None:
    provider = GoogleProvider(
        _cfg(api_key=os.environ["GOOGLE_API_KEY"], model="gemini-2.0-flash", max_tokens=50)
    )
    result = provider.complete("You are a helpful assistant.", "Say hello in one word.")
    assert result.content
    assert result.input_tokens > 0
    assert result.output_tokens > 0
