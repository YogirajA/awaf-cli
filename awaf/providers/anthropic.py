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
        return "claude-haiku-4-5-20251001"

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
                # Cache the system prompt (pillar criteria) — helps on repeated runs
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                # Cache the user prompt (artifact content) — same across all 10 pillars
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": user_prompt,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    }
                ],
                extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
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

        # Sum all input token types: regular + cache-creation + cache-read.
        # cache_creation/read are not present on older SDK versions → default 0.
        cache_create = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
        total_input = response.usage.input_tokens + cache_create + cache_read

        return ProviderResponse(
            content=content,
            input_tokens=total_input,
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
