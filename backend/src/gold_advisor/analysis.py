"""Build one immutable analysis snapshot from collected data.

Everything shown together on screen (prices, scores, reasons) comes from one snapshot,
identified by its ID. Building a snapshot never calls an external provider.
"""

import math
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from gold_advisor import announcements, freshness, health, trading
from gold_advisor.assets import AssetDefinition, GOLD
from gold_advisor.persistence import market_data
from gold_advisor.analytics import forecast, indicators, levels, position, score, technical
from gold_advisor.decision import nepal, rules, split
from gold_advisor.domain import (
    UTC,
    Decision,
    FreshnessStatus,
    Instrument,
    MassUnit,
    Metal,
    Purity,
    QualityFlag,
    Source,
    Timeframe,
)
from gold_advisor.persistence.models import (
    AnalysisSnapshotRow,
    AppSettingRow,
    CandleRow,
    EconomicEventRow,
    FxRateRow,
    LocalMetalRateRow,
    MacroObservationRow,
    PurchasePlanRow,
    SpotQuoteRow,
)

BARS_LOADED = {Timeframe.M15: 400, Timeframe.H1: 600, Timeframe.H4: 400, Timeframe.D1: 400, Timeframe.W1: 300}
WATCH_LEVEL_TIMEFRAMES = (Timeframe.H4, Timeframe.D1)
DEFAULT_WATCH_LEVELS = [4000.0]
STRONG_DOWN_MOMENTUM = -40.0
SELLOFF_LOOKBACK_H4 = 12
OK_STATUSES = (FreshnessStatus.FRESH, FreshnessStatus.MARKET_CLOSED)
VERSIONS = {
    "indicators": indicators.VERSION,
    "levels": levels.VERSION,
    "score": score.VERSION,
    "nepal": nepal.VERSION,
    "rules": rules.VERSION,
    "technical": technical.VERSION,
    "forecast": forecast.VERSION,
    "freshness": freshness.VERSION,
    "position": position.VERSION,
    "split": split.VERSION if split.ENABLED else f"{split.VERSION}-off",
    "announcements": announcements.VERSION,
    "trade": trading.VERSION,
}


def jsonable(value):
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (np.floating, float)):
        return None if math.isnan(value) else round(float(value), 4)
    if isinstance(value, np.integer):
        return int(value)
    return value


def _candles(session: Session, tf: Timeframe, limit: int | None = None, asset: AssetDefinition = GOLD) -> pd.DataFrame:
    rows = market_data.candles(session, market_data.MarketQuery(asset, tf, limit=limit or BARS_LOADED[tf]))
    df = pd.DataFrame([(r.bucket_start, r.open, r.high, r.low, r.close) for r in rows], columns=["bucket_start", "open", "high", "low", "close"])
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    return df.set_index("bucket_start")


def _setting(session: Session, key: str, default):
    row = session.get(AppSettingRow, key)
    return row.value.get("value", default) if row else default


def _current_price(session: Session, m15: pd.DataFrame, now: datetime, asset: AssetDefinition = GOLD) -> tuple[float | None, str, list[str]]:
    """The current world price, its source label and the quote's quality flags."""
    for source, label in ((Source.GOLD_API, "gold_api live spot"), (Source.SWISSQUOTE, "swissquote live spot (backup)")):
        quote = market_data.latest_quote(session, asset, (source,))
        if quote and freshness.live_quote(quote.observed_at, now, asset.calendar).status in OK_STATUSES:
            return float(quote.price), label, list(quote.quality_flags)
    if len(m15) and freshness.candles(Timeframe.M15, m15.index[-1], now, asset.calendar).status in OK_STATUSES:
        return float(m15["close"].iloc[-1]), "latest completed 15m Dukascopy close (live quote unavailable)", []
    return None, "unavailable", []


# A quiet Nepal source (holiday) is not a data problem: the normal rules still apply (rules-6).
NEPAL_OK_STATUSES = (*OK_STATUSES, FreshnessStatus.NOT_PUBLISHED)


