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
from awaf.providers.openai import OpenAIProvider


def _cfg(**kwargs) -> ProviderConfig:  # type: ignore[no-untyped-def]
    defaults = dict(
        provider_name="openai",
        model="gpt-4o",
        api_key="test-key",
        temperature=0.5,
    )
    defaults.update(kwargs)
    return ProviderConfig(**defaults)  # type: ignore[arg-type]


def _mock_openai_response(content: str = "OK") -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.prompt_tokens = 8
    usage.completion_tokens = 3
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    response.model = "gpt-4o"
    response.model_dump.return_value = {}
    return response


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_complete_happy_path() -> None:
    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value.chat.completions.create.return_value = _mock_openai_response("Hello!")
        provider = OpenAIProvider(_cfg())
        result = provider.complete("sys", "usr")

    assert isinstance(result, ProviderResponse)
    assert result.content == "Hello!"
    assert result.input_tokens == 8
    assert result.output_tokens == 3
    assert result.provider == "openai"


# ---------------------------------------------------------------------------
# 2. Rate limit
# ---------------------------------------------------------------------------


def test_complete_rate_limit() -> None:
    import openai

    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value.chat.completions.create.side_effect = openai.RateLimitError(
            "rate limited", response=MagicMock(), body={}
        )
        provider = OpenAIProvider(_cfg())
        with pytest.raises(ProviderRateLimitError) as exc_info:
            provider.complete("sys", "usr")

    assert exc_info.value.provider == "openai"


# ---------------------------------------------------------------------------
# 3. Auth error
# ---------------------------------------------------------------------------


def test_complete_auth_error() -> None:
    import openai

    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value.chat.completions.create.side_effect = openai.AuthenticationError(
            "bad key", response=MagicMock(), body={}
        )
        provider = OpenAIProvider(_cfg())
        with pytest.raises(ProviderAuthError):
            provider.complete("sys", "usr")


# ---------------------------------------------------------------------------
# 4. Timeout
# ---------------------------------------------------------------------------


def test_complete_timeout() -> None:
    import openai

    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value.chat.completions.create.side_effect = openai.APITimeoutError(
            request=MagicMock()
        )
        provider = OpenAIProvider(_cfg())
        with pytest.raises(ProviderTimeoutError):
            provider.complete("sys", "usr")


# ---------------------------------------------------------------------------
# 5. count_tokens
# ---------------------------------------------------------------------------


def test_count_tokens() -> None:
    with patch("tiktoken.encoding_for_model") as mock_enc_fn:
        mock_enc = MagicMock()
        mock_enc.encode.return_value = [1, 2]  # 2 tokens
        mock_enc_fn.return_value = mock_enc

        provider = OpenAIProvider(_cfg())
        count = provider.count_tokens("hello world")

    assert count > 0


# ---------------------------------------------------------------------------
# 6. validate_config missing key
# ---------------------------------------------------------------------------


def test_validate_config_missing_key() -> None:
    from awaf.providers.base import ProviderConfigError

    provider = OpenAIProvider(_cfg(api_key=""))
    with pytest.raises(ProviderConfigError):
        provider.validate_config()


# ---------------------------------------------------------------------------
# 7. Model alias normalization
# ---------------------------------------------------------------------------


def test_model_alias_o3() -> None:
    from awaf.providers.openai import _normalize_model

    assert _normalize_model("o3") == "o3-2025-04-16"


def test_model_alias_o4_mini() -> None:
    from awaf.providers.openai import _normalize_model

    assert _normalize_model("o4-mini") == "o4-mini-2025-04-16"


def test_model_alias_passthrough() -> None:
    from awaf.providers.openai import _normalize_model

    assert _normalize_model("gpt-4o") == "gpt-4o"


# ---------------------------------------------------------------------------
# 8. Integration
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)
def test_integration_real_call() -> None:
    api_key = os.environ["OPENAI_API_KEY"]
    provider = OpenAIProvider(_cfg(api_key=api_key, model="gpt-4o-mini", max_tokens=50))
    result = provider.complete("You are a helpful assistant.", "Say hello in one word.")
    assert result.content
    assert result.input_tokens > 0
    assert result.output_tokens > 0
