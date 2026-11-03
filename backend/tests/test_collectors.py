from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import respx

from gold_advisor.collectors import dukascopy, fenegosida, fred, gold_api, nrb, swissquote
from gold_advisor.collectors.http import get_with_retries
from gold_advisor.collectors.types import SourceSchemaError
from gold_advisor.domain import NEPAL_TZ, MassUnit, Metal, Purity, QualityFlag, Timeframe

NOW = datetime(2026, 11, 2, 5, 21, tzinfo=UTC)


class TestGoldApi:
    def test_parses_live_fixture(self, fixture_json):
        quote = gold_api.parse(fixture_json("gold_api_xau.json"), now=NOW)
        assert quote.price == Decimal("3907.199951")
        assert quote.observed_at == datetime(2026, 11, 2, 5, 20, 22, tzinfo=UTC)
        assert quote.quality_flags == ()

    def test_future_timestamp_is_flagged(self, fixture_json):
        quote = gold_api.parse(fixture_json("gold_api_xau.json"), now=NOW - timedelta(minutes=10))
        assert quote.quality_flags == (QualityFlag.CLOCK_SKEW,)

    @pytest.mark.parametrize("patch", [{"price": 0}, {"symbol": "XAG"}, {"updatedAt": "2026-11-02T05:20:22"}])
    def test_rejects_invalid_payload(self, fixture_json, patch):
        with pytest.raises(SourceSchemaError):
            gold_api.parse({**fixture_json("gold_api_xau.json"), **patch}, now=NOW)


class TestFenegosida:
    def test_today_yields_today_and_yesterday(self, fixture_json):
        rates, notes = fenegosida.parse_today(fixture_json("fenegosida_today.json"))
        assert notes == []
        tola = {r.rate_date: r for r in rates if (r.metal, r.purity, r.unit) == fenegosida.REQUIRED_TODAY}
        assert tola[date(2026, 11, 2)].price_npr == Decimal("274300.00")
        assert tola[date(2026, 11, 1)].price_npr == Decimal("272000.00")
        assert tola[date(2026, 11, 2)].published_at.astimezone(NEPAL_TZ).hour == 10
        assert all(not r.quality_flags for r in rates)

    def test_partial_today_retains_other_rates(self, fixture_json):
        rows = [r for r in fixture_json("fenegosida_today.json") if r["rateType"] != "छापावाल सुन (१ तोला)"]
        rates, _ = fenegosida.parse_today(rows)
        assert any(rate.metal is Metal.SILVER for rate in rates)
        assert not any((r.metal, r.purity, r.unit) == fenegosida.REQUIRED_TODAY for r in rates)

    def test_unknown_label_is_skipped_and_noted(self, fixture_json):
        rows = fixture_json("fenegosida_today.json") + [{**fixture_json("fenegosida_today.json")[0], "rateType": "नयाँ"}]
        _, notes = fenegosida.parse_today(rows)
        assert notes == ["unknown rateType skipped: 'नयाँ'"]

    def test_month_history_is_date_only(self, fixture_json):
        rates, _ = fenegosida.parse_history(fixture_json("fenegosida_month_2026-10.json"))
        assert len(rates) == 88
        assert all(r.published_at is None for r in rates)
        assert {r.metal for r in rates} == {Metal.GOLD, Metal.SILVER}

    def test_empty_day_returns_nothing(self):
        assert fenegosida.parse_history("") == ([], [])

    def test_unit_mismatch_flags_both_rows(self, fixture_json):
        rows = fixture_json("fenegosida_today.json")
        rows[0] = {**rows[0], "todayBaseRatePerGram": 200000}  # 10 g gold no longer matches tola
        rates, _ = fenegosida.parse_today(rows)
        flagged = {(r.unit, r.rate_date) for r in rates if r.quality_flags}
        assert flagged == {(MassUnit.TEN_GRAM, date(2026, 11, 2)), (MassUnit.TOLA, date(2026, 11, 2))}
        assert all(r.purity is Purity.HALLMARK for r in rates if r.quality_flags)