def _essential_issues(datasets: dict[str, health.DatasetHealth], price_source: str, latest_nepal_flags: list[str], asset: AssetDefinition = GOLD,
                      price_flags: list[str] = ()) -> list[str]:
    issues = []
    if datasets[asset.local_dataset].freshness.status not in NEPAL_OK_STATUSES:
        issues.append(f"Today's Nepal {asset.label.lower()} price hasn't been collected yet.")
    if datasets["usd_npr"].freshness.status not in OK_STATUSES:
        issues.append("Today's dollar exchange rate hasn't been collected yet.")
    if price_source == "unavailable":
        issues.append(f"The current world {asset.label.lower()} price isn't available.")
    if QualityFlag.SOURCES_DISAGREE.value in price_flags:
        issues.append("Two price sources disagree about the world price.")
    if datasets[f"{asset.dataset_prefix}_candles_4h"].freshness.status not in OK_STATUSES:
        issues.append(f"Recent world {asset.label.lower()} price history is out of date.")
    if QualityFlag.UNIT_MISMATCH.value in latest_nepal_flags:
        issues.append("Nepal's published per-tola and per-10-gram prices don't match each other.")
    return issues


def h4_stabilization(ind: pd.DataFrame) -> tuple[bool | None, str]:
    if len(ind) < SELLOFF_LOOKBACK_H4 + 3:
        return None, "not enough 4h bars"
    last2 = ind.iloc[-2:]
    prior = ind.iloc[-2 - SELLOFF_LOOKBACK_H4 : -2]
    selloff_low = float(prior["low"].min())
    recent_low = float(last2["low"].min())
    rsi_up = ind["rsi_14"].iloc[-1] > ind["rsi_14"].iloc[-3]
    macd_up = ind["macd_hist"].iloc[-1] > ind["macd_hist"].iloc[-3]
    no_new_low = recent_low > selloff_low
    ok = bool(no_new_low and (rsi_up or macd_up))
    detail = (
        f"Last two completed 4h lows {recent_low:.2f} vs prior selloff low {selloff_low:.2f} "
        f"({'no new low' if no_new_low else 'new low'}); RSI {'rising' if rsi_up else 'not rising'}, "
        f"MACD histogram {'rising' if macd_up else 'not rising'}."
    )
    return ok, detail


def timeframe_state(df: pd.DataFrame, tf: Timeframe, now: datetime, price_now: float | None,
                    watch_levels: list[float]) -> tuple[pd.DataFrame, dict[str, score.Component], list[dict], dict]:
    """Indicators, score components, level states and display detail for one timeframe."""
    ind = indicators.compute(df, tf)
    latest = indicators.latest_values(ind)
    recent = df.tail(levels.LOOKBACK_BARS)
    pivots = [p for p in levels.find_pivots(recent, tf) if p.available_at <= now]
    close = float(df["close"].iloc[-1])
    lvls = levels.cluster_levels(pivots, latest.get("atr_14") or 0, close, tf)
    if tf in WATCH_LEVEL_TIMEFRAMES:
        lvls += [levels.manual_level(p, close, tf) for p in watch_levels]
    states = levels.as_dicts(levels.level_state(lvl, ind, price_now) for lvl in lvls)
    swing = levels.swing_structure(pivots, now)
    components = {
        "trend": score.trend(ind),
        "momentum": score.momentum(ind),
        "structure": score.structure(swing, [s for s in states if s["state"] != "none"]),
    }
    detail = {
        "last_bar_start": df.index[-1],
        "indicators": latest,
        "levels": levels.as_dicts(lvls),
        "level_states": [s for s in states if s["state"] != "none"],
        "swing_structure": swing,
        "components": {k: asdict(v) for k, v in components.items()},
    }
    return ind, components, states, detail


def strong_breakdown(per_tf: dict[Timeframe, dict[str, score.Component]], all_states: dict[Timeframe, list[dict]]) -> str | None:
    for tf in (Timeframe.D1, Timeframe.H4):
        mom = per_tf.get(tf, {}).get("momentum")
        for s in all_states.get(tf, []):
            if s["state"] in ("confirmed_break", "retest") and s["direction"] == "down" and mom and mom.value is not None and mom.value <= STRONG_DOWN_MOMENTUM:
                return f"{tf.value} close broke below {s['price']:.2f} ({s['level_id']}); {tf.value} momentum {mom.value:+.0f}."
    return None


def _macro_series(session: Session, series_id: str) -> pd.Series | None:
    rows = session.execute(
        select(MacroObservationRow.obs_date, MacroObservationRow.value)
        .where(MacroObservationRow.source == Source.FRED.value, MacroObservationRow.series_id == series_id)
        .order_by(MacroObservationRow.obs_date.desc())
        .limit(400)
    ).all()
    if not rows:
        return None
    s = pd.Series({d: (float(v) if v is not None else np.nan) for d, v in rows}).sort_index()
    return s


