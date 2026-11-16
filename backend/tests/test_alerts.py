from gold_advisor import alerts
from gold_advisor.assets import ASSETS


def payload(decision="WAIT", rate_date="2026-11-15", price=270200.0, world=3880.0, state="stay_out"):
    return {
        "created_at": "2026-11-16T05:00:00+00:00",
        "decision": {"decision": decision, "headline": "Good time to buy" if decision == "BUY" else "Wait", "summary": "First. Second."},
        "prices": {"nepal_latest": {"rate_date": rate_date, "nepal_price": price}, "world_usd_now": world},
        "watch_levels": [3900.0],
        "rupees_per_usd_oz": 69.4,
        "trade_plan": {"state": state, "plain": "Stay out for now."},
    }


def test_each_change_gives_one_alert_with_a_stable_key():
    silver = ASSETS["silver"]
    old = payload()
    new = payload(decision="BUY", rate_date="2026-11-16", price=271700.0, world=3910.0, state="buy_first_half")
    found = alerts.detect(silver, "snap-2", new, old)
    assert sorted(a.kind for a in found) == ["advice", "nepal", "trade", "watch"]
    nepal = next(a for a in found if a.kind == "nepal")
    assert nepal.key == "nepal:silver:2026-11-16" and "up Rs 1,500" in nepal.body
    assert next(a for a in found if a.kind == "trade").url == "/trade?asset=silver"
    assert [a.key for a in alerts.detect(silver, "snap-2", new, old)] == [a.key for a in found]


def test_no_change_no_alert():
    assert alerts.detect(ASSETS["gold"], "snap-3", payload(), payload()) == []
