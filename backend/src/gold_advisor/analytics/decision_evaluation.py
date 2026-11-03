"""Evaluate recorded purchase decisions without reconstructing unavailable historical inputs."""
from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite

from gold_advisor.domain import Decision


@dataclass(frozen=True)
class Observation:
    day: date
    price: float
    decision: Decision


@dataclass(frozen=True)
class Evaluation:
    status: str
    windows: int
    buys: int
    mean_cost_vs_immediate: float | None
    mean_regret: float | None
    mean_baseline_regret: float | None


def evaluate(observations: list[Observation], *, horizon_days: int = 7,
             max_gap_days: int = 2, minimum_windows: int = 20) -> Evaluation:
    """Compare BUY advice with immediate purchase over non-overlapping complete windows.

    Each observation must reflect a recorded snapshot and its published local price.
    Missing decision days are never inferred. Windows with excessive gaps are excluded;
    a snapshot at or after the deadline is required to establish a complete window.
    If no BUY appears, purchase at the last observed price within the window solely for
    comparison. The baseline buys at the first observed price. Fees are not included.
    """
    if horizon_days < 1 or max_gap_days < 1 or minimum_windows < 1:
        raise ValueError("invalid evaluation settings")
    if any(not isfinite(row.price) or row.price <= 0 for row in observations):
        raise ValueError("prices must be finite and positive")
    if any(a.day >= b.day for a, b in zip(observations, observations[1:])):
        raise ValueError("observations must have unique, increasing dates")
    costs, regrets, baseline_regrets = [], [], []
    buys = 0
    i = 0
    while i < len(observations):
        deadline = observations[i].day + timedelta(days=horizon_days)
        j = i + 1
        while j < len(observations) and observations[j].day <= deadline:
            j += 1
        if j == len(observations) and observations[j - 1].day < deadline:
            break
        window = observations[i:j]
        gaps = [(b.day - a.day).days for a, b in zip(window, window[1:])]
        if len(window) >= 2 and max(gaps, default=0) <= max_gap_days and (deadline - window[-1].day).days <= max_gap_days:
            buy = next((row for row in window if row.decision is Decision.BUY), None)
            actual = buy or window[-1]
            buys += buy is not None
            initial, cheapest = window[0].price, min(row.price for row in window)
            costs.append(actual.price / initial - 1)
            regrets.append(actual.price / cheapest - 1)
            baseline_regrets.append(initial / cheapest - 1)
        i = j
    count = len(costs)
    enough = count >= minimum_windows
    return Evaluation("ok" if enough else "insufficient", count, buys,
                      sum(costs) / count if enough else None,
                      sum(regrets) / count if enough else None,
                      sum(baseline_regrets) / count if enough else None)
