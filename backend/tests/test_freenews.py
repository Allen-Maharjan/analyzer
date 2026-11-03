from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from gold_advisor.ai import contract
from gold_advisor.assets import ASSETS
from gold_advisor.collectors import freenews
from gold_advisor.collectors.types import SourceSchemaError
from gold_advisor.decision import news_risk

NOW = datetime(2026, 11, 3, 5, 0, tzinfo=UTC)
GOLD, SILVER = ASSETS["gold"], ASSETS["silver"]


def cand(uuid, title, hours_ago=1, publisher="Reuters"):
    return freenews.Candidate(uuid, title, publisher, NOW - timedelta(hours=hours_ago))


def details(uuid="5fcd6996-9941-4433-9579-a8a5b7a8585e", **overrides):
    data = {
        "uuid": uuid, "title": "Gold slips as dollar firms", "publisher": "Reuters",
        "published_at": "2026-11-03T02:04:33.000Z", "original_url": "https://www.reuters.com/markets/gold-1",
        "incipit": "Gold prices eased on Tuesday as the dollar strengthened.", "languages": ["en"], "body": "FULL TEXT",
    }
    return {"data": {**data, **overrides}}


class TestParsing:
    def test_live_search_fixture(self, fixture_json):
        items = freenews.parse_search(fixture_json("freenews_search_silver.json"))
        assert len(items) == 10
        assert all(i.published_at.tzinfo is not None for i in items)

    def test_live_details_fixture_keeps_excerpt_not_body(self, fixture_json):
        article = freenews.parse_details(fixture_json("freenews_details.json"))
        assert article.url.startswith("https://")
        assert article.excerpt and len(article.excerpt) <= freenews.MAX_EXCERPT
        assert not hasattr(article, "body")

    @pytest.mark.parametrize("url", ["http://x.com/a", "https://user:pw@x.com/a", "https://x.com:8443/a", "javascript:alert(1)", None])
    def test_unsafe_links_rejected(self, url):
        assert freenews.parse_details(details(original_url=url)) is None

    def test_bad_date_rejected(self):
        assert freenews.parse_details(details(published_at="yesterday")) is None

    @pytest.mark.parametrize("payload", [{"message": "error"}, {"data": "x"}, [], None])
    def test_malformed_responses(self, payload):
        with pytest.raises(SourceSchemaError):
            freenews.parse_search(payload)


class TestSelection:
    def test_keeps_only_relevant_recent_unique(self):
        picked = freenews.select(
            [
                cand("a1111111", "Gold price climbs on rate bets"),
                cand("a1111111", "Gold price climbs on rate bets"),  # same id
                cand("b2222222", "Gold Price Climbs on Rate Bets!", publisher="FXStreet"),  # near-identical title
                cand("c3333333", "Oil rallies"),  # not about gold
                cand("d4444444", "Gold bullion demand rises", hours_ago=72),  # too old
                cand("e5555555", "Silver price jumps"),  # wrong metal
            ],
            GOLD, NOW,
        )
        assert [c.provider_id for c in picked] == ["a1111111"]

    def test_caps_articles_per_publisher(self):
        titles = ["Gold price rises on Fed bets", "Central banks keep buying gold", "Gold bullion vaults fill in London",
                  "Why gold miners are rallying", "Indian gold imports fall sharply"]
        many = [cand(f"{i:08d}", t, hours_ago=i / 10) for i, t in enumerate(titles)]
        assert len(freenews.select(many, GOLD, NOW)) == freenews.MAX_PER_PUBLISHER

    def test_assets_use_their_own_terms(self):
        assert "silver price" in SILVER.news_terms and "gold price" not in SILVER.news_terms


def _search(*titles):
    return {"data": [{"uuid": f"{i:08d}-aaaa", "title": t, "publisher": f"P{i}", "published_at": "2026-11-03T04:00:00Z"} for i, t in enumerate(titles)]}


