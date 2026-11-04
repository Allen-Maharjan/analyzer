"""Replay the BUY / WAIT / WATCH CLOSELY rules over past Nepal publication days.

Each day is judged once, at DECISION_TIME Nepal time, using only what existed then: completed
candles, Nepal prices already published, earlier dollar rates, and the FOMC calendar. The same
functions as the live snapshot decide (analysis.timeframe_state, nepal.analyse, rules.decide).

Not replayed: live quotes (the last completed 1h close stands in), the world-price score (it never
changes the decision), the waiting clock, and the owner's watch levels (the asset defaults are used).

``lookahead_check`` reruns sampled days on history cut off at the decision time and reports any day
whose answer changes, which would mean the replay saw the future.
"""

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from gold_advisor import analysis, freshness
from gold_advisor.analytics.decision_evaluation import Evaluation, Observation, evaluate
from gold_advisor.assets import AssetDefinition
from gold_advisor.decision import nepal, rules
from gold_advisor.domain import NEPAL_TZ, UTC, Decision, MassUnit, Source, Timeframe
from gold_advisor.persistence.models import CandleRow, EconomicEventRow, FxRateRow, LocalMetalRateRow

VERSION = "backtest-1"
DECISION_TIME = time(12, 0)  # Nepal time, after the usual 10:00-11:00 publication
TIMEFRAMES = (Timeframe.H1, Timeframe.H4, Timeframe.D1)
DECIDING_TIMEFRAMES = (Timeframe.H4, Timeframe.D1)  # the only ones the rules read
PUBLICATIONS_LOADED = 40
FX_LOADED = 120
FX_MAX_AGE_DAYS = 5


@dataclass(frozen=True)
class History:
    bars: dict[Timeframe, pd.DataFrame]  # open/high/low/close indexed by UTC bucket_start
    publications: list[nepal.Publication]  # sorted by rate_date
    fx_mid: pd.Series  # NRB USD/NPR midpoint indexed by Timestamp(rate_date)
    major_events: list[tuple[datetime, str]]  # (scheduled_at UTC, title), sorted


@dataclass(frozen=True)
class Day:
    day: date
    at: datetime
    nepal_price: float
    decision: Decision
    rule: str
    next_price_change_pct: float | None


def load(session: Session, asset: AssetDefinition) -> History:
    bars = {}
    for tf in TIMEFRAMES:
        rows = session.execute(
            select(CandleRow.bucket_start, CandleRow.open, CandleRow.high, CandleRow.low, CandleRow.close)
            .where(CandleRow.source == asset.candle_source.value, CandleRow.instrument == asset.instrument,
                   CandleRow.timeframe == tf.value)
            .order_by(CandleRow.bucket_start)
        ).all()
        df = pd.DataFrame(rows, columns=["bucket_start", "open", "high", "low", "close"]).set_index("bucket_start")
        bars[tf] = df.astype(float)
    pubs = session.execute(
        select(LocalMetalRateRow.rate_date, LocalMetalRateRow.published_at, LocalMetalRateRow.price_npr)
        .where(LocalMetalRateRow.source == Source.FENEGOSIDA.value, LocalMetalRateRow.metal == asset.metal.value,
               LocalMetalRateRow.purity == asset.purity.value, LocalMetalRateRow.unit == MassUnit.TOLA.value)
        .order_by(LocalMetalRateRow.rate_date)
    ).all()
    fx = session.execute(
        select(FxRateRow.rate_date, FxRateRow.buy, FxRateRow.sell)
        .where(FxRateRow.source == Source.NRB.value, FxRateRow.currency == "USD")
        .order_by(FxRateRow.rate_date)
    ).all()
    events = session.execute(
        select(EconomicEventRow.scheduled_at, EconomicEventRow.title)
        .where(EconomicEventRow.importance == "major").order_by(EconomicEventRow.scheduled_at)
    ).all()
    return History(
        bars=bars,
        publications=[nepal.Publication(d, at, float(p)) for d, at, p in pubs],
        fx_mid=pd.Series({pd.Timestamp(d): (float(b) + float(s)) / 2 for d, b, s in fx}, dtype=float).sort_index(),
        major_events=[(at, title) for at, title in events],
    )


def decision_instant(day: date) -> datetime:
    return datetime.combine(day, DECISION_TIME, tzinfo=NEPAL_TZ).astimezone(UTC)


def _completed(df: pd.DataFrame, tf: Timeframe, now: datetime) -> pd.DataFrame:
    return df[df.index + tf.duration <= now]


def cut_off(history: History, now: datetime) -> History:
    """History as it stood at ``now``: completed bars, published prices, earlier dollar rates."""
    today = now.astimezone(NEPAL_TZ).date()
    return History(
        bars={tf: _completed(df, tf, now) for tf, df in history.bars.items()},
        publications=[p for p in history.publications if nepal.publication_instant(p)[0] <= now],
        fx_mid=history.fx_mid[history.fx_mid.index <= pd.Timestamp(today)],
        major_events=history.major_events,  # FOMC dates are announced a year ahead
    )