class TestNrb:
    def test_parses_usd_only_with_nepal_timestamps(self, fixture_json):
        rates, pages = nrb.parse(fixture_json("nrb_rates.json"))
        assert pages == 1
        assert {r.currency for r in rates} == {"USD"}
        by_date = {r.rate_date: r for r in rates}
        assert by_date[date(2026, 10, 31)].buy == Decimal("151.63")
        assert by_date[date(2026, 10, 31)].sell == Decimal("152.23")
        assert by_date[date(2026, 10, 31)].published_at.utcoffset() == timedelta(hours=5, minutes=45)

    def test_rejects_unexpected_shape(self):
        with pytest.raises(SourceSchemaError):
            nrb.parse({"data": {}})


class TestFred:
    def test_parses_and_preserves_gaps(self, fixture_text):
        obs = fred.parse("DGS10", fixture_text("fred_dgs10.csv"))
        by_date = {o.obs_date: o.value for o in obs}
        assert by_date[date(2026, 10, 1)] == Decimal("5.24")
        assert by_date[date(2026, 10, 12)] is None  # US holiday: empty value, not carried forward

    def test_dot_means_missing(self):
        assert fred.parse("DGS2", "observation_date,DGS2\n2026-10-01,.\n")[0].value is None

    def test_header_must_match_series(self):
        with pytest.raises(SourceSchemaError):
            fred.parse("DGS2", "observation_date,DGS10\n")


class TestDukascopy:
    ROW = '{{"timestamp":{ts},"open":4000,"high":4010,"low":3990,"close":4005,"volume":1.5}}'

    def _ms(self, dt):
        return int(dt.timestamp() * 1000)

    def test_drops_bar_still_in_progress(self):
        now = datetime(2026, 10, 30, 12, 30, tzinfo=UTC)
        done, open_ = datetime(2026, 10, 30, 11, tzinfo=UTC), datetime(2026, 10, 30, 12, tzinfo=UTC)
        raw = f"[{self.ROW.format(ts=self._ms(done))},{self.ROW.format(ts=self._ms(open_))}]"
        bars = dukascopy.parse(raw, Timeframe.H1, now=now)
        assert [b.bucket_start for b in bars] == [done]

    def test_inconsistent_ohlc_rejected(self):
        raw = '[{"timestamp":1793232000000,"open":4000,"high":3999,"low":3990,"close":4005,"volume":1}]'
        with pytest.raises(SourceSchemaError):
            dukascopy.parse(raw, Timeframe.H1, now=NOW)


class TestRetries:
    @respx.mock
    def test_retries_5xx_then_succeeds(self):
        route = respx.get("https://example.test/x").mock(
            side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
        )
        with httpx.Client() as client:
            response = get_with_retries(client, "https://example.test/x", sleep=lambda _: None)
        assert response.json() == {"ok": True}
        assert route.call_count == 2

    @respx.mock
    def test_does_not_retry_client_errors(self):
        route = respx.get("https://example.test/x").mock(return_value=httpx.Response(404))
        with httpx.Client() as client, pytest.raises(httpx.HTTPStatusError):
            get_with_retries(client, "https://example.test/x", sleep=lambda _: None)
        assert route.call_count == 1

    @respx.mock
    def test_gives_up_after_bounded_attempts(self):
        route = respx.get("https://example.test/x").mock(side_effect=httpx.ConnectError("down"))
        with httpx.Client() as client, pytest.raises(httpx.ConnectError):
            get_with_retries(client, "https://example.test/x", attempts=3, sleep=lambda _: None)
        assert route.call_count == 3


class TestSwissquote:
    def test_parses_tightest_spread_midpoint(self, fixture_json):
        quote = swissquote.parse(fixture_json("swissquote_xau.json"), now=datetime.now(UTC))
        assert 1000 < quote.price < 10000
        assert quote.source.value == "swissquote"

    def test_rejects_empty(self):
        with pytest.raises(SourceSchemaError):
            swissquote.parse([], now=NOW)
