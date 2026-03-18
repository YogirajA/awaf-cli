from __future__ import annotations

# Prices in USD per million tokens, as of 2026-02-01
# Update periodically. Used for budget estimation only; not billed by awaf-cli.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-5": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
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


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Return an approximate USD cost for the given token counts and model.

    Uses FALLBACK_PRICING for models not in the table.
    Input: per-million-token rates applied to actual token counts.
    """
    rates = PRICING.get(model, FALLBACK_PRICING)
    input_cost = (input_tokens / 1_000_000) * rates["input"]
    output_cost = (output_tokens / 1_000_000) * rates["output"]
    return input_cost + output_cost
