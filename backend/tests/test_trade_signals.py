import math

import numpy as np
import pandas as pd
import pytest

from gold_advisor.analytics import trade_signals as ts


def _close(n: int, seed: int = 0, start: str = "2010-01-01") -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(20 * np.exp(np.cumsum(rng.normal(0, 0.015, n))), index=pd.bdate_range(start, periods=n))


@pytest.mark.parametrize("fn,a,b", [(ts.entropy_positions, 20, 0.3), (ts.kalman_positions, 60, -1.0)])
def test_signals_never_use_the_future(fn, a, b):
    close = _close(1500)
    full = fn(close, a, b)
    for cut in (1000, 1200, 1499):
        part = fn(close.iloc[: cut + 1], a, b)
        assert part.iloc[-1] == full.iloc[cut]


def test_permutation_entropy_is_zero_for_a_steady_climb_and_bounded():
    up = pd.Series(np.arange(1.0, 60.0), index=pd.bdate_range("2020-01-01", periods=59))
    assert ts.permutation_entropy(up, 20).dropna().eq(0).all()
    noisy = ts.permutation_entropy(_close(400), 20).dropna()
    assert noisy.between(0, 1).all() and noisy.mean() > 0.8


def test_trades_happen_at_the_next_close_and_pay_the_gap():
    idx = pd.bdate_range("2020-01-01", periods=5)
    close = pd.Series([10.0, 11.0, 12.0, 13.0, 14.0], index=idx)
    pos = pd.Series([1, 1, 0, 0, 0], index=idx)  # signal at day 0, exit signal at day 2
    trades = ts.world_trades(close, pos)
    assert trades == [(idx[1], idx[3], pytest.approx(math.log(13 / 11)))]
    s = ts.score(close, pos, 0.02)
    assert s.total_pct == pytest.approx(round((13 / 11 * 0.98 - 1) * 100, 1))


def _planted(kind: str) -> pd.Series:
    rng = np.random.default_rng(4 if kind == "revert" else 5)
    n = 3000
    if kind == "revert":
        x = np.zeros(n)
        for t in range(1, n):
            x[t] = 0.9 * x[t - 1] + rng.normal(0, 0.02)
    else:
        x = np.cumsum(rng.normal(0.002, 0.01, n))
    return pd.Series(20 * np.exp(x), index=pd.bdate_range("2005-01-03", periods=n))


def test_fixed_speed_kalman_follows_a_planted_trend():
    close = _planted("trend")
    pos = ts.kalman_positions(close, 120, -1.0, 1e-3)
    assert ts.score(close.iloc[1000:], pos.iloc[1000:], 0.02).total_pct > 0


def test_recorded_finding_the_switch_misses_a_planted_mean_reverting_market():
    """Why the Kalman idea is not used: even on a market built to snap back to its mean, the regime
    switch mostly stays in trend mode and loses before costs (7 of 8 declared settings, 2026-11-16)."""
    close = _planted("revert")
    losing = sum(ts.score(close.iloc[1000:], ts.kalman_positions(close, *s).iloc[1000:], 0.0).total_pct < 0
                 for s in ts.KALMAN_FIXED_GRID)
    assert losing >= 6
