from __future__ import annotations

import logging
import time

from awaf.providers.base import (
    LLMProvider,
    ProviderAuthError,
    ProviderConfig,
    ProviderConfigError,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderTimeoutError,
)

logger = logging.getLogger(__name__)

# Model alias normalization for SDK compatibility
_MODEL_ALIASES: dict[str, str] = {
    "o3": "o3-2025-04-16",
    "o4-mini": "o4-mini-2025-04-16",
}


def _normalize_model(model: str) -> str:
    normalized = _MODEL_ALIASES.get(model, model)
    if normalized != model:
        logger.debug("Model alias normalized: %s -> %s", model, normalized)
    return normalized


class OpenAIProvider(LLMProvider):
    """Adapter for the OpenAI Chat Completions API."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._client: object = None  # lazy-initialised on first use

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    @property
    def default_model(self) -> str:
        return "gpt-4o"

    @property
    def supports_system_prompt(self) -> bool:
        return True

    def validate_config(self) -> None:
        try:
            import openai  # noqa: F401
        except ImportError as exc:
            raise ProviderConfigError(
                "Provider 'openai' requires additional dependencies. Run: pip install awaf[openai]",
                provider=self.config.provider_name,
                model=self.config.model,
            ) from exc

        if not self.config.api_key:
            raise ProviderConfigError(
                "OpenAI provider requires an API key. Set OPENAI_API_KEY or api_key in awaf.toml.",
                provider=self.config.provider_name,
                model=self.config.model,
            )

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        artifact_content: str | None = None,
    ) -> ProviderResponse:
        import openai

        if artifact_content:
            sep = chr(10) + chr(10)
            user_prompt = artifact_content + sep + user_prompt
        if self._client is None:
            self._client = openai.OpenAI(api_key=self.config.api_key)
        client: openai.OpenAI = self._client  # type: ignore[assignment]
        model = _normalize_model(self.config.model or self.default_model)

        t0 = time.monotonic()
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                seed=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except openai.RateLimitError as exc:
            raise ProviderRateLimitError(
                str(exc),
                provider=self.config.provider_name,
                model=model,
            ) from exc
        except openai.AuthenticationError as exc:
            raise ProviderAuthError(
                str(exc),
                provider=self.config.provider_name,
                model=model,
            ) from exc
        except openai.APITimeoutError as exc:
            raise ProviderTimeoutError(
                str(exc),
                provider=self.config.provider_name,
                model=model,
            ) from exc

        latency_ms = int((time.monotonic() - t0) * 1000)

        choice = response.choices[0]
        content = choice.message.content or ""
        usage = response.usage

        return ProviderResponse(
            content=content,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=response.model,
            provider=self.config.provider_name,
            latency_ms=latency_ms,
            raw=response.model_dump(),
        )

    def count_tokens(self, text: str) -> int:
        try:
            import tiktoken

            model = self.config.model or self.default_model
            try:
                enc = tiktoken.encoding_for_model(model)
            except KeyError:
                enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            return max(1, len(text) // 4)
