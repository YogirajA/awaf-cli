from __future__ import annotations

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


class GoogleProvider(LLMProvider):
    """Adapter for Google Gemini via google-genai SDK."""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    @property
    def default_model(self) -> str:
        return "gemini-2.0-flash"

    @property
    def supports_system_prompt(self) -> bool:
        return True

    def validate_config(self) -> None:
        try:
            import google.genai  # noqa: F401
        except ImportError as exc:
            raise ProviderError(
                "Provider 'google' requires additional dependencies. Run: pip install awaf[google]",
                provider=self.config.provider_name,
                model=self.config.model,
            ) from exc

        if not self.config.api_key:
            raise ProviderConfigError(
                "Google provider requires an API key. Set GOOGLE_API_KEY or api_key in awaf.toml.",
                provider=self.config.provider_name,
                model=self.config.model,
            )

    def complete(self, system_prompt: str, user_prompt: str) -> ProviderResponse:
        import google.api_core.exceptions
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.config.api_key)
        model_name = self.config.model or self.default_model

        t0 = time.monotonic()
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=self.config.temperature,
                    max_output_tokens=self.config.max_tokens,
                ),
            )
        except google.api_core.exceptions.ResourceExhausted as exc:
            raise ProviderRateLimitError(
                str(exc),
                provider=self.config.provider_name,
                model=model_name,
            ) from exc
        except google.api_core.exceptions.Unauthenticated as exc:
            raise ProviderAuthError(
                str(exc),
                provider=self.config.provider_name,
                model=model_name,
            ) from exc
        except google.api_core.exceptions.DeadlineExceeded as exc:
            raise ProviderTimeoutError(
                str(exc),
                provider=self.config.provider_name,
                model=model_name,
            ) from exc

        latency_ms = int((time.monotonic() - t0) * 1000)

        content = response.text if response.text else ""
        usage = response.usage_metadata
        candidates = response.candidates or []

        return ProviderResponse(
            content=content,
            input_tokens=int(usage.prompt_token_count or 0) if usage else 0,
            output_tokens=int(usage.candidates_token_count or 0) if usage else 0,
            model=model_name,
            provider=self.config.provider_name,
            latency_ms=latency_ms,
            raw={"candidates": [str(c) for c in candidates]},
        )

    def count_tokens(self, text: str) -> int:
        try:
            from google import genai

            client = genai.Client(api_key=self.config.api_key)
            model_name = self.config.model or self.default_model
            result = client.models.count_tokens(model=model_name, contents=text)
            return int(result.total_tokens or 0)
        except Exception:
            return max(1, len(text) // 4)
