from __future__ import annotations

from awaf.providers.anthropic import AnthropicProvider
from awaf.providers.azure import AzureOpenAIProvider
from awaf.providers.base import (
    LLMProvider,
    ProviderAuthError,
    ProviderConfig,
    ProviderConfigError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderTimeoutError,
)
from awaf.providers.google import GoogleProvider
from awaf.providers.litellm import LiteLLMProvider
from awaf.providers.openai import OpenAIProvider

_REGISTRY: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "azure": AzureOpenAIProvider,
    "google": GoogleProvider,
    "litellm": LiteLLMProvider,
}


def get_provider(config: ProviderConfig) -> LLMProvider:
    """
    Instantiate and validate the provider for the given config.
    Raises ProviderConfigError if provider name is unknown or config is invalid.
    """
    cls = _REGISTRY.get(config.provider_name)
    if cls is None:
        known = ", ".join(_REGISTRY.keys())
        raise ProviderConfigError(
            f"Unknown provider '{config.provider_name}'. Known providers: {known}",
            provider=config.provider_name,
            model=config.model,
        )
    provider = cls(config)
    provider.validate_config()
    return provider


def list_providers() -> list[str]:
    return list(_REGISTRY.keys())


__all__ = [
    "get_provider",
    "list_providers",
    "LLMProvider",
    "ProviderConfig",
    "ProviderResponse",
    "ProviderError",
    "ProviderConfigError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ProviderAuthError",
    "AnthropicProvider",
    "OpenAIProvider",
    "AzureOpenAIProvider",
    "GoogleProvider",
    "LiteLLMProvider",
]