def nepal_inputs(session: Session, asset: AssetDefinition, h1: pd.DataFrame) -> tuple[list[LocalMetalRateRow], list[nepal.Publication], pd.Series, pd.Series]:
    """Recent Nepal publications (newest first), world closes by bar end, and NRB USD/NPR midpoints."""
    pub_rows = session.scalars(
        select(LocalMetalRateRow)
        .where(
            LocalMetalRateRow.source == Source.FENEGOSIDA.value,
            LocalMetalRateRow.metal == asset.metal.value,
            LocalMetalRateRow.purity == asset.purity.value,
            LocalMetalRateRow.unit == MassUnit.TOLA.value,
        )
        .order_by(LocalMetalRateRow.rate_date.desc())
        .limit(40)
    ).all()
    publications = [nepal.Publication(r.rate_date, r.published_at, float(r.price_npr)) for r in pub_rows]
    xau_by_end = pd.Series(h1["close"].to_numpy(), index=h1.index + Timeframe.H1.duration) if len(h1) else pd.Series(dtype=float)
    fx_rows = session.execute(
        select(FxRateRow.rate_date, FxRateRow.buy, FxRateRow.sell)
        .where(FxRateRow.source == Source.NRB.value, FxRateRow.currency == "USD")
        .order_by(FxRateRow.rate_date.desc())
        .limit(120)
    ).all()
    fx_mid = pd.Series({pd.Timestamp(d): (float(b) + float(s)) / 2 for d, b, s in fx_rows}).sort_index()
    return list(pub_rows), publications, xau_by_end, fx_mid


def nepal_lag(publications: list[nepal.Publication], xau_by_end: pd.Series, fx_mid: pd.Series, price_now: float | None) -> nepal.NepalLag:
    if len(fx_mid):
        return nepal.analyse(publications, xau_by_end, fx_mid, price_now)
    return nepal.analyse([], xau_by_end, pd.Series([1.0]), None)


