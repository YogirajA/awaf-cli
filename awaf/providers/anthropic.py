from __future__ import annotations

import contextlib
import time

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


class AnthropicProvider(LLMProvider):
    """Adapter for the Anthropic Messages API."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    @property
    def default_model(self) -> str:
        return "claude-opus-4-5"

    @property
    def supports_system_prompt(self) -> bool:
        return True

    def validate_config(self) -> None:
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:
            raise ProviderConfigError(
                "Provider 'anthropic' requires additional dependencies. Run: pip install awaf[anthropic]",
                provider=self.config.provider_name,
                model=self.config.model,
            ) from exc

        if not self.config.api_key:
            raise ProviderConfigError(
                "Anthropic provider requires an API key. Set ANTHROPIC_API_KEY or api_key in awaf.toml.",
                provider=self.config.provider_name,
                model=self.config.model,
            )

    def complete(self, system_prompt: str, user_prompt: str) -> ProviderResponse:
        import anthropic

        client = anthropic.Anthropic(api_key=self.config.api_key)
        model = self.config.model or self.default_model

        t0 = time.monotonic()
        try:
            response = client.messages.create(
                model=model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.APIStatusError as exc:
            if exc.status_code == 429:
                retry_after: int | None = None
                raw_after = exc.response.headers.get("retry-after")
                if raw_after is not None:
                    with contextlib.suppress(ValueError):
                        retry_after = int(raw_after)
                raise ProviderRateLimitError(
                    str(exc),
                    provider=self.config.provider_name,
                    model=model,
                    retry_after_seconds=retry_after,
                ) from exc
            if exc.status_code in (401, 403):
                raise ProviderAuthError(
                    str(exc),
                    provider=self.config.provider_name,
                    model=model,
                ) from exc
            raise ProviderError(
                str(exc),
                provider=self.config.provider_name,
                model=model,
            ) from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderTimeoutError(
                str(exc),
                provider=self.config.provider_name,
                model=model,
            ) from exc

        latency_ms = int((time.monotonic() - t0) * 1000)

        # Duck typing: only TextBlock has a str .text; other block types are skipped
        text_blocks = [
            b for b in response.content if hasattr(b, "text") and isinstance(b.text, str)
        ]
        content = text_blocks[0].text if text_blocks else ""
        return ProviderResponse(
            content=content,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
            provider=self.config.provider_name,
            latency_ms=latency_ms,
            raw=response.model_dump(),
        )

    def count_tokens(self, text: str) -> int:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self.config.api_key)
            model = self.config.model or self.default_model
            result = client.beta.messages.count_tokens(
                model=model,
                messages=[{"role": "user", "content": text}],
            )
            return result.input_tokens
        except Exception:
            # Fallback: ~4 chars per token
            return max(1, len(text) // 4)
