"""Per-call cost estimate from token usage.

Prices are USD per million tokens (Anthropic list prices, checked 2026-10).
Override with PRICE_INPUT_PER_MTOK / PRICE_OUTPUT_PER_MTOK for other models
or negotiated rates.
"""

from __future__ import annotations

import os

from .schemas import Usage

# model id: (input, output, cache read) USD per 1M tokens
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
CACHE_WRITE_MULTIPLIER = 1.25


def price_for(model: str) -> tuple[float, float, float]:
    env_in, env_out = os.getenv("PRICE_INPUT_PER_MTOK"), os.getenv("PRICE_OUTPUT_PER_MTOK")
    if env_in and env_out:
        return float(env_in), float(env_out), float(env_in) * 0.1
    return PRICES.get(model, PRICES["claude-sonnet-5-5"])


def estimate_cost(model: str, usage: Usage) -> float:
    p_in, p_out, p_cache = price_for(model)
    cost = (
        usage.input_tokens * p_in
        + usage.output_tokens * p_out
        + usage.cache_read_input_tokens * p_cache
        + usage.cache_creation_input_tokens * p_in * CACHE_WRITE_MULTIPLIER
    ) / 1_000_000
    return round(cost, 6)
