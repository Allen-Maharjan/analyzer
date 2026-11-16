"""Quarter- and year-ahead world price forecasts, tested walk-forward (research only, never the decision).

Idea borrowed from Trading Economics' quarter-end and 12-month forecasts ("macro models"): predict the
world price ``h`` trading days ahead from the trend and from US real interest rates and the dollar.
Every model is judged on forecasts it made before seeing the answer, against two simple baselines:
"the price stays where it is" and "the price keeps rising at its long-run average rate".

Data: 2000-2026 daily closes fetched from Dukascopy and FRED rates/dollar fetched from FRED, held in
memory only. Nothing is written to the database. That history includes falling stretches (2012-2015),
so a model that only learned "gold goes up" cannot pass.

No-leak rules:
- FRED values are lagged one business day (published the day after their date);
- a forecast made on day t is trained only on windows that ended on or before day t;
- test forecasts start every ``h`` days, so the scored windows never overlap.

Pass rule, fixed before the first run (2026-11-16) and not to be loosened after seeing results:
a model is "useful" only if, over the non-overlapping test windows, its average error is at least 5%
smaller than BOTH baselines AND it beat "stays where it is" on more windows than chance would give
(one-sided sign test, p < 0.05). Anything else is "no better than the baselines".
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass

import numpy as np
import pandas as pd

VERSION = "macro-forecast-1"
HORIZONS = ((63, "about 3 months"), (252, "about 12 months"))
MIN_TRAIN_YEARS = 6
RANGE_COVERAGE = 0.80
ERAS = (("2006-2011 rising", "2006", "2011"), ("2012-2015 falling", "2012", "2015"),
        ("2016-2019 flat", "2016", "2019"), ("2020-2026 rising", "2020", "2026"))
FRED_IDS = ("DFII10", "DGS10", "DTWEXBGS", "DTWEXM")
MODELS = ("no_change", "average_drift", "trend", "macro")


# ---------------------------------------------------------------- data (network, read-only)


def fetch_history(symbol: str, start: str = "2000-01-01") -> pd.Series:
    """Daily closes (weekdays) from the Dukascopy script. Bars with inconsistent high/low keep their close."""
    from gold_advisor.config import get_settings

    settings = get_settings()
    args = json.dumps({"instrument": symbol, "timeframe": "d1", "from": f"{start}T00:00:00+00:00",
                       "to": pd.Timestamp.now(tz="UTC").normalize().isoformat()})
    done = subprocess.run([settings.node_binary, str(settings.dukascopy_script), args], capture_output=True,
                          text=True, timeout=settings.dukascopy_timeout_seconds, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"dukascopy {symbol}: exit {done.returncode}: {done.stderr.strip()[:300]}")
    rows = pd.DataFrame(json.loads(done.stdout))
    return closes_from_rows(rows)


def closes_from_rows(rows: pd.DataFrame) -> pd.Series:
    idx = pd.to_datetime(rows["timestamp"], unit="ms", utc=True).dt.tz_convert(None).dt.normalize()
    s = pd.Series(rows["close"].astype(float).to_numpy(), index=pd.DatetimeIndex(idx))
    s = s[(s.index.dayofweek < 5) & (s > 0)]
    return s[~s.index.duplicated(keep="last")].sort_index()


def fetch_fred(start: str = "1999-01-01") -> dict[str, pd.Series]:
    import httpx

    from gold_advisor.collectors import fred

    out = {}
    with httpx.Client(timeout=60) as client:
        for sid in FRED_IDS:
            obs = fred.fetch(client, sid, pd.Timestamp(start).date())
            out[sid] = pd.Series({pd.Timestamp(o.obs_date): (float(o.value) if o.value is not None else np.nan)
                                  for o in obs}, dtype=float)
    return out


# ---------------------------------------------------------------- features


def _lagged(series: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    s = series.dropna().sort_index().copy()
    s.index = pd.DatetimeIndex(s.index).normalize() + pd.offsets.BDay(1)
    return s.reindex(index.union(s.index)).ffill().reindex(index)


def dollar_log(macro: dict[str, pd.Series], index: pd.DatetimeIndex) -> pd.Series:
    """Log of the trade-weighted dollar: the broad index from 2006, the older major-currency index before.

    The two indexes have different levels, so the older one is rescaled to meet the newer one on the first
    days they overlap, which leaves no jump at the join (only changes are used as features).
    """
    new, old = macro.get("DTWEXBGS"), macro.get("DTWEXM")
    if new is None or new.dropna().empty:
        return np.log(_lagged(old, index)) if old is not None else pd.Series(np.nan, index=index)
    new_l = np.log(_lagged(new, index))
    if old is None or old.dropna().empty:
        return new_l
    old_l = np.log(_lagged(old, index))
    both = new_l.notna() & old_l.notna()
    shift = float((new_l[both] - old_l[both]).iloc[:5].median()) if both.any() else 0.0
    return new_l.combine_first(old_l + shift)


def build_features(close: pd.Series, macro: dict[str, pd.Series], h: int) -> pd.DataFrame:
    logc = np.log(close)
    real = _lagged(macro["DFII10"], close.index) if "DFII10" in macro else pd.Series(np.nan, index=close.index)
    return pd.DataFrame({
        "past_return": logc.diff(h),
        "real_yield": real,
        "real_yield_change": real.diff(h),
        "dollar_change": dollar_log(macro, close.index).diff(h),
    }, index=close.index)


def future_return(close: pd.Series, h: int) -> pd.Series:
    logc = np.log(close)
    return logc.shift(-h) - logc


# ---------------------------------------------------------------- walk-forward


def _ols(X: np.ndarray, y: np.ndarray, ridge: float = 1e-3) -> np.ndarray:
    X1 = np.c_[np.ones(len(X)), X]
    mu, sd = X1[:, 1:].mean(0), X1[:, 1:].std(0)
    sd[sd == 0] = 1.0
    Z = np.c_[np.ones(len(X)), (X1[:, 1:] - mu) / sd]
    beta = np.linalg.solve(Z.T @ Z + ridge * len(Z) * np.diag([0] + [1] * (Z.shape[1] - 1)), Z.T @ y)
    return np.r_[beta[0] - (beta[1:] * mu / sd).sum(), beta[1:] / sd]


@dataclass
class Result:
    horizon: int
    label: str
    windows: pd.DataFrame  # one row per test window: actual, each model's forecast, range low/high


def walk_forward(close: pd.Series, macro: dict[str, pd.Series], h: int, label: str = "",
                 min_train_years: int = MIN_TRAIN_YEARS) -> Result:
    feats = build_features(close, macro, h)
    y = future_return(close, h)
    days = close.index
    first = days[0] + pd.DateOffset(years=min_train_years)
    origins = [i for i in range(len(days)) if days[i] >= first and not np.isnan(y.iloc[i])][::h]
    macro_cols = list(feats.columns)
    rows = []
    for i in origins:
        known = y.iloc[: i - h + 1].dropna()  # windows that ended on or before day i
        if len(known) < 250:
            continue
        x_now = feats.iloc[i]
        row = {"day": days[i], "actual": float(y.iloc[i]), "no_change": 0.0,
               "average_drift": float(known.mean()),
               "trend": float(x_now["past_return"]) if not np.isnan(x_now["past_return"]) else float(known.mean())}
        train = feats.loc[known.index].join(known.rename("y")).dropna()
        if len(train) >= 250 and not x_now[macro_cols].isna().any():
            beta = _ols(train[macro_cols].to_numpy(), train["y"].to_numpy())
            row["macro"] = float(beta[0] + x_now[macro_cols].to_numpy() @ beta[1:])
        else:
            row["macro"] = np.nan
        lo, hi = np.quantile(known.to_numpy(), [(1 - RANGE_COVERAGE) / 2, (1 + RANGE_COVERAGE) / 2])
        row["range_low"], row["range_high"] = float(lo), float(hi)
        rows.append(row)
    return Result(h, label, pd.DataFrame(rows).set_index("day") if rows else pd.DataFrame())


# ---------------------------------------------------------------- scoring


def _sign_test_p(wins: int, n: int) -> float | None:
    if n == 0:
        return None
    try:
        from scipy.stats import binomtest

        return float(binomtest(wins, n, 0.5, alternative="greater").pvalue)
    except ImportError:
        return 0.5 * math.erfc((wins - n / 2) / (math.sqrt(n) / 2) / math.sqrt(2))


def _score(w: pd.DataFrame, model: str) -> dict:
    d = w.dropna(subset=[model])
    err = (d[model] - d["actual"]).abs()
    base_nc = d["actual"].abs()
    base_dr = (d["average_drift"] - d["actual"]).abs()
    beats_nc = int((err < base_nc).sum())
    return {
        "windows": len(d),
        "avg_error_pct": round(float(err.mean()) * 100, 2),
        "vs_no_change": round(1 - float(err.mean()) / float(base_nc.mean()), 3) if base_nc.mean() else None,
        "vs_average_drift": round(1 - float(err.mean()) / float(base_dr.mean()), 3) if base_dr.mean() else None,
        "direction_right": round(float((np.sign(d[model]) == np.sign(d["actual"])).mean()), 3) if model != "no_change" else None,
        "beat_no_change_windows": beats_nc,
        "p_value": _sign_test_p(beats_nc, len(d)),
    }


def verdict(s: dict) -> str:
    if not s["windows"]:
        return "not enough data"
    ok = (s["vs_no_change"] is not None and s["vs_no_change"] >= 0.05 and s["vs_average_drift"] is not None
          and s["vs_average_drift"] >= 0.05 and s["p_value"] is not None and s["p_value"] < 0.05)
    return "useful" if ok else "no better than the baselines"


def evaluate(res: Result) -> dict:
    w = res.windows
    if w.empty:
        return {"horizon_days": res.horizon, "status": "insufficient"}
    models = {}
    for m in MODELS:
        s = _score(w, m)
        if m not in ("no_change", "average_drift"):
            s["verdict"] = verdict(s)
        models[m] = s
    inside = (w["actual"] >= w["range_low"]) & (w["actual"] <= w["range_high"])
    eras = {}
    for name, a, b in ERAS:
        e = w.loc[a:b]
        if len(e):
            eras[name] = {"windows": len(e), "actual_up_share": round(float((e["actual"] > 0).mean()), 2),
                          **{f"{m}_error_pct": round(float((e[m] - e["actual"]).abs().mean()) * 100, 2)
                             for m in MODELS if e[m].notna().any()}}
    return {
        "horizon_days": res.horizon, "label": res.label, "status": "ok",
        "first_forecast": w.index[0].date().isoformat(), "last_forecast": w.index[-1].date().isoformat(),
        "always_up_right": round(float((w["actual"] > 0).mean()), 3),
        "models": models,
        "range": {"target_coverage": RANGE_COVERAGE, "actual_coverage": round(float(inside.mean()), 3),
                  "windows": len(w)},
        "by_era": eras,
    }


def today_range(close: pd.Series, h: int) -> dict:
    """The tested range for today: where the price landed ``h`` days later in 80% of all past windows."""
    known = future_return(close, h).dropna()
    lo, hi = np.quantile(known.to_numpy(), [(1 - RANGE_COVERAGE) / 2, (1 + RANGE_COVERAGE) / 2])
    last = float(close.iloc[-1])
    return {"horizon_days": h, "as_of": close.index[-1].date().isoformat(), "price": round(last, 2),
            "low": round(last * math.exp(lo), 2), "high": round(last * math.exp(hi), 2)}


def report(asset_label: str, close: pd.Series, macro: dict[str, pd.Series]) -> dict:
    results = [evaluate(walk_forward(close, macro, h, label)) for h, label in HORIZONS]
    useful = any(r.get("models", {}).get(m, {}).get("verdict") == "useful"
                 for r in results for m in ("trend", "macro"))
    covered = all(r.get("status") == "ok" and abs(r["range"]["actual_coverage"] - RANGE_COVERAGE) <= 0.10
                  for r in results)
    out = {"version": VERSION, "asset": asset_label, "history_from": close.index[0].date().isoformat(),
           "walk_forward": results, "any_model_useful": useful}
    if covered:
        out["today_range"] = [today_range(close, h) for h, _ in HORIZONS]
    else:
        out["today_range_note"] = "The 80% range did not hold close to 80% in the test, so it is not shown."
    return out
