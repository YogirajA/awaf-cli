from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from awaf.providers.azure import AzureOpenAIProvider
from awaf.providers.base import (
    ProviderAuthError,
    ProviderConfig,
    ProviderConfigError,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderTimeoutError,
)


def _cfg(**kwargs) -> ProviderConfig:  # type: ignore[no-untyped-def]
    defaults = dict(
        provider_name="azure",
        model="gpt-4o",
        api_key="test-key",
        azure_endpoint="https://my-resource.openai.azure.com",
        azure_deployment="my-deployment",
        temperature=0.5,
    )
    defaults.update(kwargs)
    return ProviderConfig(**defaults)  # type: ignore[arg-type]


def _mock_response(content: str = "OK") -> MagicMock:
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
    with patch("openai.AzureOpenAI") as mock_cls:
        mock_cls.return_value.chat.completions.create.return_value = _mock_response("Azure!")
        provider = AzureOpenAIProvider(_cfg())
        result = provider.complete("sys", "usr")

    assert isinstance(result, ProviderResponse)
    assert result.content == "Azure!"
    assert result.model == "gpt-4o"  # config.model, not deployment name
    assert result.provider == "azure"


# ---------------------------------------------------------------------------
# 2. Rate limit
# ---------------------------------------------------------------------------


def test_complete_rate_limit() -> None:
    import openai

    with patch("openai.AzureOpenAI") as mock_cls:
        mock_cls.return_value.chat.completions.create.side_effect = openai.RateLimitError(
            "rate limited", response=MagicMock(), body={}
        )
        provider = AzureOpenAIProvider(_cfg())
        with pytest.raises(ProviderRateLimitError) as exc_info:
            provider.complete("sys", "usr")

    assert exc_info.value.provider == "azure"


# ---------------------------------------------------------------------------
# 3. Auth error
# ---------------------------------------------------------------------------


def test_complete_auth_error() -> None:
    import openai

    with patch("openai.AzureOpenAI") as mock_cls:
        mock_cls.return_value.chat.completions.create.side_effect = openai.AuthenticationError(
            "bad key", response=MagicMock(), body={}
        )
        provider = AzureOpenAIProvider(_cfg())
        with pytest.raises(ProviderAuthError):
            provider.complete("sys", "usr")


# ---------------------------------------------------------------------------
# 4. Timeout
# ---------------------------------------------------------------------------


def test_complete_timeout() -> None:
    import openai

    with patch("openai.AzureOpenAI") as mock_cls:
        mock_cls.return_value.chat.completions.create.side_effect = openai.APITimeoutError(
            request=MagicMock()
        )
        provider = AzureOpenAIProvider(_cfg())
        with pytest.raises(ProviderTimeoutError):
            provider.complete("sys", "usr")


# ---------------------------------------------------------------------------
# 5. count_tokens
# ---------------------------------------------------------------------------


def test_count_tokens() -> None:
    with patch("tiktoken.encoding_for_model") as mock_enc_fn:
        mock_enc = MagicMock()
        mock_enc.encode.return_value = [1, 2, 3]
        mock_enc_fn.return_value = mock_enc

        provider = AzureOpenAIProvider(_cfg())
        count = provider.count_tokens("hello world")

    assert count > 0


# ---------------------------------------------------------------------------
# 6. validate_config — missing endpoint
# ---------------------------------------------------------------------------


def test_validate_config_missing_endpoint() -> None:
    provider = AzureOpenAIProvider(_cfg(azure_endpoint=None))
    with pytest.raises(ProviderConfigError, match="azure_endpoint"):
        provider.validate_config()


# ---------------------------------------------------------------------------
# 7. validate_config — missing deployment
# ---------------------------------------------------------------------------


def test_validate_config_missing_deployment() -> None:
    provider = AzureOpenAIProvider(_cfg(azure_deployment=None))
    with pytest.raises(ProviderConfigError, match="azure_deployment"):
        provider.validate_config()


# ---------------------------------------------------------------------------
# 8. validate_config — missing api_key
# ---------------------------------------------------------------------------


def test_validate_config_missing_key() -> None:
    provider = AzureOpenAIProvider(_cfg(api_key=""))
    with pytest.raises(ProviderConfigError):
        provider.validate_config()


# ---------------------------------------------------------------------------
# 9. Integration
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("AZURE_OPENAI_API_KEY"),
    reason="AZURE_OPENAI_API_KEY not set",
)
def test_integration_real_call() -> None:
    provider = AzureOpenAIProvider(
        _cfg(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
            azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", ""),
            max_tokens=50,
        )
    )
    result = provider.complete("You are a helpful assistant.", "Say hello in one word.")
    assert result.content
    assert result.input_tokens > 0
    assert result.output_tokens > 0
