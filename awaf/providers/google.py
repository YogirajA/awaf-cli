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
        self._client: object = None  # lazy-initialised on first use

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

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        artifact_content: str | None = None,
    ) -> ProviderResponse:
        from google import genai
        from google.genai import types

        if artifact_content:
            sep = chr(10) + chr(10)
            user_prompt = artifact_content + sep + user_prompt
        if self._client is None:
            self._client = genai.Client(api_key=self.config.api_key)
        client: genai.Client = self._client  # type: ignore[assignment]
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
        except Exception as exc:
            self._raise_provider_error(exc, model_name)
            raise  # unreachable; satisfies type checker

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
        # Heuristic avoids API round-trips per file during ingest.
        # Set AWAF_EXACT_TOKEN_COUNT=1 to use the Google count_tokens API.
        import os

        if not os.environ.get("AWAF_EXACT_TOKEN_COUNT"):
            return max(1, len(text) // 4)
        try:
            from google import genai

            if self._client is None:
                self._client = genai.Client(api_key=self.config.api_key)
            client: genai.Client = self._client  # type: ignore[assignment]
            model_name = self.config.model or self.default_model
            result = client.models.count_tokens(model=model_name, contents=text)
            return int(result.total_tokens or 0)
        except Exception:
            return max(1, len(text) // 4)

    def _raise_provider_error(self, exc: Exception, model_name: str) -> None:
        """Map google-genai SDK exceptions to provider exceptions."""
        # status code is 'code' in google.genai.errors, may also be 'status_code'
        code = int(getattr(exc, "code", 0) or getattr(exc, "status_code", 0) or 0)
        name = type(exc).__name__
        msg = str(exc)

        if code == 429 or name in ("ResourceExhausted", "RateLimitError"):
            raise ProviderRateLimitError(
                msg, provider=self.config.provider_name, model=model_name
            ) from exc
        if code in (401, 403) or name in ("Unauthenticated", "PermissionDenied"):
            raise ProviderAuthError(
                msg, provider=self.config.provider_name, model=model_name
            ) from exc
        if isinstance(exc, TimeoutError) or name in ("DeadlineExceeded", "TimeoutError"):
            raise ProviderTimeoutError(
                msg, provider=self.config.provider_name, model=model_name
            ) from exc
        raise ProviderError(msg, provider=self.config.provider_name, model=model_name) from exc