def build(session: Session, now: datetime | None = None, asset: AssetDefinition = GOLD) -> AnalysisSnapshotRow:
    if asset.analysis_profile != "nepal_metal":
        raise ValueError("No purchase policy configured for this analysis profile")
    now = now or datetime.now(UTC)
    datasets = {d.dataset: d for d in health.all_sources(session, now, asset)}
    bars = {tf: _candles(session, tf, asset=asset) for tf in BARS_LOADED}
    price_now, price_source, price_flags = _current_price(session, bars[Timeframe.M15], now, asset)
    watch_levels = [float(x) for x in _setting(session, asset.watch_key, asset.watch_levels)]

    per_tf: dict[Timeframe, dict[str, score.Component]] = {}
    tf_detail: dict[str, dict] = {}
    all_states: dict[Timeframe, list[dict]] = {}
    ind_by_tf: dict[Timeframe, pd.DataFrame] = {}
    for tf, df in bars.items():
        if df.empty:
            continue
        ind, per_tf[tf], all_states[tf], tf_detail[tf.value] = timeframe_state(df, tf, now, price_now, watch_levels)
        ind_by_tf[tf] = ind

    components = score.aggregate_technical(per_tf)
    components["macro"] = score.macro(_macro_series(session, "DFII10"), _macro_series(session, "DGS2"), None)

    next_event = session.scalars(
        select(EconomicEventRow)
        .where(EconomicEventRow.importance == "major", EconomicEventRow.scheduled_at > now - timedelta(hours=1))
        .order_by(EconomicEventRow.scheduled_at)
        .limit(1)
    ).first()
    hours_to_event = (next_event.scheduled_at - now).total_seconds() / 3600 if next_event else None
    # Soonest announcement of any kind (FOMC, or US CPI / jobs / PCE). Shown to the owner; only
    # "major" (FOMC) events force WAIT.
    next_announcement = session.scalars(
        select(EconomicEventRow)
        .where(EconomicEventRow.importance.in_(("major", "high")), EconomicEventRow.scheduled_at > now - timedelta(hours=1))
        .order_by(EconomicEventRow.scheduled_at)
        .limit(1)
    ).first()
    hours_to_announcement = (next_announcement.scheduled_at - now).total_seconds() / 3600 if next_announcement else None
    next_release = next_announcement if next_announcement is not None and next_announcement.importance == "high" else None
    components["event_risk"] = score.event_risk(score.base_direction(components), hours_to_event)
    deterministic, coverage = score.combine(components)

    strong = strong_breakdown(per_tf, all_states)

    h4_ok, h4_detail = h4_stabilization(ind_by_tf[Timeframe.H4]) if Timeframe.H4 in ind_by_tf else (None, "no 4h bars")

    pub_rows, publications, xau_by_end, fx_mid = nepal_inputs(session, asset, bars[Timeframe.H1])
    h1 = bars[Timeframe.H1]
    lag = nepal_lag(publications, xau_by_end, fx_mid, price_now)

    # Nepal's expected next price. Hourly volatility from the last ~5 days of completed 1h bars.
    hourly_vol = nepal.hourly_volatility(h1["close"])
    nepal_next = nepal.forecast_next(lag, now, hourly_vol, asset.calendar.is_open, asset.nepal_price_step)

    # Nepal-equivalent rupees per tola for one US$/oz of world price, using the usual premium.
    rupee_factor = (
        float(fx_mid.iloc[-1]) * nepal.OUNCES_PER_TOLA * (1 + lag.premium_mean)
        if len(fx_mid) and lag.premium_mean is not None
        else None
    )
    full_d1 = bars[Timeframe.D1] if bars[Timeframe.D1].empty else _candles(session, Timeframe.D1, limit=4000, asset=asset)
    forecasts = forecast.forecast(indicators.compute(full_d1, Timeframe.D1), price_now, rupee_factor, asset.label) if len(full_d1) else []
    technical_detail = {
        tf.value: technical.signals(ind_by_tf[tf], rupee_factor, asset.label)
        for tf in (Timeframe.H1, Timeframe.H4, Timeframe.D1, Timeframe.W1)
        if tf in ind_by_tf
    }
    price_levels = {
        "fibonacci": technical.fibonacci(ind_by_tf[Timeframe.D1]) if Timeframe.D1 in ind_by_tf else None,
        "pivots": technical.pivots(ind_by_tf[Timeframe.D1]) if Timeframe.D1 in ind_by_tf else None,
    }

    plan = session.get(PurchasePlanRow, asset.id)
    waiting_days = (now - plan.waiting_since).total_seconds() / 86400 if plan and plan.waiting_since and not plan.completed_at else None

    nepal_health = datasets[asset.local_dataset]
    result = rules.decide(
        rules.DecisionInputs(
            essential_issues=_essential_issues(datasets, price_source, pub_rows[0].quality_flags if pub_rows else [], asset, price_flags),
            lag=lag,
            hours_to_next_major_event=hours_to_event,
            next_event_title=next_event.title if next_event else None,
            strong_breakdown=strong,
            h4_stabilized=h4_ok,
            h4_detail=h4_detail,
            score=deterministic,
            outlook=score.outlook(deterministic),
            coverage=coverage,
            waiting_days=waiting_days,
            asset=asset,
            next_price=nepal_next.estimate if nepal_next else None,
            next_price_change_pct=nepal_next.change_pct if nepal_next else None,
            next_release_title=next_release.title if next_release else None,
            hours_to_next_release=hours_to_announcement if next_release else None,
            nepal_quiet_since=nepal_health.latest_observation if nepal_health.freshness.status is FreshnessStatus.NOT_PUBLISHED else None,
        )
    )
    answers = _concrete_answers(
        session, asset, now, result, plan, publications, bars[Timeframe.D1], price_now, rupee_factor, tf_detail,
        score.outlook(deterministic), paused_breakdown=bool(strong and h4_ok),
    )

    # The waiting clock starts with the first non-BUY advice and only an owner action resets it.
    if result.decision is not Decision.BUY:
        if plan is None:
            session.add(PurchasePlanRow(asset_id=asset.id, waiting_since=now))
        elif plan.waiting_since is None and plan.completed_at is None:
            plan.waiting_since = now

    snapshot_id = str(uuid.uuid4())
    payload = jsonable(
        {
            "asset": asset.public(),
            "created_at": now,
            "decision": result.as_dict(),
            "prices": {
                "world_usd_now": price_now,
                "world_usd_source": price_source,
                "nepal_latest": lag.latest,
                "usd_npr_mid": float(fx_mid.iloc[-1]) if len(fx_mid) else None,
                "reference_per_tola_now": lag.reference_now,
                "changes": _changes(bars[Timeframe.D1], price_now),
                "nepal_history": [{"date": p.rate_date, "price": p.price} for p in reversed(publications[:30])],
                "nepal_next": nepal_next,
            },
            "nepal_lag": lag,
            "score": {
                "deterministic": deterministic,
                "ai_adjusted": None,
                "ai_status": "not configured",
                "outlook": score.outlook(deterministic),
                "coverage": coverage,
                "weights": score.COMPONENT_WEIGHTS,
                "timeframe_weights": {tf.value: w for tf, w in score.TIMEFRAME_WEIGHTS.items()},
                "components": {k: asdict(v) for k, v in components.items()},
            },
            "timeframes": tf_detail,
            "technical": technical_detail,
            "price_levels": price_levels,
            "forecasts": forecasts,
            "rupees_per_usd_oz": rupee_factor,
            "next_event": {
                "title": next_announcement.title,
                "scheduled_at": next_announcement.scheduled_at,
                "hours_away": hours_to_announcement,
                "forces_wait": next_announcement.importance == "major",
            }
            if next_announcement
            else None,
            "sources": [asdict(d) for d in datasets.values()],
            "watch_levels": watch_levels,
            **answers,
            "trade_plan": _trade_plan(
                session, asset, now, bars[Timeframe.D1], tf_detail.get(Timeframe.D1.value), rupee_factor,
                publications[0].price if publications else None,
            ),
            "versions": VERSIONS,
        }
    )
    row = AnalysisSnapshotRow(
        id=snapshot_id,
        asset_id=asset.id,
        created_at=now,
        versions=VERSIONS,
        decision=result.decision.value,
        deterministic_score=Decimal(str(deterministic)) if deterministic is not None else None,
        payload=payload,
    )
    session.add(row)
    return row


