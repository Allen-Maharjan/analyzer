"""Two candidate silver trade signals, tested before anything reaches the Trade screen (research only).

Ideas brought by the owner (2026-11-16), long-only because the owner can only buy and sell back:

A. Entropy: permutation entropy (order 3) of daily closes measures how ordered the path is, not just how
   big the moves are. Buy when entropy is low for this market (rolling percentile of its own past) AND the
   close is at least 1 standard deviation below its 20-day mean; sell when entropy spikes (top 20%).
B. Kalman + regime switch: a local-level Kalman filter on log price gives the "true mean" (noise ratio
   refit each January on the previous three years only). Regime test, over the last W days: if daily
   returns are explained by the gap to the Kalman mean (AIC at least 2 lower than "returns are a constant
   drift"), the market is mean-reverting: buy at z <= z_entry, sell at z >= 0. Otherwise it is trending:
   hold while the close is above the mean and the mean is rising, sell on a close below the mean.

Timing: a signal uses completed daily bars only. On world history it trades at the NEXT day's close; in
the Nepal confirmation it trades at that day's Nepal price, like the existing replay.

Settings tried (declared before the first run, all reported): A: window 20 or 40 days x low-entropy cut
at the 20th or 30th percentile. B: regime window 60 or 120 days x z_entry -1.0 or -1.5.

Pass rule, fixed before the first run (2026-11-16), with the buy-back gap at 2%:
1. Development (world silver, 2006-01-01 to 2024-11-04; settings chosen here): the best setting must
   make money overall AND beat buy-and-hold scaled to its share of days in the market, overall and in at
   least 3 of the 4 eras, one of which must be the 2012-2015 fall.
2. Confirmation (Nepal silver prices, 2024-11-05 on, run once with that setting): must make money, beat
   the current trade rule (trade-1) and beat scaled buy-and-hold.
Anything else: "did not pass".

Attempt 1 results (trade-signals-1, frozen): neither passed development. Entropy was a near miss: its
best setting made +127.6% overall at a 2% gap (scaled buy-and-hold +46.2%, +4.08% per trade before the
gap, 40 trades), and every setting made money in 2020-2024, but it beat scaled holding only in 2006-2011
and lost in the 2012-2015 fall and 2016-2019, so it failed the era test. Correlation with plain
volatility is 0.07, so it is a different measure. At 4% the best setting was -0.2%. Kalman lost almost everything at a 2% gap: about 20
trades a year averaging +0.11% before the gap. Cause, found on planted data: fitting the noise ratio by
likelihood always picks the fastest setting (0.1, a steady gain of about 0.27, roughly a 6-day average),
because a near-random-walk price is best predicted by itself. The fitted "true mean" is the price, so
there is no gap to trade. That is a finding about the idea, not only a bug.

Attempt 2 (trade-signals-2, declared before its run): the Kalman mean's speed is a declared setting,
not fitted: ratio 0.01 (gain about 0.095, roughly a 20-day average) or 0.001 (gain about 0.031, roughly
a 63-day average), crossed with the same regime windows and z levels: 8 settings, all reported. A
fixed-speed Kalman level filter is a moving average; the only new part is the regime switch. Same pass
rule. Entropy is not retried. There is no attempt 3.

Attempt 2 results: did not pass. On planted data the switch caught a steady trend but lost money before
costs on a market built to snap back to its mean (7 of 8 settings): it stayed in trend mode most days.
On world silver 2006-2024 all 8 settings made 147-233 trades averaging -0.32% to +0.33% before the
gap, and lost 96-99% at a 2% gap; none beat scaled buy-and-hold in any era.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

VERSION = "trade-signals-2"
GAPS = (0.0, 0.02, 0.04)
HEADLINE_GAP = 0.02
DEV_START, DEV_END = "2006-01-01", "2024-11-04"
ERAS = (("2006-2011", "2006", "2011"), ("2012-2015 fall", "2012", "2015"),
        ("2016-2019", "2016", "2019"), ("2020-2024", "2020", "2024-11-04"))
ENTROPY_GRID = tuple((w, q) for w in (20, 40) for q in (0.2, 0.3))
KALMAN_GRID = tuple((w, z) for w in (60, 120) for z in (-1.0, -1.5))  # attempt 1: fitted speed
KALMAN_FIXED_GRID = tuple((w, z, r) for r in (1e-2, 1e-3) for w in (60, 120) for z in (-1.0, -1.5))  # attempt 2
RANK_LOOKBACK = 250
KALMAN_RATIOS = (1e-4, 1e-3, 1e-2, 1e-1)
KALMAN_FIT_YEARS = 3


# ---------------------------------------------------------------- A: permutation entropy


def permutation_entropy(close: pd.Series, window: int) -> pd.Series:
    """Normalised (0-1) permutation entropy of order 3 over the last ``window`` days, known at each close."""
    c = close.to_numpy(float)
    pat = np.full(len(c), -1)
    for i in range(2, len(c)):
        pat[i] = hash(tuple(np.argsort(c[i - 2 : i + 1], kind="stable"))) % 1_000_003
    codes = {v: k for k, v in enumerate(sorted(set(pat[pat >= 0])))}
    onehot = np.zeros((len(c), max(len(codes), 1)))
    for i, p in enumerate(pat):
        if p >= 0:
            onehot[i, codes[p]] = 1
    counts = pd.DataFrame(onehot, index=close.index).rolling(window, min_periods=window).sum()
    probs = counts.div(counts.sum(axis=1), axis=0)
    ent = -(probs * np.log(probs.where(probs > 0))).sum(axis=1, min_count=1)
    ent[counts.sum(axis=1) < window] = np.nan
    return ent / math.log(6)


def _past_rank(s: pd.Series, lookback: int = RANK_LOOKBACK) -> pd.Series:
    """Share of the previous ``lookback`` values below today's value (today's own value excluded)."""
    v = s.to_numpy(float)
    out = np.full(len(v), np.nan)
    for i in range(lookback, len(v)):
        past = v[i - lookback : i]
        past = past[~np.isnan(past)]
        if len(past) >= lookback // 2 and not np.isnan(v[i]):
            out[i] = float((past < v[i]).mean())
    return pd.Series(out, index=s.index)


def entropy_positions(close: pd.Series, window: int, low_q: float, high_q: float = 0.8) -> pd.Series:
    """1 = hold, 0 = flat, decided at each day's close."""
    rank = _past_rank(permutation_entropy(close, window))
    mean, sd = close.rolling(20).mean(), close.rolling(20).std()
    z = (close - mean) / sd
    pos, held = np.zeros(len(close)), 0
    for i, (r, zz) in enumerate(zip(rank.to_numpy(), z.to_numpy())):
        if np.isnan(r) or np.isnan(zz):
            pos[i] = held
            continue
        if not held and r <= low_q and zz <= -1.0:
            held = 1
        elif held and r >= high_q:
            held = 0
        pos[i] = held
    return pd.Series(pos, index=close.index)


