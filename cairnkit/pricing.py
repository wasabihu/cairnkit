"""Cost estimates for providers that do not report a price with the usage."""

from __future__ import annotations

from dataclasses import dataclass

from cairnkit.types import Usage


@dataclass(frozen=True)
class Price:
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float | None = None


def estimate_cost(usage: Usage, price: Price) -> float:
    cached = usage.cached_tokens
    fresh = max(usage.prompt_tokens - cached, 0)
    cached_rate = (
        price.cached_input_per_million
        if price.cached_input_per_million is not None
        else price.input_per_million
    )
    return (
        fresh * price.input_per_million
        + cached * cached_rate
        + usage.completion_tokens * price.output_per_million
    ) / 1_000_000


def cost_of(usage: Usage, prices: dict[str, Price], model: str) -> float | None:
    """The provider-reported cost when present, else an estimate, else None."""
    if usage.cost is not None:
        return usage.cost
    price = prices.get(model)
    return estimate_cost(usage, price) if price else None
