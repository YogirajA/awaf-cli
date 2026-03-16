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
)


class LiteLLMProvider(LLMProvider):
    """
    Catch-all adapter via LiteLLM.

    Supports Bedrock, Vertex, Groq, Ollama, Mistral, and dozens more.
    Pass the full LiteLLM model string, e.g.:
      - "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"
      - "ollama/llama3"
      - "groq/llama-3.1-8b-instant"
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    @property
    def default_model(self) -> str:
        # LiteLLM has no sensible default; validate_config enforces model presence.
        return ""

    @property
    def supports_system_prompt(self) -> bool:
        return True

    def validate_config(self) -> None:
        try:
            import litellm  # noqa: F401
        except ImportError as exc:
            raise ProviderError(
                "Provider 'litellm' requires additional dependencies. Run: pip install awaf[litellm]",
                provider=self.config.provider_name,
                model=self.config.model,
            ) from exc

        if not self.config.model:
            raise ProviderConfigError(
                "LiteLLM provider requires a model string. "
                "Set AWAF_MODEL or model in awaf.toml (e.g. 'ollama/llama3', 'bedrock/...').",
                provider=self.config.provider_name,
                model="",
            )

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        artifact_content: str | None = None,
    ) -> ProviderResponse:
        import litellm

        if artifact_content:
            sep = chr(10) + chr(10)
            user_prompt = artifact_content + sep + user_prompt
        model = self.config.model

        t0 = time.monotonic()
        try:
            response = litellm.completion(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                **self.config.litellm_extra_params,
            )
        except litellm.RateLimitError as exc:  # type: ignore[attr-defined]
            raise ProviderRateLimitError(
                str(exc),
                provider=self.config.provider_name,
                model=model,
            ) from exc
        except litellm.AuthenticationError as exc:  # type: ignore[attr-defined]
            raise ProviderAuthError(
                str(exc),
                provider=self.config.provider_name,
                model=model,
            ) from exc
        except Exception as exc:
            raise ProviderError(
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
            model=response.model or model,
            provider=self.config.provider_name,
            latency_ms=latency_ms,
            raw=response.model_dump() if hasattr(response, "model_dump") else {},
        )

    def count_tokens(self, text: str) -> int:
        try:
            import litellm

            model = self.config.model
            return int(litellm.token_counter(model=model, text=text))
        except Exception:
            return max(1, len(text) // 4)