# ---------------------------------------------------------------- B: Kalman + regime


def kalman_level(y: np.ndarray, ratio: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Local-level filter with observation variance 1 and state variance ``ratio`` (scale cancels).
    Returns filtered means, one-step innovations and their variances."""
    n = len(y)
    x, p = y[0], 1.0
    mean, innov, fvar = np.empty(n), np.full(n, np.nan), np.full(n, np.nan)
    mean[0] = x
    for t in range(1, n):
        p = p + ratio
        f = p + 1.0
        v = y[t] - x
        k = p / f
        x, p = x + k * v, (1 - k) * p
        mean[t], innov[t], fvar[t] = x, v, f
    return mean, innov, fvar


def _concentrated_loglik(innov: np.ndarray, fvar: np.ndarray) -> float:
    v, f = innov[~np.isnan(innov)], fvar[~np.isnan(fvar)]
    if len(v) < 10:
        return -np.inf
    sigma2 = float(np.mean(v * v / f))
    return -0.5 * float(np.sum(np.log(f))) - 0.5 * len(v) * math.log(max(sigma2, 1e-18))


def kalman_mean(close: pd.Series) -> pd.Series:
    """Kalman mean of log price; the noise ratio for each calendar year is fitted on the 3 years before it.
    The filter runs causally from the start, switching ratio at each January."""
    y = np.log(close.to_numpy(float))
    years = close.index.year
    out = np.full(len(y), np.nan)
    x, p = y[0], 1.0
    ratio_by_year: dict[int, float] = {}
    for yr in sorted(set(years)):
        past = (years >= yr - KALMAN_FIT_YEARS) & (years < yr)
        if past.sum() >= 250:
            ys = y[past]
            ratio_by_year[yr] = max(KALMAN_RATIOS, key=lambda r: _concentrated_loglik(*kalman_level(ys, r)[1:]))
    for t in range(len(y)):
        ratio = ratio_by_year.get(years[t])
        if ratio is None:
            continue
        if np.isnan(out[t - 1]) if t else True:
            x, p = y[t], 1.0
        else:
            p = p + ratio
            k = p / (p + 1.0)
            x, p = x + k * (y[t] - x), (1 - k) * p
        out[t] = x
    return pd.Series(out, index=close.index)


def _aic(rss: float, n: int, k: int) -> float:
    return n * math.log(max(rss, 1e-18) / n) + 2 * k


def kalman_positions(close: pd.Series, window: int, z_entry: float, ratio: float | None = None) -> pd.Series:
    """``ratio`` None: speed fitted each year (attempt 1). A number: fixed speed (attempt 2)."""
    y = np.log(close.to_numpy(float))
    m = kalman_mean(close).to_numpy() if ratio is None else kalman_level(y, ratio)[0]
    gap = y - m
    ret = np.r_[np.nan, np.diff(y)]
    pos, held, mode = np.zeros(len(y)), 0, None
    for t in range(len(y)):
        if t < window + 5 or np.isnan(m[t - window]):
            pos[t] = held
            continue
        r = ret[t - window + 1 : t + 1]
        g = gap[t - window : t]
        sd = float(np.nanstd(gap[t - window + 1 : t + 1])) or 1e-9
        z = gap[t] / sd
        rss_drift = float(np.sum((r - r.mean()) ** 2))
        X = np.c_[np.ones(window), g]
        beta, *_ = np.linalg.lstsq(X, r, rcond=None)
        rss_mr = float(np.sum((r - X @ beta) ** 2))
        reverting = beta[1] < 0 and _aic(rss_mr, window, 2) <= _aic(rss_drift, window, 1) - 2
        new_mode = "revert" if reverting else "trend"
        if held and mode is not None and new_mode != mode:
            held = 0  # regime changed while holding: close out
        mode = new_mode
        rising = m[t] > m[t - 5]
        if mode == "revert":
            if not held and z <= z_entry:
                held = 1
            elif held and z >= 0:
                held = 0
        else:
            if not held and gap[t] > 0 and rising:
                held = 1
            elif held and gap[t] < 0:
                held = 0
        pos[t] = held
    return pd.Series(pos, index=close.index)


# ---------------------------------------------------------------- scoring on world history


@dataclass
class Score:
    trades: int
    years: float
    in_market_share: float
    avg_gain_before_gap_pct: float | None
    total_pct: float  # compounded result of all trades after the gap, % of money in
    scaled_buy_hold_pct: float  # buy-and-hold over the period, scaled to the share of days in the market


def world_trades(close: pd.Series, pos: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp, float]]:
    """Signal at close t, trade at close t+1. Returns (entry day, exit day, log return before the gap)."""
    exec_pos = pos.shift(1).fillna(0).to_numpy()
    c, idx = close.to_numpy(float), close.index
    trades, entry = [], None
    for i in range(len(c)):
        if exec_pos[i] and entry is None:
            entry = i
        elif not exec_pos[i] and entry is not None:
            trades.append((idx[entry], idx[i], math.log(c[i] / c[entry])))
            entry = None
    if entry is not None:  # still open at the end: valued at the last close, gap applied
        trades.append((idx[entry], idx[-1], math.log(c[-1] / c[entry])))
    return trades


def score(close: pd.Series, pos: pd.Series, gap: float) -> Score:
    trades = world_trades(close, pos)
    days = len(close)
    held = float(pos.shift(1).fillna(0).mean()) if days else 0.0
    total = sum(r + math.log(1 - gap) for _, _, r in trades)
    bh = math.log(float(close.iloc[-1]) / float(close.iloc[0])) if days > 1 else 0.0
    years = (close.index[-1] - close.index[0]).days / 365.25 if days > 1 else 0.0
    return Score(
        trades=len(trades), years=round(years, 1), in_market_share=round(held, 3),
        avg_gain_before_gap_pct=round(float(np.mean([r for *_, r in trades])) * 100, 2) if trades else None,
        total_pct=round((math.exp(total) - 1) * 100, 1),
        scaled_buy_hold_pct=round((math.exp(bh * held) - 1) * 100, 1),
    )


def _beats(s: Score) -> bool:
    return s.total_pct > 0 and s.total_pct > s.scaled_buy_hold_pct


def development(close: pd.Series) -> dict:
    """All declared settings on world history up to DEV_END; positions use history from 2000 for warm-up."""
    close = close.loc[:DEV_END]
    out = {}
    for name, grid, fn in (("entropy", ENTROPY_GRID, entropy_positions), ("kalman_fitted", KALMAN_GRID, kalman_positions),
                           ("kalman_fixed", KALMAN_FIXED_GRID, kalman_positions)):
        rows = []
        for setting in grid:
            pos = fn(close, *setting)
            seg = lambda lo, hi: (close.loc[lo:hi], pos.loc[lo:hi])  # noqa: E731
            c, p = seg(DEV_START, DEV_END)
            overall = {f"gap_{int(g * 100)}pct": score(c, p, g).__dict__ for g in GAPS}
            eras = {e: score(*seg(lo, hi), HEADLINE_GAP).__dict__ for e, lo, hi in ERAS}
            head = score(c, p, HEADLINE_GAP)
            era_wins = [e for e, lo, hi in ERAS if _beats(score(*seg(lo, hi), HEADLINE_GAP))]
            passed = _beats(head) and len(era_wins) >= 3 and "2012-2015 fall" in era_wins
            rows.append({"setting": list(setting), "overall": overall, "eras": eras, "eras_beaten": era_wins,
                         "passes_development": passed})
        best = max(rows, key=lambda r: r["overall"][f"gap_{int(HEADLINE_GAP * 100)}pct"]["total_pct"])
        out[name] = {"settings": rows, "chosen": best["setting"], "chosen_passes": best["passes_development"]}
    return out


def entropy_vs_volatility(close: pd.Series, window: int = 20) -> float:
    """Correlation of the entropy with plain volatility; near +-1 would mean it is volatility renamed."""
    ent = permutation_entropy(close, window)
    vol = np.log(close).diff().rolling(window).std()
    both = pd.concat([ent, vol], axis=1).dropna()
    return round(float(both.corr().iloc[0, 1]), 3)


def report(close: pd.Series) -> dict:
    dev = development(close)
    passed = [k for k, v in dev.items() if v["chosen_passes"]]
    return {"version": VERSION, "headline_gap_pct": HEADLINE_GAP * 100,
            "entropy_vs_volatility_corr": entropy_vs_volatility(close.loc[:DEV_END]),
            "development": dev, "passed_development": passed,
            "nepal_confirmation": "run only for a signal that passes development" if not passed else "pending"}
