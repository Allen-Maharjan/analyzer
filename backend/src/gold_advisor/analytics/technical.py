"""Readable indicator signals and classic price levels for the detail screen.

Each signal has a direction (+1 rising, -1 falling, 0 neutral), a value, and a
plain-language reading. Levels are Fibonacci retracements of the recent range and
classic floor-trader pivots from the last completed bar.
"""

import math

import pandas as pd

VERSION = "technical-1"
FIB_LOOKBACK_BARS = 126  # about six months of daily bars
FIB_RATIOS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)


def _f(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _signal(key, name, value, direction, reading, explain) -> dict:
    return {"key": key, "name": name, "value": value, "signal": direction, "reading": reading, "explain": explain}


def signals(ind: pd.DataFrame, rupees_per_usd_oz: float | None = None) -> dict:
    if len(ind) < 2:
        return {"signals": [], "tally": {"up": 0, "down": 0, "neutral": 0}}
    last, prev = ind.iloc[-1], ind.iloc[-2]
    close = float(last["close"])
    out: list[dict] = []

    sma50, sma200 = _f(last["sma_50"]), _f(last["sma_200"])
    if sma50 and sma200:
        a50, a200 = close > sma50, close > sma200
        cross = "above" if sma50 > sma200 else "below"
        out.append(_signal(
            "moving_averages", "Moving averages", f"50d ${sma50:,.0f} · 200d ${sma200:,.0f}",
            1 if a50 and a200 else -1 if not a50 and not a200 else 0,
            f"Price is {'above' if a50 else 'below'} its 50-day average and {'above' if a200 else 'below'} its 200-day "
            f"average. The 50-day sits {cross} the 200-day ({'golden' if cross == 'above' else 'death'} cross).",
            "Averages of past closing prices. Price above them usually means an uptrend.",
        ))

    rsi = _f(last["rsi_14"])
    if rsi is not None:
        zone = "very weak, often near a bounce" if rsi < 30 else "very strong, often near a pullback" if rsi > 70 else "in the normal range"
        out.append(_signal("rsi", "RSI (14)", f"{rsi:.0f}", 1 if rsi > 55 else -1 if rsi < 45 else 0,
                           f"Recent buying vs selling pressure is {zone}.",
                           "0–100 scale of recent gains vs losses. Below 30 oversold, above 70 overbought."))

    hist, hist_prev = _f(last["macd_hist"]), _f(prev["macd_hist"])
    if hist is not None and hist_prev is not None:
        side = "above" if hist > 0 else "below"
        trend = "strengthening" if abs(hist) > abs(hist_prev) else "fading"
        out.append(_signal("macd", "MACD (12, 26, 9)", f"{hist:+.2f}", 1 if hist > 0 else -1,
                           f"MACD is {side} its signal line and the move is {trend}.",
                           "Compares a fast and a slow average to show momentum turning."))

    upper, mid, lower = _f(last["bb_upper"]), _f(last["bb_middle"]), _f(last["bb_lower"])
    if upper and lower and upper > lower:
        pb = (close - lower) / (upper - lower)
        where = "below the lower band (unusually low)" if pb < 0 else "above the upper band (unusually high)" if pb > 1 else f"{pb * 100:.0f}% of the way up the band"
        out.append(_signal("bollinger", "Bollinger Bands (20, 2)", f"%B {pb:.2f}", 1 if close > (mid or close) else -1,
                           f"Price is {where}.",
                           "A band two standard deviations around the 20-day average. Most closes stay inside it."))

    k, d = _f(last["stoch_k"]), _f(last["stoch_d"])
    if k is not None and d is not None:
        zone = " in oversold territory" if k < 20 else " in overbought territory" if k > 80 else ""
        out.append(_signal("stochastic", "Stochastic (14, 3, 3)", f"%K {k:.0f} · %D {d:.0f}", 1 if k > d else -1,
                           f"The fast line is {'above' if k > d else 'below'} the slow line{zone}.",
                           "Where today's close sits in the recent high–low range. Below 20 oversold, above 80 overbought."))

    adx, pdi, mdi = _f(last["adx_14"]), _f(last["plus_di"]), _f(last["minus_di"])
    if adx is not None and pdi is not None and mdi is not None:
        strength = "strong" if adx >= 25 else "weak" if adx < 20 else "moderate"
        direction = (1 if pdi > mdi else -1) if adx >= 20 else 0
        out.append(_signal("adx", "ADX (14)", f"{adx:.0f}", direction,
                           f"The trend is {strength}, with {'buyers' if pdi > mdi else 'sellers'} in control.",
                           "Trend strength from 0 to 100. Above 25 is a strong trend, below 20 no real trend."))

    atr = _f(last["atr_14"])
    if atr:
        rs = f" (about Rs {atr * rupees_per_usd_oz:,.0f} per tola in Nepal)" if rupees_per_usd_oz else ""
        out.append(_signal("atr", "ATR (14)", f"${atr:,.0f} · {atr / close * 100:.1f}%", 0,
                           f"Gold typically moves about ${atr:,.0f} in one bar{rs}.",
                           "Average true range: the usual size of one bar's move."))

    vol = _f(last["realized_vol"])
    if vol is not None:
        level = "high" if vol > 0.25 else "low" if vol < 0.12 else "normal"
        out.append(_signal("volatility", "Volatility (20, yearly)", f"{vol * 100:.0f}%", 0,
                           f"Price swings are {level} compared with this instrument's history.",
                           "How much prices have been jumping around, scaled to a year."))

    tally = {"up": sum(s["signal"] > 0 for s in out), "down": sum(s["signal"] < 0 for s in out),
             "neutral": sum(s["signal"] == 0 for s in out)}
    return {"signals": out, "tally": tally}


def fibonacci(ind: pd.DataFrame) -> dict | None:
    recent = ind.tail(FIB_LOOKBACK_BARS)
    if len(recent) < 20:
        return None
    high, low = float(recent["high"].max()), float(recent["low"].min())
    high_at, low_at = recent["high"].idxmax(), recent["low"].idxmin()
    falling = high_at < low_at  # high came first, so the move is down and retracements are bounces
    levels = [{"ratio": r, "price": round(high - r * (high - low), 2)} for r in FIB_RATIOS]
    return {"high": high, "low": low, "high_at": high_at, "low_at": low_at,
            "direction": "down" if falling else "up", "levels": levels}


def pivots(ind: pd.DataFrame) -> dict | None:
    # Skip the short Sunday-evening session bar; pivots need a full trading day.
    full_days = ind[pd.DatetimeIndex(ind.index).weekday != 6]
    if full_days.empty:
        return None
    last = full_days.iloc[-1]
    h, l, c = float(last["high"]), float(last["low"]), float(last["close"])
    p = (h + l + c) / 3
    vals = {"R3": h + 2 * (p - l), "R2": p + (h - l), "R1": 2 * p - l, "P": p,
            "S1": 2 * p - h, "S2": p - (h - l), "S3": l - 2 * (h - p)}
    return {"based_on": full_days.index[-1], "levels": {k: round(v, 2) for k, v in vals.items() if math.isfinite(v)}}
