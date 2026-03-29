from __future__ import annotations

import re


def normalize_model(model: str) -> str:
    """Strip trailing Anthropic date suffix (e.g. -20251001) for table lookups.

    Anthropic model IDs include a date component that isn't part of the pricing key
    (e.g. ``claude-haiku-4-5-20251001`` → ``claude-haiku-4-5``).  Stripping it lets
    ``PRICING`` and ``CONTEXT_WINDOW`` use the stable family name without needing an
    entry for every date-stamped release.
    """
    return re.sub(r"-\d{8}$", "", model)


# Prices in USD per million tokens, as of 2026-02-01
# Update periodically. Used for budget estimation only; not billed by awaf-cli.
PRICING: dict[str, dict[str, float]] = {
    # Anthropic — includes cache rates (cache_creation = 1.25x input, cache_read = 0.10x input)
    "claude-opus-4-6": {
        "input": 15.00,
        "cache_creation_input": 18.75,
        "cache_read_input": 1.50,
        "output": 75.00,
    },
    "claude-sonnet-4-6": {
        "input": 3.00,
        "cache_creation_input": 3.75,
        "cache_read_input": 0.30,
        "output": 15.00,
    },
    "claude-haiku-4-6": {
        "input": 0.80,
        "cache_creation_input": 1.00,
        "cache_read_input": 0.08,
        "output": 4.00,
    },
    "claude-opus-4-5": {
        "input": 15.00,
        "cache_creation_input": 18.75,
        "cache_read_input": 1.50,
        "output": 75.00,
    },
    "claude-sonnet-4-5": {
        "input": 3.00,
        "cache_creation_input": 3.75,
        "cache_read_input": 0.30,
        "output": 15.00,
    },
    "claude-haiku-4-5": {
        "input": 0.80,
        "cache_creation_input": 1.00,
        "cache_read_input": 0.08,
        "output": 4.00,
    },
    # OpenAI / Google — no prompt caching supported; cache fields unused
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "o3": {"input": 10.00, "output": 40.00},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
}

# Conservative fallback for unknown models
FALLBACK_PRICING: dict[str, float] = {"input": 5.00, "output": 20.00}

# Context window sizes in tokens (input limit per call)
CONTEXT_WINDOW: dict[str, int] = {
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4-6": 200_000,
    "claude-opus-4-5": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-haiku-4-5": 200_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "o3": 200_000,
    "gemini-2.0-flash": 1_048_576,
    "gemini-1.5-pro": 1_048_576,
}
FALLBACK_CONTEXT_WINDOW: int = 128_000


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    """
    Return an approximate USD cost for the given token counts and model.

    Uses FALLBACK_PRICING for models not in the table.
    For Anthropic models, cache_creation and cache_read tokens are priced separately
    (1.25x and 0.10x the base input rate respectively). Non-Anthropic providers always
    pass 0 for cache tokens so this degrades to a simple input/output calculation.
    """
    rates = PRICING.get(model) or PRICING.get(normalize_model(model)) or FALLBACK_PRICING
    regular_input = input_tokens - cache_creation_input_tokens - cache_read_input_tokens
    input_cost = (regular_input / 1_000_000) * rates["input"]
    cache_create_cost = (cache_creation_input_tokens / 1_000_000) * rates.get(
        "cache_creation_input", rates["input"] * 1.25
    )
    cache_read_cost = (cache_read_input_tokens / 1_000_000) * rates.get(
        "cache_read_input", rates["input"] * 0.10
    )
    output_cost = (output_tokens / 1_000_000) * rates["output"]
    return input_cost + cache_create_cost + cache_read_cost + output_cost
