from __future__ import annotations

import logging
import random
import time

from awaf.providers.base import (
    LLMProvider,
    ProviderRateLimitError,
    ProviderResponse,
    ProviderTimeoutError,
)

logger = logging.getLogger(__name__)


def with_retry(
    provider: LLMProvider,
    system_prompt: str,
    user_prompt: str,
    artifact_content: str | None = None,
    max_retries: int = 3,
) -> ProviderResponse:
    """
    Call provider.complete() with exponential backoff.

    Retry on: ProviderRateLimitError, ProviderTimeoutError
    Do not retry on: ProviderAuthError, ProviderConfigError, ProviderError (other)

    Backoff: 2^attempt seconds (1s, 2s, 4s), plus ProviderRateLimitError.retry_after_seconds if set.

    On exhaustion of retries: re-raise the last exception.
    Log each retry attempt at WARNING level with attempt number and exception type.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return provider.complete(system_prompt, user_prompt, artifact_content)
        except (ProviderRateLimitError, ProviderTimeoutError) as exc:
            last_exc = exc

            if attempt >= max_retries:
                break

            backoff = 2**attempt  # 1s, 2s, 4s, …

            # Honor Retry-After header from rate-limit responses
            if isinstance(exc, ProviderRateLimitError) and exc.retry_after_seconds:
                backoff = max(backoff, exc.retry_after_seconds)

            jitter = random.uniform(0, min(backoff * 0.15 + 2, 15))
            sleep_time = backoff + jitter
            logger.warning(
                "Provider call failed (attempt %d/%d, %s). Retrying in %.0fs.",
                attempt + 1,
                max_retries,
                type(exc).__name__,
                sleep_time,
            )
            time.sleep(sleep_time)

    # Non-retryable exceptions propagate immediately; retryable ones reach here
    # only after exhaustion.
    assert last_exc is not None
    raise last_exc
