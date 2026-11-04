"""BUY / WAIT / WATCH CLOSELY rules and their plain-language explanation.

Rules apply in strict precedence (first match wins):
1. WATCH CLOSELY when essential data is stale, missing, inconsistent, or insufficient.
2. WAIT when a major event is within 24 h, world gold fell more than 2% since Nepal's last
   publication, or a confirmed breakdown still has strong downside momentum and the 4-hour
   chart has not paused (a breakdown whose fall has paused no longer forces WAIT).
3. BUY when the expected Nepal adjustment has cleared and two completed 4-hour candles show no
   new selloff low with improving RSI or MACD. If that holds but Nepal's next price is expected at
   least 0.5% lower (the next-price forecast), WAIT for it instead. BUY no longer needs Nepal's
   price to have dropped first (rules-4): a two-year replay found that requirement made the advice
   wait too long and pay about 0.5% more than buying at once.
4. WATCH CLOSELY otherwise.

Every result carries plain text for a non-trader and separate technical detail.
"""

from dataclasses import asdict, dataclass, field

from gold_advisor.assets import AssetDefinition, GOLD
from gold_advisor.decision.nepal import NepalLag
from gold_advisor.domain import Confidence, Decision, Outlook

VERSION = "rules-4"
WAIT_EVENT_HOURS = 24
WAIT_INTL_DECLINE = -0.02
REVIEW_AFTER_DAYS = 7


@dataclass(frozen=True)
class Reason:
    plain: str
    detail: str


@dataclass(frozen=True)
class DecisionInputs:
    essential_issues: list[str]
    lag: NepalLag
    hours_to_next_major_event: float | None
    next_event_title: str | None
    strong_breakdown: str | None
    h4_stabilized: bool | None
    h4_detail: str
    score: float | None
    outlook: Outlook | None
    coverage: float
    waiting_days: float | None
    asset: AssetDefinition = GOLD
    next_price: float | None = None  # Nepal's expected next price (forecast), rupees per tola
    next_price_change_pct: float | None = None  # vs the latest published price
    next_release_title: str | None = None  # next US data release (CPI, jobs, PCE): a risk, not a WAIT trigger
    hours_to_next_release: float | None = None


@dataclass
class DecisionResult:
    decision: Decision
    headline: str
    summary: str
    reasons: list[Reason]
    confidence: Confidence
    upside_risks: list[str]
    downside_risks: list[str]
    next_review: str
    what_would_change: str
    review_due: bool
    waiting_days: float | None
    rule: str
    limitations: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def rupees(value: float) -> str:
    """Nepali digit grouping: 274300 -> 'Rs 2,74,300'."""
    sign = "-" if value < 0 else ""
    n = str(int(round(abs(value))))
    head, tail = n[:-3], n[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}Rs {','.join(groups + [tail]) if groups else tail}"


def pct(value: float) -> str:
    return f"{value * 100:+.1f}%"


def _confidence(inp: DecisionInputs) -> Confidence:
    lag = inp.lag
    if inp.essential_issues or lag.premium_observations < 10:
        return Confidence.LOW
    if inp.coverage >= 0.8 and lag.premium_observations >= 20 and not lag.publication_dates_only:
        return Confidence.HIGH
    if inp.coverage >= 0.5:
        return Confidence.MEDIUM
    return Confidence.LOW


def _market_reason(inp: DecisionInputs) -> Reason | None:
    if inp.outlook is None:
        return None
    words = {
        Outlook.BULLISH: f"World {inp.asset.label.lower()} prices are generally rising right now.",
        Outlook.BEARISH: f"World {inp.asset.label.lower()} prices are generally falling right now.",
        Outlook.NEUTRAL: f"World {inp.asset.label.lower()} prices are not moving clearly up or down.",
    }[inp.outlook]
    return Reason(words, f"Deterministic score {inp.score:+.1f} ({inp.outlook.value}); data coverage {inp.coverage:.0%}.")


def _nepal_reason(lag: NepalLag, asset: AssetDefinition) -> Reason | None:
    if lag.nepal_change_3_publications is None or lag.latest is None:
        return None
    change = lag.nepal_change_3_publications
    if change < 0:
        plain = f"Nepal's {asset.label.lower()} price has dropped {rupees(-change)} per tola over the last three price updates."
    elif change > 0:
        plain = f"Nepal's {asset.label.lower()} price has risen {rupees(change)} per tola over the last three price updates."
    else:
        plain = f"Nepal's {asset.label.lower()} price is unchanged over the last three price updates."
    return Reason(plain, f"Latest {lag.latest.rate_date}: {rupees(lag.latest.nepal_price)}; change {pct(lag.nepal_change_3_publications_pct or 0)}.")