class TestRefresh:
    @respx.mock
    def test_paced_within_budget_and_drops_non_english(self):
        respx.get(f"{freenews.BASE_URL}/news").mock(return_value=httpx.Response(200, json=_search("Gold price up", "Gold bullion falls")))
        respx.get(f"{freenews.BASE_URL}/details").mock(
            side_effect=[httpx.Response(200, json=details(uuid="00000000-aaaa")), httpx.Response(200, json=details(uuid="00000001-aaaa", languages=["te"]))]
        )
        sleeps, clock = [], iter(range(1000))
        with httpx.Client() as client:
            result = freenews.refresh(client, GOLD, now=NOW, sleep=sleeps.append, clock=lambda: next(clock) * 0.1)
        assert result.requests_used == len(GOLD.news_terms) + len(freenews.SHARED_TERMS) + 2
        assert result.requests_used <= freenews.REQUEST_BUDGET
        assert all(s <= freenews.MIN_INTERVAL for s in sleeps) and sleeps  # pacing happened
        assert [a.language for a in result.articles] == ["en"]

    @respx.mock
    def test_429_and_500_are_retried_then_recorded_as_partial(self):
        respx.get(f"{freenews.BASE_URL}/news").mock(
            side_effect=[httpx.Response(429), httpx.Response(200, json=_search("Gold price up"))] + [httpx.Response(500)] * 20
        )
        respx.get(f"{freenews.BASE_URL}/details").mock(return_value=httpx.Response(200, json=details(uuid="00000000-aaaa")))
        with httpx.Client() as client:
            result = freenews.refresh(client, GOLD, now=NOW, sleep=lambda _: None)
        assert len(result.articles) == 1
        assert any("HTTP 500" in f for f in result.failures)

    @respx.mock
    def test_all_searches_failing_is_unavailable_not_empty(self):
        respx.get(f"{freenews.BASE_URL}/news").mock(return_value=httpx.Response(500))
        with httpx.Client() as client, pytest.raises(freenews.NewsUnavailable):
            freenews.refresh(client, GOLD, now=NOW, sleep=lambda _: None)

    def test_missing_key(self):
        with pytest.raises(freenews.NewsUnavailable):
            freenews.make_news_client("  ")

    @respx.mock
    def test_key_only_in_header(self):
        route = respx.get(f"{freenews.BASE_URL}/news").mock(return_value=httpx.Response(200, json={"data": []}))
        with freenews.make_news_client("secret-key") as client:
            freenews.refresh(client, GOLD, now=NOW, sleep=lambda _: None)
        req = route.calls[0].request
        assert req.headers["x-api-key"] == "secret-key" and "secret-key" not in str(req.url)


class TestRiskRule:
    risk = news_risk.Risk("War headline", NOW + timedelta(hours=5), "Gold slips", "Reuters", "https://r.com/a")

    def test_buy_becomes_wait(self):
        shown, override = news_risk.apply({"decision": "BUY", "headline": "Good time to buy"}, self.risk, NOW)
        assert shown["decision"] == "WAIT" and override["original_decision"] == "BUY"

    @pytest.mark.parametrize("decision", ["WAIT", "WATCH CLOSELY"])
    def test_other_decisions_unchanged(self, decision):
        shown, override = news_risk.apply({"decision": decision}, self.risk, NOW)
        assert shown["decision"] == decision and override is None

    def test_expired_risk_has_no_effect(self):
        shown, override = news_risk.apply({"decision": "BUY"}, self.risk, NOW + timedelta(hours=6))
        assert shown["decision"] == "BUY" and override is None


class TestAiNews:
    inp = {
        "asset": GOLD.public(),
        "facts": [{"id": "price", "value": 3928.9, "unit": "USD/oz"}],
        "levels": [],
        "news": [{"id": "news-abc12345", "title": "Gold near $3,950 on deal hopes", "publisher": "FXStreet", "excerpt": ""}],
    }
    base = {
        "plain_summary": "Gold is $3,928.90.", "outlook": "neutral", "adjustment": 0, "adjustment_reason": "None.",
        "reasons": [{"text": "Price known.", "evidence_ids": ["price"]}] * 2, "risks": [], "watch_levels": [],
    }

    def check(self, **news):
        return contract.validate(self.inp, {**self.base, **news})

    def test_valid_citation(self):
        assert self.check(news_summary="Reports say gold holds near $3,950.", news_citations=["news-abc12345"])["ok"]

    def test_unknown_citation_rejected(self):
        assert not self.check(news_summary="Reports say gold rose.", news_citations=["news-fake0000"])["ok"]

    def test_summary_without_citation_rejected(self):
        assert not self.check(news_summary="Reports say gold rose.", news_citations=[])["ok"]

    def test_headline_number_not_allowed_in_main_summary(self):
        assert not contract.validate(self.inp, {**self.base, "plain_summary": "Gold is $3,950.", "news_summary": "", "news_citations": []})["ok"]

    def test_prompt_marks_news_untrusted(self):
        assert "untrusted" in contract.prompt(self.inp) and "news-abc12345" in contract.prompt(self.inp)
