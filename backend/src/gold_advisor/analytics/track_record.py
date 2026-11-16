"""Track record: the app's past forecasts and advice against what Nepal really published.

Pure functions over stored rows; no database access, so it can be tested directly. Nothing is
estimated or filled in: a day without a qualifying snapshot is left out, and every summary carries
its sample size.

Forecast record, for each published Nepal price with rate date D: the last snapshot created before
the price was published (before 10:45 Nepal time on D when the time is unknown) whose latest Nepal
price is from before D and which carries an expected next price.

Advice record, for each publication day D: the advice standing at 12:00 Nepal time on D (the same
instant as ``backtest.DECISION_TIME``), as the rules said it, with no news-risk override. A snapshot
more than 24 hours older than that instant does not count as standing advice. The outcome is read
from the next 5 publications only.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from gold_advisor.analytics.decision_evaluation import Evaluation, Observation, evaluate
from gold_advisor.domain import NEPAL_TZ, UTC, Decision

ASSUMED_PUBLICATION_TIME = time(10, 45)
DECISION_TIME = time(12, 0)
OUTCOME_PUBLICATIONS = 5
STANDING_MAX_AGE = timedelta(hours=24)
SMALL_SAMPLE = 20
MINIMUM_WINDOWS = 20


@dataclass(frozen=True)
class Publication:
    rate_date: date
    published_at: datetime | None
    price: float


@dataclass(frozen=True)
class Snapshot:
    created_at: datetime
    nepal_rate_date: date | None  # prices.nepal_latest.rate_date
    next_estimate: float | None  # prices.nepal_next
    next_low: float | None
    next_high: float | None
    decision: Decision | None
    rule: str | None


@dataclass(frozen=True)
class ForecastRow:
    rate_date: date
    estimate: float
    low: float
    high: float
    actual: float
    error_npr: float  # actual minus estimate
    error_pct: float  # error / actual
    inside_range: bool
    hours_before: float
    snapshot_at: datetime


@dataclass(frozen=True)
class ForecastSummary:
    count: int
    mean_abs_error_pct: float | None
    mean_abs_error_npr: float | None
    inside_range: int
    small_sample: bool


@dataclass(frozen=True)
class AdviceRow:
    rate_date: date
    decision: str
    rule: str | None
    price: float
    advice_at: datetime
    later_count: int
    later_low: float | None
    later_high: float | None
    later_last: float | None
    open: bool  # fewer than 5 later publications so far
    outcome: str
    good: bool | None  # True: the advice worked out; False: it cost money; None: open or not judged


@dataclass(frozen=True)
class AdviceSummary:
    days: int
    status: str  # "ok" | "insufficient", from decision_evaluation.evaluate
    windows: int
    windows_needed: int
    buys: int
    mean_cost_vs_immediate: float | None


def publication_cutoff(p: Publication) -> datetime:
    if p.published_at is not None:
        return p.published_at.astimezone(UTC)
    return datetime.combine(p.rate_date, ASSUMED_PUBLICATION_TIME, tzinfo=NEPAL_TZ).astimezone(UTC)


def forecast_rows(publications: list[Publication], snapshots: list[Snapshot]) -> list[ForecastRow]:
    """Newest first. ``snapshots`` in any order."""
    ordered = sorted(snapshots, key=lambda s: s.created_at)
    rows = []
    for p in publications:
        cutoff = publication_cutoff(p)
        chosen = None
        for s in ordered:
            if s.created_at >= cutoff:
                break
            if s.next_estimate is not None and s.nepal_rate_date is not None and s.nepal_rate_date < p.rate_date:
                chosen = s
        if chosen is None:
            continue
        error = p.price - chosen.next_estimate
        low = chosen.next_low if chosen.next_low is not None else chosen.next_estimate
        high = chosen.next_high if chosen.next_high is not None else chosen.next_estimate
        rows.append(
            ForecastRow(
                rate_date=p.rate_date,
                estimate=chosen.next_estimate,
                low=low,
                high=high,
                actual=p.price,
                error_npr=error,
                error_pct=error / p.price,
                inside_range=low <= p.price <= high,
                hours_before=round((cutoff - chosen.created_at).total_seconds() / 3600, 1),
                snapshot_at=chosen.created_at,
            )
        )
    return sorted(rows, key=lambda r: r.rate_date, reverse=True)


def forecast_summary(rows: list[ForecastRow]) -> ForecastSummary:
    n = len(rows)
    return ForecastSummary(
        count=n,
        mean_abs_error_pct=sum(abs(r.error_pct) for r in rows) / n if n else None,
        mean_abs_error_npr=sum(abs(r.error_npr) for r in rows) / n if n else None,
        inside_range=sum(r.inside_range for r in rows),
        small_sample=n < SMALL_SAMPLE,
    )


def _rupees(value: float) -> str:
    from gold_advisor.decision.rules import rupees

    return rupees(value)


def _outcome(decision: Decision, price: float, later: list[float]) -> tuple[str, bool | None]:
    if len(later) < OUTCOME_PUBLICATIONS:
        return "still open", None
    low = min(later)
    if decision is Decision.WAIT:
        if low < price:
            return f"price fell {_rupees(price - low)} within 5 updates", True
        return f"price did not fall; waiting cost {_rupees(low - price)}", False
    if decision is Decision.BUY:
        if low < price:
            return f"a later price was {_rupees(price - low)} lower", False
        return "this was the lowest price of the next 5", True
    if low < price:
        return f"the lowest of the next 5 updates was {_rupees(price - low)} lower", None
    return "the next 5 updates were all at or above this price", None


def advice_rows(publications: list[Publication], snapshots: list[Snapshot]) -> list[AdviceRow]:
    """Newest first. ``publications`` in any order."""
    pubs = sorted(publications, key=lambda p: p.rate_date)
    ordered = sorted((s for s in snapshots if s.decision is not None), key=lambda s: s.created_at)
    rows = []
    for i, p in enumerate(pubs):
        instant = datetime.combine(p.rate_date, DECISION_TIME, tzinfo=NEPAL_TZ).astimezone(UTC)
        standing = None
        for s in ordered:
            if s.created_at > instant:
                break
            standing = s
        if standing is None or instant - standing.created_at > STANDING_MAX_AGE:
            continue
        later = [q.price for q in pubs[i + 1 : i + 1 + OUTCOME_PUBLICATIONS]]
        outcome, good = _outcome(standing.decision, p.price, later)
        rows.append(
            AdviceRow(
                rate_date=p.rate_date,
                decision=standing.decision.value,
                rule=standing.rule,
                price=p.price,
                advice_at=standing.created_at,
                later_count=len(later),
                later_low=min(later) if later else None,
                later_high=max(later) if later else None,
                later_last=later[-1] if later else None,
                open=len(later) < OUTCOME_PUBLICATIONS,
                outcome=outcome,
                good=good,
            )
        )
    return sorted(rows, key=lambda r: r.rate_date, reverse=True)


def advice_summary(rows: list[AdviceRow]) -> AdviceSummary:
    observations = [Observation(r.rate_date, r.price, Decision(r.decision)) for r in sorted(rows, key=lambda r: r.rate_date)]
    result: Evaluation = evaluate(observations, minimum_windows=MINIMUM_WINDOWS)
    return AdviceSummary(
        days=len(rows),
        status=result.status,
        windows=result.windows,
        windows_needed=MINIMUM_WINDOWS,
        buys=result.buys,
        mean_cost_vs_immediate=result.mean_cost_vs_immediate,
    )
