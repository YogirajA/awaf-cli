from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ProviderConfig:
    """
    Resolved provider configuration. Built by config.py from awaf.toml + env vars.
    Concrete adapters receive this; they do not read env vars or toml directly.
    """

    provider_name: str  # "anthropic" | "openai" | "azure" | "google" | "litellm"
    model: str  # full model string, e.g. "gpt-4o", "claude-opus-4-5"
    api_key: str  # resolved from env var
    max_tokens: int = 4096
    temperature: float = 0.5
    timeout_seconds: int = 120
    max_retries: int = 3
    # Azure-specific (ignored by non-Azure adapters)
    azure_endpoint: str | None = None
    azure_deployment: str | None = None
    azure_api_version: str = "2025-01-01-preview"
    # LiteLLM-specific
    litellm_extra_params: dict = field(default_factory=dict)  # type: ignore[type-arg]


@dataclass
class ProviderResponse:
    """
    Normalized response returned by all adapters.
    Pillar agents consume this; they never touch raw provider SDK objects.
    """

    content: str  # the model's text response
    input_tokens: int
    output_tokens: int
    model: str  # actual model used (may differ from requested for aliases)
    provider: str  # "anthropic" | "openai" | etc.
    latency_ms: int
    raw: dict = field(default_factory=dict)  # type: ignore[type-arg]  # raw response dict for debugging; never used in scoring


class LLMProvider(ABC):
    """
    Abstract base class for all provider adapters.
    All methods must be implemented. No optional methods.
    """

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> ProviderResponse:
        """
        Synchronous single-turn completion.
        Called by each pillar agent for its evaluation.

        - system_prompt: AWAF pillar evaluation instructions
        - user_prompt: serialized artifact content for this pillar
        - Must raise ProviderError on non-retryable failures
        - Must raise ProviderRateLimitError on rate limit / quota errors
        - Must raise ProviderTimeoutError on timeout
        """
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for the given text using this provider's tokenizer.
        Used by the ingestor to enforce AWAF_MAX_ARTIFACTS_TOKENS.
        Exact accuracy not required; within 10% is acceptable.
        """
        ...

    @abstractmethod
    def validate_config(self) -> None:
        """
        Validate that the provider config is complete and the API key is present.
        Called at startup before any assessment begins.
        Must raise ProviderConfigError with a human-readable message on failure.
        """
        ...

    @property
    @abstractmethod
    def default_model(self) -> str:
        """
        Default model string for this provider if none is specified in config.
        """
        ...

    @property
    @abstractmethod
    def supports_system_prompt(self) -> bool:
        """
        True for all current providers. Reserved for future providers that
        require system prompt content to be merged into user turn.
        """
        ...


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Base class for all provider errors."""

    def __init__(self, message: str, provider: str, model: str) -> None:
        self.provider = provider
        self.model = model
        super().__init__(f"[{provider}/{model}] {message}")


class ProviderConfigError(ProviderError):
    """Raised by validate_config() when configuration is invalid or incomplete."""

    pass


class ProviderRateLimitError(ProviderError):
    """
    Raised when the provider returns a rate limit or quota error.
    The retry layer in awaf/retry.py catches this and applies backoff.
    """

    def __init__(
        self,
        message: str,
        provider: str,
        model: str,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message, provider, model)


class ProviderTimeoutError(ProviderError):
    """Raised when a request exceeds config.timeout_seconds."""

    pass


class ProviderAuthError(ProviderError):
    """Raised on 401/403 responses. Not retried."""

    pass
