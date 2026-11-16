"""Replay the BUY / WAIT / WATCH CLOSELY rules over past Nepal publication days.

Each day is judged once, at DECISION_TIME Nepal time, using only what existed then: completed
candles, Nepal prices already published, earlier dollar rates, and the FOMC calendar. The same
functions as the live snapshot decide (analysis.timeframe_state, nepal.analyse, rules.decide).

Not replayed: live quotes (the last completed 1h close stands in), the waiting clock, and the owner's
watch levels (the asset defaults are used). The world-price outlook, which only decides whether a BUY
is split in two parts, is replayed from the 1h, 4h and 1D parts of the score plus macro and event
risk (the live score also has 15m and 1W parts). US data-release dates exist from 2026 only, so
earlier two-part deadlines use FOMC dates or the 7-day default.

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

from gold_advisor import analysis, freshness, trading
from gold_advisor.analytics import position, score
from gold_advisor.analytics.decision_evaluation import Evaluation, Observation, evaluate
from gold_advisor.assets import AssetDefinition
from gold_advisor.decision import nepal, rules, split
from gold_advisor.domain import NEPAL_TZ, UTC, Decision, MassUnit, Source, Timeframe
from gold_advisor.persistence.models import CandleRow, EconomicEventRow, FxRateRow, LocalMetalRateRow, MacroObservationRow

VERSION = "backtest-2"
DECISION_TIME = time(12, 0)  # Nepal time, after the usual 10:00-11:00 publication
TIMEFRAMES = (Timeframe.H1, Timeframe.H4, Timeframe.D1)
DECIDING_TIMEFRAMES = (Timeframe.H4, Timeframe.D1)  # the only ones the rules read
SCORE_TIMEFRAMES = (Timeframe.H1, Timeframe.H4, Timeframe.D1)  # for the replayed outlook
MACRO_SERIES = ("DFII10", "DGS2")
PUBLICATIONS_LOADED = 40
FX_LOADED = 120
FX_MAX_AGE_DAYS = 5


@dataclass(frozen=True)
class History:
    bars: dict[Timeframe, pd.DataFrame]  # open/high/low/close indexed by UTC bucket_start
    publications: list[nepal.Publication]  # sorted by rate_date
    fx_mid: pd.Series  # NRB USD/NPR midpoint indexed by Timestamp(rate_date)
    major_events: list[tuple[datetime, str]]  # (scheduled_at UTC, title), sorted
    announcements: list[tuple[datetime, str]] = ()  # major and high importance, sorted
    macro: dict[str, pd.Series] | None = None  # FRED series indexed by Timestamp(obs_date)


@dataclass(frozen=True)
class Day:
    day: date
    at: datetime
    nepal_price: float
    decision: Decision
    rule: str
    next_price_change_pct: float | None
    outlook: str | None = None
    split_dip: float | None = None  # rupees; set when this BUY would be split in two parts
    split_recovery: float | None = None
    split_deadline: date | None = None
    trade_facts: trading.MarketFacts | None = None  # what the silver trade rule reads that day


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
        select(EconomicEventRow.scheduled_at, EconomicEventRow.title, EconomicEventRow.importance)
        .where(EconomicEventRow.importance.in_(("major", "high"))).order_by(EconomicEventRow.scheduled_at)
    ).all()
    macro = {}
    for series_id in MACRO_SERIES:
        rows = session.execute(
            select(MacroObservationRow.obs_date, MacroObservationRow.value)
            .where(MacroObservationRow.source == Source.FRED.value, MacroObservationRow.series_id == series_id)
            .order_by(MacroObservationRow.obs_date)
        ).all()
        macro[series_id] = pd.Series({pd.Timestamp(d): (float(v) if v is not None else np.nan) for d, v in rows}, dtype=float)
    return History(
        bars=bars,
        publications=[nepal.Publication(d, at, float(p)) for d, at, p in pubs],
        fx_mid=pd.Series({pd.Timestamp(d): (float(b) + float(s)) / 2 for d, b, s in fx}, dtype=float).sort_index(),
        major_events=[(at, title) for at, title, imp in events if imp == "major"],
        announcements=[(at, title) for at, title, _ in events],
        macro=macro,
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
        announcements=history.announcements,  # release dates are published ahead too
        macro={k: v[v.index < pd.Timestamp(today)] for k, v in (history.macro or {}).items()},
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

    per_tf, states, ind_by_tf, detail = {}, {}, {}, {}
    for tf in SCORE_TIMEFRAMES:
        if bars[tf].empty:
            continue
        ind_by_tf[tf], per_tf[tf], states[tf], detail[tf.value] = analysis.timeframe_state(bars[tf], tf, now, price_now, list(asset.watch_levels))
    h4_ok, h4_detail = analysis.h4_stabilization(ind_by_tf[Timeframe.H4]) if Timeframe.H4 in ind_by_tf else (None, "no 4h bars")

    xau_by_end = pd.Series(h1["close"].to_numpy(), index=h1.index + Timeframe.H1.duration)
    lag = nepal.analyse(pubs, xau_by_end, fx_mid, price_now)
    hourly_vol = nepal.hourly_volatility(h1["close"])
    nxt = nepal.forecast_next(lag, now, hourly_vol, asset.calendar.is_open, asset.nepal_price_step)
    event = next(((at, title) for at, title in history.major_events if at > now - timedelta(hours=1)), None)

    strong = analysis.strong_breakdown({tf: per_tf[tf] for tf in DECIDING_TIMEFRAMES if tf in per_tf}, states)
    hours_to_event = (event[0] - now).total_seconds() / 3600 if event else None
    result = rules.decide(rules.DecisionInputs(
        essential_issues=issues,
        lag=lag,
        hours_to_next_major_event=hours_to_event,
        next_event_title=event[1] if event else None,
        strong_breakdown=strong,
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
    components = score.aggregate_technical(per_tf)
    macro = {k: v[v.index < pd.Timestamp(today)] for k, v in (history.macro or {}).items()}  # published before today
    components["macro"] = score.macro(macro.get("DFII10"), macro.get("DGS2"), None)
    components["event_risk"] = score.event_risk(score.base_direction(components), hours_to_event)
    outlook = score.outlook(score.combine(components)[0])
    dip = recovery = deadline = None
    reason = split.reason_for(result.decision, outlook, bool(strong and h4_ok))
    if reason and lag.premium_mean is not None:
        factor = float(fx_mid.iloc[-1]) * nepal.OUNCES_PER_TOLA * (1 + lag.premium_mean)
        keys = position.key_levels(
            {tf: d["levels"] for tf, d in detail.items() if tf != Timeframe.H1.value},
            {tf: d["level_states"] for tf, d in detail.items() if tf != Timeframe.H1.value},
            price_now, factor, asset.level_rupee_step,
        )
        plan = split.plan(
            reason,
            [k.rupees for k in keys if k.kind == "floor" and k.rupees is not None],
            [k.rupees for k in keys if k.kind == "ceiling" and k.rupees is not None],
            pubs[-1].price,
            now,
            list(history.announcements),
        )
        dip, recovery, deadline = plan.dip_npr, plan.recovery_npr, plan.deadline
    facts = None
    if asset.tradable and Timeframe.D1.value in detail:
        facts = trading.market_facts(bars[Timeframe.D1], detail["1D"]["level_states"], detail["1D"]["levels"])
    return Day(today, now, pubs[-1].price, result.decision, result.rule, nxt.change_pct if nxt else None,
               outlook.value if outlook else None, dip, recovery, deadline, facts)


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


def _second_half(days: list[Day], i: int) -> Day | None:
    """The first later publication day that meets a second-half trigger of the BUY on ``days[i]``."""
    first = days[i]
    for d in days[i + 1 :]:
        if (first.split_dip is not None and d.nepal_price <= first.split_dip) or (
            first.split_recovery is not None and d.nepal_price >= first.split_recovery
        ) or d.day >= first.split_deadline:
            return d
    return None


def compare_split(days: list[Day], horizon_days: int = 7, max_gap_days: int = 2) -> dict:
    """One purchase on the first BUY of each period against the two-part rule, over the same
    non-overlapping periods as ``decision_evaluation.evaluate``. Costs are against buying on the
    period's first day, per tola, fees not included. A period whose second half has not been
    triggered by the end of the data is left out."""
    one, two, diff_npr, diff_split, cheaper = [], [], [], [], 0
    split_windows = left_out = 0
    i = 0
    while i < len(days):
        deadline = days[i].day + timedelta(days=horizon_days)
        j = i + 1
        while j < len(days) and days[j].day <= deadline:
            j += 1
        if j == len(days) and days[j - 1].day < deadline:
            break
        window = days[i:j]
        gaps = [(b.day - a.day).days for a, b in zip(window, window[1:])]
        if len(window) >= 2 and max(gaps, default=0) <= max_gap_days and (deadline - window[-1].day).days <= max_gap_days:
            k = next((n for n in range(i, j) if days[n].decision is Decision.BUY), None)
            whole = days[k] if k is not None else window[-1]
            paid_one = whole.nepal_price
            paid_two = paid_one
            if k is not None and days[k].split_deadline is not None:
                second = _second_half(days, k)
                if second is None:
                    left_out += 1
                    i = j
                    continue
                split_windows += 1
                paid_two = (days[k].nepal_price + second.nepal_price) / 2
                diff_split.append(paid_two - paid_one)
                cheaper += paid_two < paid_one
            initial = window[0].nepal_price
            one.append(paid_one / initial - 1)
            two.append(paid_two / initial - 1)
            diff_npr.append(paid_two - paid_one)
        i = j
    n = len(one)
    mean = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    return {
        "windows": n,
        "split_windows": split_windows,
        "left_out_untriggered": left_out,
        "one_purchase_mean_cost_pct": mean(one) * 100 if n else None,
        "two_part_mean_cost_pct": mean(two) * 100 if n else None,
        "two_minus_one_npr_per_tola_all_windows": mean(diff_npr),
        "two_minus_one_npr_per_tola_split_windows": mean(diff_split),
        "split_windows_cheaper": cheaper,
        "verdict": (
            None if not split_windows else
            "two-part buying was cheaper on average" if mean(diff_split) < 0 else "one purchase was cheaper or equal on average"
        ),
    }


TRADE_GAPS = (0.0, 0.02, 0.04)


def trade_replay(days: list[Day], budget: float = trading.DEFAULT_BUDGET) -> dict:
    """The silver trade rule over the replay days, at buy-back gaps of 0%, 2% and 4%."""
    series = [(d.day.isoformat(), d.nepal_price, d.trade_facts) for d in days]
    return {
        "version": trading.VERSION,
        "budget_npr": budget,
        "results": [trading.replay(series, gap, budget) for gap in TRADE_GAPS],
    }