def _concrete_answers(
    session: Session,
    asset: AssetDefinition,
    now: datetime,
    result: rules.DecisionResult,
    plan: PurchasePlanRow | None,
    publications: list[nepal.Publication],
    d1: pd.DataFrame,
    price_now: float | None,
    rupee_factor: float | None,
    tf_detail: dict[str, dict],
    outlook,
    paused_breakdown: bool,
) -> dict:
    """The Today screen's concrete facts: where the price stands, rupee floors and ceilings, the
    two-part purchase (which may rewrite the BUY headline), and upcoming US announcements."""
    pos = position.position(asset.label, [(p.rate_date, p.price) for p in reversed(publications)], d1, price_now, now)
    keys = position.key_levels(
        {tf: detail.get("levels", []) for tf, detail in tf_detail.items()},
        {tf: detail.get("level_states", []) for tf, detail in tf_detail.items()},
        price_now,
        rupee_factor,
        asset.level_rupee_step,
    )
    events = session.execute(
        select(EconomicEventRow.event_type, EconomicEventRow.title, EconomicEventRow.scheduled_at, EconomicEventRow.importance)
        .where(
            EconomicEventRow.importance.in_(("major", "high")),
            EconomicEventRow.scheduled_at > now,
            EconomicEventRow.scheduled_at <= now + announcements.HORIZON,
        )
        .order_by(EconomicEventRow.scheduled_at)
    ).all()
    stale = announcements.calendar_stale({job: health.collector_health(session, job).last_success_at for job in announcements.CALENDAR_JOBS}, now)

    pending_second = plan is not None and plan.first_part_at is not None and plan.completed_at is None
    split_plan = None
    reason = None if pending_second else split.applies(result.decision, outlook, paused_breakdown)
    if reason:
        split_plan = split.plan(
            reason,
            [k.rupees for k in keys if k.kind == "floor" and k.rupees is not None],
            [k.rupees for k in keys if k.kind == "ceiling" and k.rupees is not None],
            publications[0].price if publications else None,
            now,
            [(at, title) for _, title, at, _ in events],
        )
        result.headline = "Buy half now"
        result.summary = (
            f"Other signs point to buying, but {reason[0].lower()}{reason[1:]} "
            "Buy half now and keep the rest for the second half, using one of the triggers below."
        )
        result.what_would_change = " ".join(split.triggers_plain(split_plan.dip_npr, split_plan.recovery_npr, split_plan.deadline))
    second = None
    if pending_second:
        second = split.second_half(
            plan.first_part_at,
            float(plan.first_part_price) if plan.first_part_price is not None else None,
            float(plan.second_dip_npr) if plan.second_dip_npr is not None else None,
            float(plan.second_recovery_npr) if plan.second_recovery_npr is not None else None,
            plan.second_deadline,
            publications[0].price if publications else None,
            now,
        )
    return {
        "position": pos,
        "key_levels": keys,
        "split": split_plan,
        "second_half": second,
        "announcements": {
            "calendar_stale": stale,
            "items": [] if stale else announcements.upcoming([tuple(e) for e in events], now),
        },
    }