def decide_at(history: History, asset: AssetDefinition, now: datetime) -> Day | None:
    """The rules' answer at ``now``, or None when that day can't be judged (no publication or data)."""
    today = now.astimezone(NEPAL_TZ).date()
    bars = {tf: _completed(history.bars[tf], tf, now).tail(analysis.BARS_LOADED[tf]) for tf in TIMEFRAMES}
    pubs = [p for p in history.publications if nepal.publication_instant(p)[0] <= now][-PUBLICATIONS_LOADED:]
    fx_mid = history.fx_mid[history.fx_mid.index <= pd.Timestamp(today)].tail(FX_LOADED)
    if not pubs or pubs[-1].rate_date != today or bars[Timeframe.H1].empty or fx_mid.empty:
        return None
    if (pd.Timestamp(today) - fx_mid.index[-1]).days > FX_MAX_AGE_DAYS:
        return None

    h1 = bars[Timeframe.H1]
    price_now = float(h1["close"].iloc[-1])
    issues = []
    h4 = bars[Timeframe.H4]
    if h4.empty or freshness.candles(Timeframe.H4, h4.index[-1], now, asset.calendar).status not in analysis.OK_STATUSES:
        issues.append(f"Recent world {asset.label.lower()} price history is out of date.")

    per_tf, states, ind_by_tf = {}, {}, {}
    for tf in DECIDING_TIMEFRAMES:
        if bars[tf].empty:
            continue
        ind_by_tf[tf], per_tf[tf], states[tf], _ = analysis.timeframe_state(bars[tf], tf, now, price_now, list(asset.watch_levels))
    h4_ok, h4_detail = analysis.h4_stabilization(ind_by_tf[Timeframe.H4]) if Timeframe.H4 in ind_by_tf else (None, "no 4h bars")

    xau_by_end = pd.Series(h1["close"].to_numpy(), index=h1.index + Timeframe.H1.duration)
    lag = nepal.analyse(pubs, xau_by_end, fx_mid, price_now)
    hourly_vol = float(np.log(h1["close"]).diff().tail(120).std()) if len(h1) > 30 else None
    nxt = nepal.forecast_next(lag, now, hourly_vol, asset.calendar.is_open, asset.nepal_price_step)
    event = next(((at, title) for at, title in history.major_events if at > now - timedelta(hours=1)), None)

    result = rules.decide(rules.DecisionInputs(
        essential_issues=issues,
        lag=lag,
        hours_to_next_major_event=(event[0] - now).total_seconds() / 3600 if event else None,
        next_event_title=event[1] if event else None,
        strong_breakdown=analysis.strong_breakdown(per_tf, states),
        h4_stabilized=h4_ok,
        h4_detail=h4_detail,
        score=None,
        outlook=None,
        coverage=0.0,
        waiting_days=None,
        asset=asset,
        next_price=nxt.estimate if nxt else None,
        next_price_change_pct=nxt.change_pct if nxt else None,
    ))
    return Day(today, now, pubs[-1].price, result.decision, result.rule, nxt.change_pct if nxt else None)


def run(history: History, asset: AssetDefinition, start: date, end: date) -> list[Day]:
    days = sorted({p.rate_date for p in history.publications if start <= p.rate_date <= end})
    return [d for d in (decide_at(history, asset, decision_instant(day)) for day in days) if d is not None]


def lookahead_check(history: History, asset: AssetDefinition, days: list[Day], sample: int = 30) -> list[dict]:
    """Rerun up to ``sample`` evenly spread days on history cut off at the decision time."""
    if not days:
        return []
    picks = [days[i] for i in sorted({round(i) for i in np.linspace(0, len(days) - 1, min(sample, len(days)))})]
    mismatches = []
    for d in picks:
        again = decide_at(cut_off(history, d.at), asset, d.at)
        if again != d:
            mismatches.append({"day": d.day, "full_history": asdict(d), "cut_off": asdict(again) if again else None})
    return mismatches


def summarise(days: list[Day], horizon_days: int = 7) -> dict:
    """How following the advice compares with buying on the first day of each window."""

    def scored(rows: list[Day]) -> Evaluation:
        return evaluate([Observation(d.day, d.nepal_price, d.decision) for d in rows], horizon_days=horizon_days)

    by_year = {}
    for year in sorted({d.day.year for d in days}):
        by_year[year] = asdict(scored([d for d in days if d.day.year == year]))
    overall = scored(days)
    return {
        "version": VERSION,
        "days": len(days),
        "first_day": days[0].day if days else None,
        "last_day": days[-1].day if days else None,
        "decisions": dict(Counter(d.decision.value for d in days)),
        "rules": dict(Counter(d.rule for d in days)),
        "overall": asdict(overall),
        "by_year": by_year,
        "plain": plain_summary(overall, horizon_days),
    }


def plain_summary(result: Evaluation, horizon_days: int) -> str:
    if result.status != "ok" or result.mean_cost_vs_immediate is None:
        return f"Not enough complete {horizon_days}-day periods to judge the advice yet ({result.windows} found)."
    saved = -result.mean_cost_vs_immediate * 100
    verdict = "less" if saved > 0 else "more"
    return (
        f"Across {result.windows} separate {horizon_days}-day periods, following the app's advice paid on average "
        f"{abs(saved):.2f}% {verdict} than buying on the first day. The best day in each period was on average "
        f"{result.mean_regret * 100:.2f}% cheaper than the advice's purchase, and "
        f"{result.mean_baseline_regret * 100:.2f}% cheaper than buying on the first day. Fees are not included."
    )
