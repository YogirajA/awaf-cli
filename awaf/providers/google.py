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
    """Adapter for Google Gemini via google-generativeai SDK."""

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
            import google.generativeai  # noqa: F401
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
        import google.generativeai as genai

        genai.configure(api_key=self.config.api_key)  # type: ignore[attr-defined]
        model_name = self.config.model or self.default_model

        gmodel = genai.GenerativeModel(  # type: ignore[attr-defined]
            model_name,
            system_instruction=system_prompt,
        )

        # GenerationConfig accepts a dict via the GenerationConfigDict protocol
        generation_config = genai.types.GenerationConfig(
            temperature=self.config.temperature,
            max_output_tokens=self.config.max_tokens,
        )

        t0 = time.monotonic()
        try:
            response = gmodel.generate_content(
                user_prompt,
                generation_config=generation_config,
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

        return ProviderResponse(
            content=content,
            input_tokens=usage.prompt_token_count if usage else 0,
            output_tokens=usage.candidates_token_count if usage else 0,
            model=model_name,
            provider=self.config.provider_name,
            latency_ms=latency_ms,
            raw={"candidates": [str(c) for c in response.candidates]},
        )

    def count_tokens(self, text: str) -> int:
        try:
            import google.generativeai as genai

            genai.configure(api_key=self.config.api_key)  # type: ignore[attr-defined]
            model_name = self.config.model or self.default_model
            gmodel = genai.GenerativeModel(model_name)  # type: ignore[attr-defined]
            result = gmodel.count_tokens(text)
            return int(result.total_tokens)
        except Exception:
            return max(1, len(text) // 4)