def trade_book(session: Session, asset: AssetDefinition) -> trading.Book:
    from gold_advisor.persistence.models import TradeRow

    rows = session.scalars(select(TradeRow).where(TradeRow.asset_id == asset.id)).all()
    return trading.book([trading.Trade(r.side, float(r.quantity_tola), float(r.price_npr), r.traded_at) for r in rows])


def trade_holding(session: Session, asset: AssetDefinition, held: trading.Book, rupee_factor: float | None) -> trading.Holding | None:
    """The open position as the rule sees it: the world price at the first buy and the daily low
    made before it (the cut-loss level)."""
    if held.quantity_tola <= 0 or held.first_buy_at is None:
        return None
    entry = session.scalar(
        select(CandleRow.close)
        .where(CandleRow.source == asset.candle_source.value, CandleRow.instrument == asset.instrument,
               CandleRow.timeframe == Timeframe.H1.value, CandleRow.bucket_start <= held.first_buy_at - Timeframe.H1.duration)
        .order_by(CandleRow.bucket_start.desc()).limit(1)
    )
    lows = session.scalars(
        select(CandleRow.low)
        .where(CandleRow.source == asset.candle_source.value, CandleRow.instrument == asset.instrument,
               CandleRow.timeframe == Timeframe.D1.value, CandleRow.bucket_start <= held.first_buy_at - Timeframe.D1.duration)
        .order_by(CandleRow.bucket_start.desc()).limit(trading.SELLOFF_LOOKBACK_BARS)
    ).all()
    if entry is None and rupee_factor:
        entry = held.cost_npr / held.quantity_tola / rupee_factor
    return trading.Holding(min(held.parts, 2), held.quantity_tola, held.cost_npr, float(entry or 0.0),
                           float(min(lows)) if lows else None)


def trade_settings(session: Session, asset: AssetDefinition) -> tuple[float, float | None]:
    """Budget in rupees and the buy-back gap as a fraction (None until the owner enters it)."""
    stored = _setting(session, f"trade:{asset.id}", {}) or {}
    gap = stored.get("gap_pct")
    return float(stored.get("budget") or trading.DEFAULT_BUDGET), (float(gap) / 100 if gap is not None else None)


def _trade_plan(
    session: Session,
    asset: AssetDefinition,
    now: datetime,
    d1: pd.DataFrame,
    d1_detail: dict | None,
    rupee_factor: float | None,
    nepal_price: float | None,
) -> dict | None:
    """The Trade screen's plan for a tradable asset (trading.py), from completed daily bars and the
    owner's recorded trades. None for other assets. ``facts`` are kept so the API can re-plan at once
    when the owner records a trade."""
    if not asset.tradable or d1_detail is None:
        return None
    completed = d1[d1.index + Timeframe.D1.duration <= now]
    facts = trading.market_facts(completed, d1_detail.get("level_states", []), d1_detail.get("levels", []))
    budget, gap = trade_settings(session, asset)
    held = trade_book(session, asset)
    plan = trading.plan(facts, trade_holding(session, asset, held, rupee_factor))
    return {
        "version": trading.VERSION,
        "approved": trading.APPROVED,
        "state": plan.state,
        "plain": plan.plain,
        "facts": facts,
        **trading.money(plan, nepal_price, rupee_factor, asset.level_rupee_step, budget, gap, held),
    }


def _changes(d1: pd.DataFrame, price_now: float | None) -> dict[str, float | None]:
    if d1.empty:
        return {}
    ref = price_now if price_now is not None else float(d1["close"].iloc[-1])
    closes = d1["close"]
    out = {}
    for label, days in (("1D", 1), ("7D", 7), ("30D", 30)):
        cutoff = d1.index[-1] - pd.Timedelta(days=days - 1)
        past = closes[closes.index <= cutoff]
        out[label] = (ref / float(past.iloc[-1]) - 1) if len(past) else None
    return out
