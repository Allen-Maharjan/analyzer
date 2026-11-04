from datetime import UTC, date, datetime

from gold_advisor.decision.nepal import AlignedPublication, NepalLag
from gold_advisor.decision.rules import DecisionInputs, decide, rupees
from gold_advisor.domain import Decision, Outlook


def lag(**overrides) -> NepalLag:
    latest = AlignedPublication(date(2026, 11, 2), datetime(2026, 11, 2, 5, tzinfo=UTC), True, 274300, 3900, 151.9, 222000, 0.235)
    base = dict(
        latest=latest, premium_mean=0.22, premium_std=0.006, premium_observations=20, reference_now=222000,
        implied_nepal_now=274000, expected_adjustment_pct=-0.001, adjustment_pending=False,
        intl_change_since_publication_pct=0.0, nepal_change_3_publications=0.0, nepal_change_3_publications_pct=0.0,
        publication_dates_only=False,
    )
    return NepalLag(**{**base, **overrides})


def inputs(**overrides) -> DecisionInputs:
    base = dict(
        essential_issues=[], lag=lag(), hours_to_next_major_event=200.0, next_event_title="FOMC rate decision",
        strong_breakdown=None, h4_stabilized=False, h4_detail="", score=0.0, outlook=Outlook.NEUTRAL,
        coverage=1.0, waiting_days=None,
    )
    return DecisionInputs(**{**base, **overrides})


def test_large_international_decline_with_unchanged_nepal_price_waits():
    result = decide(inputs(lag=lag(intl_change_since_publication_pct=-0.025)))
    assert result.decision is Decision.WAIT and result.rule == "intl_decline_unpublished"


def test_local_adjustment_plus_stabilization_buys():
    result = decide(inputs(lag=lag(nepal_change_3_publications=-6000, nepal_change_3_publications_pct=-0.021), h4_stabilized=True))
    assert result.decision is Decision.BUY
    assert 3 <= len(result.reasons) <= 5


def test_stale_data_beats_everything():
    result = decide(inputs(essential_issues=["Today's Nepal gold price hasn't been collected yet."], h4_stabilized=True))
    assert result.decision is Decision.WATCH_CLOSELY and result.rule == "data"


def test_event_within_24h_waits():
    assert decide(inputs(hours_to_next_major_event=10.0)).rule == "event_within_24h"


def test_conflicting_signals_watch_closely():
    result = decide(inputs(lag=lag(nepal_change_3_publications=-6000, adjustment_pending=True), h4_stabilized=True))
    assert result.decision is Decision.WATCH_CLOSELY


def test_review_due_after_seven_days():
    assert decide(inputs(waiting_days=8.0)).review_due is True


def test_rupees_use_nepali_grouping():
    assert rupees(274300) == "Rs 2,74,300"


def test_breakdown_waits_while_the_fall_continues():
    result = decide(inputs(strong_breakdown="1D close broke below 4000", h4_stabilized=False))
    assert result.decision is Decision.WAIT and result.rule == "confirmed_breakdown"


def test_breakdown_whose_fall_has_paused_no_longer_forces_wait():
    result = decide(inputs(strong_breakdown="1D close broke below 4000", h4_stabilized=True,
                           lag=lag(nepal_change_3_publications=-6000, nepal_change_3_publications_pct=-0.021)))
    assert result.decision is Decision.BUY
    assert any("broke below" in risk for risk in result.downside_risks)


def test_buy_no_longer_needs_nepal_to_have_dropped():
    unchanged = lag(nepal_change_3_publications=700, nepal_change_3_publications_pct=0.003)
    assert decide(inputs(lag=unchanged, h4_stabilized=True)).decision is Decision.BUY
    assert decide(inputs(lag=unchanged, h4_stabilized=False)).decision is Decision.WATCH_CLOSELY


def test_expected_rise_in_nepal_price_still_buys():
    rising = lag(expected_adjustment_pct=0.02, adjustment_pending=True)
    result = decide(inputs(lag=rising, h4_stabilized=True, next_price=280000, next_price_change_pct=0.02))
    assert result.decision is Decision.BUY and result.rule == "expected_higher_next"
    assert decide(inputs(lag=rising, h4_stabilized=False)).decision is Decision.WATCH_CLOSELY


def test_buy_turns_into_wait_when_tomorrow_is_expected_cheaper():
    buy_setup = dict(lag=lag(nepal_change_3_publications=-6000, nepal_change_3_publications_pct=-0.021), h4_stabilized=True)
    result = decide(inputs(**buy_setup, next_price=272000, next_price_change_pct=-0.0084))
    assert result.decision is Decision.WAIT and result.rule == "expected_lower_next"
    assert any("Rs 2,300 lower" in r.plain for r in result.reasons)
    # A small expected dip (under 0.5%) does not block buying.
    assert decide(inputs(**buy_setup, next_price=273500, next_price_change_pct=-0.0029)).decision is Decision.BUY


def test_us_data_release_is_a_risk_not_a_wait():
    result = decide(inputs(lag=lag(nepal_change_3_publications=-6000, nepal_change_3_publications_pct=-0.021), h4_stabilized=True,
                           next_release_title="US jobs report (NFP)", hours_to_next_release=6.0))
    assert result.decision is Decision.BUY
    assert any("US jobs report" in r for r in result.downside_risks)