def _lag_reason(lag: NepalLag, inp: "DecisionInputs | None" = None) -> Reason | None:
    if lag.expected_adjustment_pct is None:
        return None
    if inp is not None and inp.next_price is not None and inp.next_price_change_pct is not None and lag.adjustment_pending:
        # Say the size of the move with the next-price forecast, the more accurate estimate.
        change = inp.next_price - lag.latest.nepal_price
        if abs(change) >= 1:
            direction = "fall" if change < 0 else "rise"
            return Reason(
                f"Based on world prices, Nepal's price may {direction} by about {rupees(abs(change))} per tola at the next update.",
                f"Next-price forecast {rupees(inp.next_price)} ({pct(inp.next_price_change_pct)}); gap vs usual: adjustment {pct(lag.expected_adjustment_pct)}.",
            )
    adj = lag.expected_adjustment_pct
    detail = (
        f"Implied Nepal price {rupees(lag.implied_nepal_now or 0)} vs published {rupees(lag.latest.nepal_price)} "
        f"({pct(adj)}); premium mean {pct(lag.premium_mean or 0)}, sd {pct(lag.premium_std or 0)}, n={lag.premium_observations}."
    )
    if not lag.adjustment_pending:
        return Reason("Nepal's price has already caught up with world prices.", detail)
    direction = "fall" if adj < 0 else "rise"
    return Reason(
        f"Based on world prices, Nepal's price may {direction} by about {rupees(abs(adj) * lag.latest.nepal_price)} "
        "per tola at the next update.",
        detail,
    )


