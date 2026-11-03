"""Out-of-sample evaluation of a local-price purchase rule.

This evaluates a deliberately limited local-price-only rule, not the live decision engine.
Each simulated purchase starts after the previous window ends. Parameter selection uses
only windows completed before the held-out period. No market data is fetched here.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite


@dataclass(frozen=True)
class Publication:
    day: date
    price: float


@dataclass(frozen=True)
class Result:
    threshold: float
    sample_size: int
    mean_cost_vs_immediate: float
    mean_regret: float
    better_than_immediate: float


@dataclass(frozen=True)
class Calibration:
    training_end: date
    evaluation_start: date
    threshold: float
    training: Result
    evaluation: Result
    baseline: Result


def _windows(publications: list[Publication], horizon_days: int) -> list[list[Publication]]:
    windows = []
    start = 0
    while start < len(publications):
        deadline = publications[start].day + timedelta(days=horizon_days)
        end = start + 1
        while end < len(publications) and publications[end].day <= deadline:
            end += 1
        # Require a later observation reaching or crossing the deadline to prove the
        # simulation window has completed; never score a truncated final window.
        if end >= len(publications):
            break
        if end - start > 1:
            windows.append(publications[start:end])
        start = end
    return windows


def _score(windows: list[list[Publication]], threshold: float) -> Result:
    cost, regret, wins = [], [], 0
    for window in windows:
        initial = window[0].price
        purchase = next((item.price for item in window[1:] if item.price <= initial * (1 - threshold)), window[-1].price)
        cost.append(purchase / initial - 1)
        regret.append(purchase / min(item.price for item in window) - 1)
        wins += purchase < initial
    count = len(cost)
    return Result(threshold, count, sum(cost) / count if count else 0.0,
                  sum(regret) / count if count else 0.0, wins / count if count else 0.0)


def evaluate(publications: list[Publication], *, candidates: tuple[float, ...] = (0.005, 0.01, 0.015, 0.02),
             horizon_days: int = 7, training_fraction: float = 0.6, minimum_windows: int = 20) -> Calibration:
    """Select threshold in training and evaluate it once on later completed windows.

    The baseline purchases immediately. Values use published local prices and exclude
    transaction costs. Missing dates are not filled; inputs must be ordered and unique.
    """
    if not candidates or any(not isfinite(v) or not 0 < v < 1 for v in candidates):
        raise ValueError("candidate thresholds must be finite and between zero and one")
    if horizon_days < 1 or not 0 < training_fraction < 1 or minimum_windows < 1:
        raise ValueError("invalid evaluation settings")
    if any(not isfinite(p.price) or p.price <= 0 for p in publications):
        raise ValueError("prices must be finite and positive")
    if any(a.day >= b.day for a, b in zip(publications, publications[1:])):
        raise ValueError("publication dates must be unique and ordered")
    windows = _windows(publications, horizon_days)
    split = int(len(windows) * training_fraction)
    train, test = windows[:split], windows[split:]
    if len(train) < minimum_windows or len(test) < minimum_windows:
        raise ValueError("not enough completed windows for a meaningful evaluation")
    scores = [_score(train, threshold) for threshold in candidates]
    selected = min(scores, key=lambda result: (result.mean_cost_vs_immediate, result.threshold))
    baseline = Result(0.0, len(test), 0.0,
        sum(w[0].price / min(p.price for p in w) - 1 for w in test) / len(test), 0.0)
    return Calibration(train[-1][-1].day, test[0][0].day, selected.threshold,
                       selected, _score(test, selected.threshold), baseline)
