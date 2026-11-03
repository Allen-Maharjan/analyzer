"""BUY / WAIT / WATCH CLOSELY rules and their plain-language explanation.

Rules apply in strict precedence (first match wins):
1. WATCH CLOSELY when essential data is stale, missing, inconsistent, or insufficient.
2. WAIT when a major event is within 24 h, world gold fell more than 2% since Nepal's last
   publication, or a confirmed breakdown still has strong downside momentum.
3. BUY when Nepal fell at least Rs 3,000/tola or 1% across the latest three publications,
   the expected Nepal adjustment has cleared, and two completed 4-hour candles show no new
   selloff low with improving RSI or MACD.
4. WATCH CLOSELY otherwise.

Every result carries plain text for a non-trader and separate technical detail.
"""

from dataclasses import asdict, dataclass, field

from gold_advisor.assets import AssetDefinition, GOLD
from gold_advisor.decision.nepal import NepalLag
from gold_advisor.domain import Confidence, Decision, Outlook

VERSION = "rules-1"
WAIT_EVENT_HOURS = 24
WAIT_INTL_DECLINE = -0.02
BUY_DROP_RUPEES = -3000
BUY_DROP_PCT = -0.01
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


def _lag_reason(lag: NepalLag) -> Reason | None:
    if lag.expected_adjustment_pct is None:
        return None
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

    def result(decision, rule, headline, summary, next_review, change) -> DecisionResult:
        for r in (_nepal_reason(lag, inp.asset), _lag_reason(lag), _market_reason(inp)):
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
    if inp.strong_breakdown:
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

    # 3. Conditions to buy.
    dropped = lag.nepal_change_3_publications is not None and (
        (inp.asset.buy_drop_rupees is not None and lag.nepal_change_3_publications <= inp.asset.buy_drop_rupees) or (lag.nepal_change_3_publications_pct or 0) <= inp.asset.buy_drop_pct
    )
    if dropped and lag.adjustment_pending is False and inp.h4_stabilized:
        reasons.append(Reason("World prices have stopped falling for now.", inp.h4_detail))
        return result(
            Decision.BUY,
            "local_adjustment_and_stabilization",
            "Good time to buy",
            "Nepal's price has come down, has caught up with world prices, and the fall has paused.",
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
        "Nepal's price dropping and holding steady would point to buying; a big fall in world prices would point to waiting.",
    )