def decide(inp: DecisionInputs) -> DecisionResult:
    lag = inp.lag
    reasons: list[Reason] = []
    limitations = []
    if inp.hours_to_next_major_event is None:
        limitations.append("The US economic calendar is not available, so upcoming announcements may be missed.")
    if lag.publication_dates_only:
        limitations.append("Nepal's latest price has a date but no exact time; comparisons assume about 10:45 am.")

    upside = [f"{inp.asset.label} could rebound quickly after a fall, so waiting can also cost money."]
    downside = [f"World {inp.asset.label.lower()} could keep falling, and Nepal's price usually follows within a day or two."]
    if inp.next_event_title and inp.hours_to_next_major_event is not None and inp.hours_to_next_major_event < 24 * 7:
        downside.append(f"{inp.next_event_title} in about {inp.hours_to_next_major_event:.0f} hours can move prices sharply either way.")
    if inp.next_release_title and inp.hours_to_next_release is not None and 0 <= inp.hours_to_next_release < 48:
        downside.append(f"The {inp.next_release_title} in about {inp.hours_to_next_release:.0f} hours can move prices sharply either way.")

    def result(decision, rule, headline, summary, next_review, change) -> DecisionResult:
        for r in (_nepal_reason(lag, inp.asset), _lag_reason(lag, inp), _market_reason(inp)):
            if r is not None and len(reasons) < 5 and r not in reasons:
                reasons.append(r)
        review_due = bool(inp.waiting_days is not None and inp.waiting_days >= REVIEW_AFTER_DAYS and decision is not Decision.BUY)
        if review_due:
            summary += (
                f" You have been waiting {inp.waiting_days:.0f} days. Only wait longer if the reasons above still apply today."
            )
        return DecisionResult(
            decision=decision,
            headline=headline,
            summary=summary,
            reasons=reasons[:5],
            confidence=Confidence.LOW if decision is Decision.WATCH_CLOSELY and rule == "data" else _confidence(inp),
            upside_risks=upside,
            downside_risks=downside,
            next_review=next_review,
            what_would_change=change,
            review_due=review_due,
            waiting_days=inp.waiting_days,
            rule=rule,
            limitations=limitations,
        )

    # 1. Data problems.
    if inp.essential_issues or lag.premium_observations < 10:
        for issue in inp.essential_issues[:3]:
            reasons.append(Reason(issue, "Essential input stale, missing, or inconsistent."))
        if lag.premium_observations < 10:
            reasons.append(
                Reason(
                    "There isn't enough price history yet to compare Nepal with world prices.",
                    f"{lag.premium_observations} aligned publications; 10 required.",
                )
            )
        return result(
            Decision.WATCH_CLOSELY,
            "data",
            "Hold off: some prices are out of date",
            "The app can't give a reliable answer until fresh prices arrive. Don't decide based on old numbers.",
            "As soon as the missing prices are collected.",
            "Fresh Nepal, world, and dollar prices.",
        )

    # 2. Reasons to wait.
    if inp.hours_to_next_major_event is not None and inp.hours_to_next_major_event <= WAIT_EVENT_HOURS:
        reasons.append(
            Reason(
                f"A major US announcement ({inp.next_event_title}) is due within a day. Prices often jump around it.",
                f"Next major event in {inp.hours_to_next_major_event:.1f} h; event-safety factor 0.",
            )
        )
        return result(
            Decision.WAIT,
            "event_within_24h",
            "Wait: a big announcement is coming",
            "Prices can swing sharply around this announcement. It's safer to decide after it.",
            "About an hour after the announcement.",
            "Once the announcement has passed and prices settle, this will be checked again.",
        )
    if lag.intl_change_since_publication_pct is not None and lag.intl_change_since_publication_pct <= inp.asset.wait_decline_pct:
        reasons.append(
            Reason(
                f"World {inp.asset.label.lower()} has fallen {abs(lag.intl_change_since_publication_pct) * 100:.1f}% since Nepal last set its price. "
                "Nepal's price will probably come down at the next update.",
                f"{inp.asset.instrument} {pct(lag.intl_change_since_publication_pct)} since publication at {lag.latest.at.isoformat()}.",
            )
        )
        return result(
            Decision.WAIT,
            "intl_decline_unpublished",
            "Wait: Nepal's price will probably drop soon",
            f"World {inp.asset.label.lower()} prices fell after Nepal's last update. Buying now likely means paying more than tomorrow.",
            "After Nepal's next price update (usually around 11 am).",
            "Nepal publishing a lower price, or world prices recovering.",
        )
    if inp.strong_breakdown and not inp.h4_stabilized:
        reasons.append(
            Reason(f"World {inp.asset.label.lower()} just broke below an important price floor and is still falling hard.", inp.strong_breakdown)
        )
        return result(
            Decision.WAIT,
            "confirmed_breakdown",
            "Wait: prices are still falling",
            f"{inp.asset.label} is dropping quickly right now. Waiting a little may get a better price.",
            "After the next two 4-hour periods, or at Nepal's next price update.",
            "The fall slowing down and prices holding steady.",
        )

    if inp.strong_breakdown:
        # A recent breakdown whose fall has paused: not a reason to wait on its own, but still a risk.
        downside.append(f"World {inp.asset.label.lower()} recently broke below an important price floor; the fall has paused but could resume.")

    # 3. Conditions to buy.
    if lag.adjustment_pending is False and inp.h4_stabilized:
        limit = inp.asset.buy_block_expected_drop_pct
        if limit is not None and inp.next_price_change_pct is not None and inp.next_price_change_pct <= limit and inp.next_price is not None:
            reasons.append(
                Reason(
                    f"Nepal's next price is expected to be about {rupees(lag.latest.nepal_price - inp.next_price)} lower "
                    f"({rupees(inp.next_price)} per tola).",
                    f"Next-price forecast {pct(inp.next_price_change_pct)} vs today's published price; threshold {pct(limit)}.",
                )
            )
            return result(
                Decision.WAIT,
                "expected_lower_next",
                "Wait: tomorrow's price will probably be lower",
                "Other signs point to buying, but world prices have slipped since Nepal set today's price. Waiting for the next update should be cheaper.",
                "After Nepal's next price update (usually around 11 am).",
                "Nepal publishing the lower price, after which buying may make sense.",
            )
        reasons.append(Reason("World prices have stopped falling for now.", inp.h4_detail))
        return result(
            Decision.BUY,
            "local_adjustment_and_stabilization",
            "Good time to buy",
            "Nepal's price has caught up with world prices, world prices aren't falling, and no big announcement is close. "
            "There's no clear reason to wait.",
            "Before buying, check that today's price is still the one shown here.",
            "World prices starting to fall again, or Nepal raising its price.",
        )

    # 4. Mixed.
    if inp.h4_stabilized is False:
        reasons.append(Reason("World prices haven't settled yet.", inp.h4_detail))
    return result(
        Decision.WATCH_CLOSELY,
        "mixed",
        "Keep watching",
        "There's no strong reason to buy or to wait right now. The app will tell you when that changes.",
        "At Nepal's next price update, or if world prices move more than 1%.",
        "World prices holding steady and Nepal's price catching up with them would point to buying; a big fall in world prices would point to waiting.",
    )
