from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from gold_advisor.assets import ASSETS, GOLD, get_asset
from gold_advisor.collectors import gold_api, dukascopy
from gold_advisor.collectors.types import SourceSchemaError
from gold_advisor.domain import Decision, Timeframe
from gold_advisor.persistence.market_data import MarketQuery
from gold_advisor.decision.rules import decide
from test_decision_rules import inputs, lag

SILVER = ASSETS['silver']
NOW = datetime(2026, 11, 2, 5, 21, tzinfo=UTC)


def test_registry_validation_and_catalog():
    from gold_advisor.api import app
    client = TestClient(app)
    assert {a['id'] for a in client.get('/api/v1/assets').json()} == {'gold', 'silver'}
    assert client.get('/api/v1/candles?asset=unknown&timeframe=1D').status_code == 422
    with pytest.raises(ValueError):
        get_asset('XAU/USD; DROP TABLE candles')


@respx.mock
def test_silver_request_and_symbol_validation(fixture_json):
    payload = {**fixture_json('gold_api_xau.json'), 'symbol': 'XAG', 'price': 49.25}
    request = respx.get('https://api.gold-api.com/price/XAG').mock(return_value=httpx.Response(200, json=payload))
    with httpx.Client() as client:
        quote = gold_api.fetch(client, now=NOW, asset=SILVER)
    assert request.called
    assert quote.instrument == 'XAG/USD' and quote.price == Decimal('49.25')
    with pytest.raises(SourceSchemaError):
        gold_api.parse(payload, now=NOW, asset=GOLD)


def test_silver_candles_keep_identity():
    rows = dukascopy.parse('[{"timestamp":1793592000000,"open":49,"high":51,"low":48,"close":50}]', Timeframe.H1, now=NOW, asset=SILVER)
    assert rows and {r.instrument for r in rows} == {'XAG/USD'}


@pytest.mark.parametrize('asset,expected', [(GOLD, Decision.BUY), (SILVER, Decision.WATCH_CLOSELY)])
def test_fixed_rupee_trigger_only_applies_to_gold(asset, expected):
    result = decide(inputs(asset=asset, lag=lag(nepal_change_3_publications=-3001, nepal_change_3_publications_pct=-0.005), h4_stabilized=True))
    assert result.decision == expected
    assert '{inp' not in str(result.as_dict())
    assert asset.label.lower() in str(result.as_dict()).lower()


def test_silver_percentage_buy_and_international_wait():
    result = decide(inputs(asset=SILVER, lag=lag(nepal_change_3_publications=-50, nepal_change_3_publications_pct=-0.01), h4_stabilized=True))
    assert result.decision == Decision.BUY
    result = decide(inputs(asset=SILVER, lag=lag(intl_change_since_publication_pct=-0.02)))
    assert result.decision == Decision.WAIT
    assert 'XAG/USD' in str(result.as_dict())
    assert 'gold' not in str(result.as_dict()).lower()


def test_query_bounds_and_timeframe_capabilities():
    with pytest.raises(ValueError):
        MarketQuery(SILVER, Timeframe.H1, limit=5001)
    equity = replace(GOLD, id='nepse:NABIL', instrument='NEPSE:NABIL', quote_currency='NPR', price_unit='share', metal=None, purity=None, analysis_profile='equity', timeframes=(Timeframe.D1,))
    with pytest.raises(ValueError):
        MarketQuery(equity, Timeframe.H4)
    assert MarketQuery(equity, Timeframe.D1).asset.quote_currency == 'NPR'


def test_ai_validates_small_currency_amounts():
    from gold_advisor.ai import contract
    inp = {'asset': SILVER.public(), 'facts': [{'id': 'price', 'value': 49.25, 'unit': 'USD/oz'}], 'levels': []}
    out = {'plain_summary': 'Silver is $49.25.', 'outlook': 'neutral', 'adjustment': 0, 'adjustment_reason': 'Unchanged.', 'reasons': [{'text': 'Price is available.', 'evidence_ids': ['price']}] * 2, 'risks': [], 'watch_levels': []}
    assert contract.validate(inp, out)['ok']
    assert not contract.validate(inp, {**out, 'plain_summary': 'Silver is $55.50.'})['ok']
    assert 'buy silver' in contract.prompt(inp)


def test_spot_failure_uses_same_asset_backup(monkeypatch):
    from gold_advisor import jobs
    calls = []
    def attempt(source, fetch, asset):
        calls.append((source, asset))
        if len(calls) == 1:
            raise httpx.ConnectError('offline')
        return 'backup'
    monkeypatch.setattr(jobs, '_spot_job', attempt)
    assert jobs.collect_gold_spot(SILVER) == 'backup'
    assert all(asset is SILVER for _, asset in calls)
