"""Empirical scenarios for 24 hours, 3 days, and 7 days from historical analogues.

For each horizon: find the past daily closes most similar to today (trend, momentum,
RSI, recent move, volatility; standardised over the past only), keep up to 100 with
non-overlapping outcome windows, and count what happened next. Probabilities are those
observed frequencies, with a 95% interval; they are not calibrated certainties.
"""

import math

import numpy as np
import pandas as pd

VERSION = "forecast-1"
HORIZONS = ((24, "24 hours"), (72, "3 days"), (168, "7 days"))
MAX_NEIGHBOURS = 100
MIN_OBSERVATIONS = 30
NEUTRAL_ATR = 0.5
MIN_BAND_COUNT = 5
SCENARIOS = ("bearish", "neutral", "bullish")


def features(ind: pd.DataFrame) -> pd.DataFrame:
    atr = ind["atr_14"].replace(0, np.nan)
    return pd.DataFrame(
        {
            "trend": (ind["ema_21"] - ind["ema_50"]) / atr,
            "macd": ind["macd_hist"] / atr,
            "rsi": ind["rsi_14"],
            "move_5": (ind["close"] - ind["close"].shift(5)) / atr,
            "volatility": ind["realized_vol"],
        },
        index=ind.index,
    )


def _insufficient(hours: int, label: str, reason: str) -> dict:
    return {"horizon_hours": hours, "label": label, "status": "insufficient", "reason": reason}


def _one(ind, feats, closes, atr, close_times, hours, label, base_price, rupee_factor, label_name) -> dict:
    horizon = pd.Timedelta(hours=hours)
    out_idx = np.searchsorted(close_times.values, (close_times + horizon).values, side="left")
    known = (out_idx < len(closes)) & np.asarray((close_times + horizon) <= close_times[-1])
    valid = known & feats.notna().all(axis=1).to_numpy()
    valid[-1] = False
    candidates = np.where(valid)[0]
    current = feats.iloc[-1]
    if current.isna().any():
        return _insufficient(hours, label, "Today's indicators are still warming up.")
    if len(candidates) < MIN_OBSERVATIONS:
        return _insufficient(hours, label, f"Only {len(candidates)} past days to compare; {MIN_OBSERVATIONS} needed.")

    x = feats.iloc[candidates].to_numpy(float)
    mu, sd = x.mean(axis=0), x.std(axis=0)
    sd[sd == 0] = 1
    dist = np.sqrt((((x - mu) / sd - (current.to_numpy(float) - mu) / sd) ** 2).sum(axis=1))

    chosen, windows = [], []
    for k in np.argsort(dist):
        i, j = int(candidates[k]), int(out_idx[candidates[k]])
        if any(i <= b and j >= a for a, b in windows):
            continue
        chosen.append(i)
        windows.append((i, j))
        if len(chosen) >= MAX_NEIGHBOURS:
            break
    n = len(chosen)
    if n < MIN_OBSERVATIONS:
        return _insufficient(hours, label, f"Only {n} non-overlapping similar days; {MIN_OBSERVATIONS} needed.")

    ch = np.array(chosen)
    ret = closes[out_idx[ch]] / closes[ch] - 1
    days = hours / 24
    thr = NEUTRAL_ATR * atr[ch] / closes[ch] * math.sqrt(days)
    cls = np.where(ret < -thr, "bearish", np.where(ret > thr, "bullish", "neutral"))
    neutral_now = NEUTRAL_ATR * atr[-1] / closes[-1] * math.sqrt(days)

    def price(r):
        return round(base_price * (1 + float(r)), 2)

    def rupees(r):
        return round(base_price * (1 + float(r)) * rupee_factor) if rupee_factor else None

    scenarios = []
    for name in SCENARIOS:
        mask = cls == name
        p = float(mask.mean())
        se = math.sqrt(p * (1 - p) / n)
        r = ret[mask]
        band = (np.percentile(r, 10), np.percentile(r, 90)) if len(r) >= MIN_BAND_COUNT else None
        scenarios.append(
            {
                "name": name,
                "probability": round(p, 3),
                "probability_low": round(max(0.0, p - 1.96 * se), 3),
                "probability_high": round(min(1.0, p + 1.96 * se), 3),
                "count": int(mask.sum()),
                "median_return": round(float(np.median(r)), 4) if len(r) else None,
                "band_return": [round(float(band[0]), 4), round(float(band[1]), 4)] if band else None,
                "band_usd": [price(band[0]), price(band[1])] if band else None,
                "band_npr_per_tola": [rupees(band[0]), rupees(band[1])] if band and rupee_factor else None,
                "condition": {
                    "bearish": f"{label_name} ends more than {neutral_now * 100:.1f}% lower",
                    "neutral": f"{label_name} ends within ±{neutral_now * 100:.1f}%",
                    "bullish": f"{label_name} ends more than {neutral_now * 100:.1f}% higher",
                }[name],
            }
        )
    best = max(scenarios, key=lambda s: s["probability"])
    clear = best["probability"] >= 0.45 and best["probability_low"] > 1 / 3
    p10, p50, p90 = np.percentile(ret, [10, 50, 90])
    return {
        "horizon_hours": hours,
        "label": label,
        "status": "ok",
        "sample_size": n,
        "first_analogue": ind.index[ch.min()],
        "most_likely": best["name"] if clear else None,
        "most_likely_probability": best["probability"],
        "scenarios": scenarios,
        "base_price_usd": base_price,
        "range_usd": [price(p10), price(p90)],
        "median_usd": price(p50),
        "range_npr_per_tola": [rupees(p10), rupees(p90)] if rupee_factor else None,
        "median_npr_per_tola": rupees(p50) if rupee_factor else None,
        "invalidation": {
            "bearish": price(neutral_now),
            "bullish": price(-neutral_now),
        },
        "limitations": "Based on similar past days only. Ignores news, scheduled US announcements, and Nepal's price lag.",
    }


def forecast(ind_d1: pd.DataFrame, base_price: float | None, rupee_factor: float | None, label_name: str = "Gold") -> list[dict]:
    if ind_d1.empty:
        return [_insufficient(h, label, "No daily price history.") for h, label in HORIZONS]
    feats = features(ind_d1)
    closes = ind_d1["close"].to_numpy(float)
    atr = ind_d1["atr_14"].to_numpy(float)
    close_times = pd.DatetimeIndex(ind_d1.index) + pd.Timedelta(days=1)
    base = base_price if base_price is not None else float(closes[-1])
    return [_one(ind_d1, feats, closes, atr, close_times, h, label, base, rupee_factor, label_name) for h, label in HORIZONS]
