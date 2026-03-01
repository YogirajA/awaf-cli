from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from awaf.providers.base import (
    ProviderAuthError,
    ProviderConfig,
    ProviderConfigError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponse,
)
from awaf.providers.litellm import LiteLLMProvider


def _cfg(**kwargs) -> ProviderConfig:  # type: ignore[no-untyped-def]
    defaults = dict(
        provider_name="litellm",
        model="ollama/llama3",
        api_key="",
        temperature=0.5,
    )
    defaults.update(kwargs)
    return ProviderConfig(**defaults)  # type: ignore[arg-type]


def _mock_litellm_response(content: str = "LiteLLM reply") -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    usage = MagicMock()
    usage.prompt_tokens = 6
    usage.completion_tokens = 4
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    response.model = "ollama/llama3"
    response.model_dump.return_value = {}
    return response


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


def test_complete_happy_path() -> None:
    with patch("litellm.completion") as mock_completion:
        mock_completion.return_value = _mock_litellm_response("Hello via LiteLLM!")

        provider = LiteLLMProvider(_cfg())
        result = provider.complete("sys", "usr")

    assert isinstance(result, ProviderResponse)
    assert result.content == "Hello via LiteLLM!"
    assert result.input_tokens == 6
    assert result.output_tokens == 4
    assert result.provider == "litellm"


# ---------------------------------------------------------------------------
# 2. Rate limit
# ---------------------------------------------------------------------------


def test_complete_rate_limit() -> None:
    import litellm

    with patch("litellm.completion") as mock_completion:
        mock_completion.side_effect = litellm.RateLimitError(
            message="rate limited", llm_provider="ollama", model="llama3"
        )

        provider = LiteLLMProvider(_cfg())
        with pytest.raises(ProviderRateLimitError) as exc_info:
            provider.complete("sys", "usr")

    assert exc_info.value.provider == "litellm"


# ---------------------------------------------------------------------------
# 3. Auth error
# ---------------------------------------------------------------------------


def test_complete_auth_error() -> None:
    import litellm

    with patch("litellm.completion") as mock_completion:
        mock_completion.side_effect = litellm.AuthenticationError(
            message="bad key", llm_provider="groq", model="llama3"
        )

        provider = LiteLLMProvider(_cfg())
        with pytest.raises(ProviderAuthError):
            provider.complete("sys", "usr")


# ---------------------------------------------------------------------------
# 4. Generic exception → ProviderError
# ---------------------------------------------------------------------------


def test_complete_generic_error() -> None:
    with patch("litellm.completion") as mock_completion:
        mock_completion.side_effect = RuntimeError("something went wrong")

        provider = LiteLLMProvider(_cfg())
        with pytest.raises(ProviderError):
            provider.complete("sys", "usr")


# ---------------------------------------------------------------------------
# 5. count_tokens
# ---------------------------------------------------------------------------


def test_count_tokens() -> None:
    with patch("litellm.token_counter") as mock_counter:
        mock_counter.return_value = 5

        provider = LiteLLMProvider(_cfg())
        count = provider.count_tokens("hello world")

    assert count > 0


# ---------------------------------------------------------------------------
# 6. validate_config — missing model
# ---------------------------------------------------------------------------


def test_validate_config_missing_model() -> None:
    provider = LiteLLMProvider(_cfg(model=""))
    with pytest.raises(ProviderConfigError, match="model"):
        provider.validate_config()


# ---------------------------------------------------------------------------
# 7. Integration (requires local Ollama or real backend)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("LITELLM_INTEGRATION_MODEL"),
    reason="LITELLM_INTEGRATION_MODEL not set",
)
def test_integration_real_call() -> None:
    model = os.environ["LITELLM_INTEGRATION_MODEL"]
    provider = LiteLLMProvider(_cfg(model=model, max_tokens=50))
    result = provider.complete("You are a helpful assistant.", "Say hello in one word.")
    assert result.content
    assert result.input_tokens > 0
    assert result.output_tokens > 0
