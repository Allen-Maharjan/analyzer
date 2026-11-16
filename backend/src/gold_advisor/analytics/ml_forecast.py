"""LightGBM direction forecaster for world gold and silver (evidence only, never the decision).

Question it answers: "Will the world price be higher or lower in 1, 3 and 5 trading days?"
It learns from daily candles (both metals) and US interest rates, and is judged walk-forward:
retrained every month on the past only, then asked about the next month it has never seen.
Its hit rate is compared with two simple baselines, "always guess the more common direction" and
"guess that the last 20 days' direction continues". A model that cannot beat those has no edge.

No-leak rules:
- a day's features use only that day's completed candle and earlier ones;
- FRED rates are lagged one business day (they are published the day after their date);
- training stops ``horizon`` days before each test month, so no training label overlaps a test day.

``lightgbm`` is an optional dependency (``pip install -e backend[ml]``); it is imported lazily so the
API and the cycle never need it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

VERSION = "ml-forecast-1"
HORIZONS = (1, 3, 5)  # trading days; roughly the app's 24 hours, 3 days and 7 days
MIN_TRAIN_DAYS = 756  # three years before the first test month
STEP_DAYS = 21  # retrain monthly
CONFIDENT = 0.10  # "confident" means the model's chance of up is below 40% or above 60%
MACRO_SERIES = ("DGS10", "DGS2", "DFII10")

MODEL_PARAMS = dict(
    n_estimators=200,
    learning_rate=0.03,
    num_leaves=15,
    min_child_samples=40,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    random_state=0,
    verbose=-1,
)


# ---------------------------------------------------------------- features


def daily_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Weekday daily bars indexed by date. Dukascopy's short Sunday-evening bar is dropped."""
    out = df[["open", "high", "low", "close"]].astype(float).copy()
    out.index = pd.DatetimeIndex(pd.to_datetime(out.index, utc=True).tz_convert(None).normalize())
    out = out[out.index.dayofweek < 5]
    return out[~out.index.duplicated(keep="last")].sort_index()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def _atr(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = bars["close"].shift(1)
    tr = pd.concat([bars["high"] - bars["low"], (bars["high"] - prev).abs(), (bars["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def _price_features(bars: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
    c = bars["close"]
    logc = np.log(c)
    atr_pct = _atr(bars) / c
    ret1 = logc.diff()
    f = {}
    for n in (1, 3, 5, 10, 20, 60):
        f[f"ret_{n}"] = logc.diff(n)
    for n in (20, 50, 200):
        ema = c.ewm(span=n, adjust=False, min_periods=n).mean()
        f[f"dist_ema{n}"] = (c / ema - 1) / atr_pct
    f["rsi_14"] = _rsi(c)
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    f["macd_hist"] = (macd - macd.ewm(span=9, adjust=False).mean()) / c
    f["atr_pct"] = atr_pct
    vol20 = ret1.rolling(20).std()
    f["vol_20"] = vol20
    f["vol_ratio"] = ret1.rolling(5).std() / vol20
    lo, hi = bars["low"].rolling(20).min(), bars["high"].rolling(20).max()
    f["range_pos_20"] = (c - lo) / (hi - lo).replace(0, np.nan)
    span = (bars["high"] - bars["low"]).replace(0, np.nan)
    f["body"] = (c - bars["open"]) / span
    f["upper_wick"] = (bars["high"] - bars[["open", "close"]].max(axis=1)) / span
    f["lower_wick"] = (bars[["open", "close"]].min(axis=1) - bars["low"]) / span
    out = pd.DataFrame(f, index=bars.index)
    return out.add_prefix(prefix)


def build_features(bars: pd.DataFrame, other: pd.DataFrame | None = None,
                   macro: dict[str, pd.Series] | None = None) -> pd.DataFrame:
    """One row per trading day of ``bars``, using only information known at that day's close."""
    feats = _price_features(bars)
    feats["dow"] = bars.index.dayofweek.astype(float)
    if other is not None and len(other):
        o = other.reindex(bars.index).ffill()
        logo = np.log(o["close"])
        for n in (1, 5, 20):
            feats[f"other_ret_{n}"] = logo.diff(n)
        ratio = np.log(bars["close"]) - logo
        feats["ratio_z60"] = (ratio - ratio.rolling(60).mean()) / ratio.rolling(60).std()
    for sid, series in (macro or {}).items():
        if series is None or series.empty:
            continue
        s = series.astype(float).copy()
        s.index = pd.DatetimeIndex(pd.to_datetime(s.index)).normalize()
        s = s.sort_index().dropna()
        # Published the business day after its date: shift by one business day, then align.
        s.index = s.index + pd.offsets.BDay(1)
        aligned = s.reindex(bars.index.union(s.index)).ffill().reindex(bars.index)
        feats[f"{sid}_level"] = aligned
        feats[f"{sid}_chg5"] = aligned.diff(5)
    return feats


def labels(close: pd.Series, horizon: int) -> pd.Series:
    """1.0 if the close ``horizon`` trading days later is higher, 0.0 if not, NaN if not yet known."""
    future = close.shift(-horizon)
    out = (future > close).astype(float)
    out[future.isna()] = np.nan
    return out


# ---------------------------------------------------------------- walk-forward


@dataclass
class Fold:
    train_end: pd.Timestamp  # last training day (inclusive)
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass
class WalkForward:
    horizon: int
    predictions: pd.DataFrame  # index day; columns p_up, actual, majority, momentum
    folds: list[Fold] = field(default_factory=list)


class _Model:
    """Binary LightGBM via the native API (no scikit-learn needed)."""

    def __init__(self, params: dict | None = None):
        p = {**MODEL_PARAMS, **(params or {})}
        self.rounds = p.pop("n_estimators")
        self.params = {"objective": "binary", "learning_rate": p["learning_rate"], "num_leaves": p["num_leaves"],
                       "min_data_in_leaf": p["min_child_samples"], "bagging_fraction": p["subsample"],
                       "bagging_freq": p["subsample_freq"], "feature_fraction": p["colsample_bytree"],
                       "lambda_l2": p["reg_lambda"], "seed": p["random_state"], "verbose": p["verbose"],
                       "deterministic": True, "num_threads": 1}
        self.booster = None

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "_Model":
        import lightgbm as lgb

        self.booster = lgb.train(self.params, lgb.Dataset(X, label=y.to_numpy(float)), num_boost_round=self.rounds)
        return self

    def predict_up(self, X: pd.DataFrame) -> np.ndarray:
        return self.booster.predict(X)


def _model(params: dict | None = None) -> _Model:
    return _Model(params)


def walk_forward(feats: pd.DataFrame, close: pd.Series, horizon: int, *, min_train: int = MIN_TRAIN_DAYS,
                 step: int = STEP_DAYS, params: dict | None = None) -> WalkForward:
    y = labels(close, horizon)
    usable = feats.notna().sum(axis=1) >= max(1, int(0.8 * feats.shape[1]))
    days = feats.index[usable & y.notna()]
    X, Y = feats.loc[days], y.loc[days]
    mom = np.sign(feats.loc[days, "ret_20"]) if "ret_20" in feats else pd.Series(0.0, index=days)
    rows, folds = [], []
    start = min_train
    while start < len(days):
        stop = min(start + step, len(days))
        train_stop = start - horizon  # purge: labels of these rows end before the test month
        if train_stop < 100:
            start = stop
            continue
        Xtr, Ytr = X.iloc[:train_stop], Y.iloc[:train_stop]
        model = _model(params)
        model.fit(Xtr, Ytr)
        Xte = X.iloc[start:stop]
        p = model.predict_up(Xte)
        majority = float(Ytr.mean() >= 0.5)
        for day, prob in zip(Xte.index, p):
            rows.append({"day": day, "p_up": float(prob), "actual": float(Y.loc[day]),
                         "majority": majority, "momentum": float(mom.loc[day] > 0),
                         "train_up_rate": float(Ytr.mean())})
        folds.append(Fold(train_end=X.index[train_stop - 1], test_start=Xte.index[0], test_end=Xte.index[-1]))
        start = stop
    preds = pd.DataFrame(rows).set_index("day") if rows else pd.DataFrame(
        columns=["p_up", "actual", "majority", "momentum", "train_up_rate"])
    return WalkForward(horizon=horizon, predictions=preds, folds=folds)


# ---------------------------------------------------------------- scoring


def _p_value(hits: int, n: int, baseline: float) -> float | None:
    """One-sided chance of at least ``hits`` correct out of ``n`` if the true hit rate were ``baseline``."""
    if n == 0:
        return None
    try:
        from scipy.stats import binomtest

        return float(binomtest(hits, n, min(max(baseline, 1e-9), 1 - 1e-9), alternative="greater").pvalue)
    except ImportError:  # normal approximation
        sd = math.sqrt(n * baseline * (1 - baseline)) or 1.0
        return 0.5 * math.erfc((hits - n * baseline) / sd / math.sqrt(2))


def evaluate(wf: WalkForward) -> dict:
    p = wf.predictions
    n = len(p)
    if n == 0:
        return {"horizon_days": wf.horizon, "status": "insufficient", "tested_days": 0}
    pred = (p["p_up"] >= 0.5).astype(float)
    hit = pred == p["actual"]
    acc = float(hit.mean())
    acc_major = float((p["majority"] == p["actual"]).mean())
    acc_mom = float((p["momentum"] == p["actual"]).mean())
    best_base = max(acc_major, acc_mom)
    brier = float(((p["p_up"] - p["actual"]) ** 2).mean())
    brier_clim = float(((p["train_up_rate"] - p["actual"]) ** 2).mean())
    conf = (p["p_up"] - 0.5).abs() >= CONFIDENT
    by_year = {}
    for year, g in p.groupby(p.index.year):
        gp = (g["p_up"] >= 0.5).astype(float)
        by_year[int(year)] = {"days": len(g), "model": round(float((gp == g["actual"]).mean()), 4),
                              "always_majority": round(float((g["majority"] == g["actual"]).mean()), 4)}
    # Overlapping 3- and 5-day windows make neighbouring days near-copies; count independent windows.
    effective_n = max(1, n // wf.horizon)
    return {
        "horizon_days": wf.horizon,
        "status": "ok",
        "tested_days": n,
        "first_day": p.index[0].date().isoformat(),
        "last_day": p.index[-1].date().isoformat(),
        "up_share": round(float(p["actual"].mean()), 4),
        "hit_rate": round(acc, 4),
        "baseline_always_majority": round(acc_major, 4),
        "baseline_momentum_20d": round(acc_mom, 4),
        "edge_vs_best_baseline": round(acc - best_base, 4),
        "p_value_vs_best_baseline": _p_value(round(acc * effective_n), effective_n, best_base),
        "brier": round(brier, 4),
        "brier_baseline": round(brier_clim, 4),
        "confident_share": round(float(conf.mean()), 4),
        "confident_hit_rate": round(float(hit[conf].mean()), 4) if conf.any() else None,
        "by_year": by_year,
        "retrains": len(wf.folds),
    }


def verdict(ev: dict) -> str:
    if ev.get("status") != "ok":
        return "not enough history to judge"
    edge, pv = ev["edge_vs_best_baseline"], ev["p_value_vs_best_baseline"]
    if edge >= 0.03 and pv is not None and pv < 0.05:
        return "useful edge"
    if edge > 0.01:
        return "small edge, could be luck"
    return "no edge"


def plain_summary(label: str, ev: dict) -> str:
    if ev.get("status") != "ok":
        return f"{label}: not enough history to test."
    return (
        f"{label}, {ev['horizon_days']} trading day(s) ahead: right {ev['hit_rate']:.0%} of {ev['tested_days']} unseen days; "
        f"always guessing '{'up' if ev['up_share'] >= 0.5 else 'down'}' was right {ev['baseline_always_majority']:.0%}, "
        f"following the last 20 days was right {ev['baseline_momentum_20d']:.0%}. Verdict: {verdict(ev)}."
    )


# ---------------------------------------------------------------- today's forecast


def predict_latest(feats: pd.DataFrame, close: pd.Series, horizon: int, params: dict | None = None) -> dict:
    """Train on every labelled day, then give today's chance that price is higher ``horizon`` days on."""
    y = labels(close, horizon)
    usable = feats.notna().sum(axis=1) >= max(1, int(0.8 * feats.shape[1]))
    train = feats.index[usable & y.notna()]
    model = _model(params)
    model.fit(feats.loc[train], y.loc[train])
    today = feats.index[-1]
    p = float(model.predict_up(feats.loc[[today]])[0])
    importance = sorted(zip(feats.columns, model.booster.feature_importance("gain")), key=lambda t: -t[1])
    total = sum(v for _, v in importance) or 1.0
    return {
        "horizon_days": horizon,
        "as_of": today.date().isoformat(),
        "chance_up": round(p, 4),
        "top_inputs": [{"feature": k, "share": round(float(v) / total, 4)} for k, v in importance[:8]],
    }


# ---------------------------------------------------------------- loading and full report


def load_inputs(session, asset) -> tuple[pd.DataFrame, pd.DataFrame | None, dict[str, pd.Series]]:
    """Daily candles for ``asset`` and the other metal, plus FRED rates. Read-only."""
    from sqlalchemy import select

    from gold_advisor.assets import ASSETS
    from gold_advisor.domain import Source
    from gold_advisor.persistence.models import CandleRow, MacroObservationRow

    def candles(a) -> pd.DataFrame:
        rows = session.execute(
            select(CandleRow.bucket_start, CandleRow.open, CandleRow.high, CandleRow.low, CandleRow.close)
            .where(CandleRow.source == a.candle_source.value, CandleRow.instrument == a.instrument,
                   CandleRow.timeframe == "1D")
            .order_by(CandleRow.bucket_start)
        ).all()
        df = pd.DataFrame(rows, columns=["bucket_start", "open", "high", "low", "close"]).set_index("bucket_start")
        return daily_bars(df.astype(float))

    bars = candles(asset)
    others = [a for a in ASSETS.values() if a.id != asset.id]
    other = candles(others[0]) if others else None
    macro = {}
    for sid in MACRO_SERIES:
        rows = session.execute(
            select(MacroObservationRow.obs_date, MacroObservationRow.value)
            .where(MacroObservationRow.source == Source.FRED.value, MacroObservationRow.series_id == sid)
            .order_by(MacroObservationRow.obs_date)
        ).all()
        macro[sid] = pd.Series({pd.Timestamp(d): (float(v) if v is not None else np.nan) for d, v in rows}, dtype=float)
    return bars, other, macro


def report(asset_label: str, bars: pd.DataFrame, other: pd.DataFrame | None, macro: dict[str, pd.Series],
           horizons: tuple[int, ...] = HORIZONS, params: dict | None = None) -> dict:
    feats = build_features(bars, other, macro)
    close = bars["close"]
    results, latest = [], []
    for h in horizons:
        ev = evaluate(walk_forward(feats, close, h, params=params))
        ev["verdict"] = verdict(ev)
        ev["plain"] = plain_summary(asset_label, ev)
        results.append(ev)
        latest.append(predict_latest(feats, close, h, params=params))
    out = {"version": VERSION, "asset": asset_label, "features": list(feats.columns),
           "walk_forward": results, "today": latest}
    if not any(ev.get("verdict") == "useful edge" for ev in results):
        out["today_warning"] = ("Not a prediction: the model did not beat simple guessing in the test above, "
                                "so these chances carry no information.")
    return out
