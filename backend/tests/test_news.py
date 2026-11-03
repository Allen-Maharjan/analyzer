from datetime import datetime, timezone

import httpx
import pytest
import respx

from gold_advisor.assets import ASSETS
from gold_advisor.collectors import news
from gold_advisor.collectors.types import SourceSchemaError

NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def item(**kwargs):
    return {'title': 'Gold prices change', 'url': 'https://www.reuters.com/markets/gold',
            'seendate': '20261102T110000Z', **kwargs}


def test_parse_rejects_bad_sources_future_and_duplicates():
    trusted = item(url='https://reuters.com/markets/gold')
    rows = [trusted, trusted, item(url='https://reuters.com.evil.example/a'),
            item(url='http://reuters.com/a'), item(url='https://reuters.com/b', seendate='20261103T110000Z')]
    assert [a.url for a in news.parse({'articles': rows}, now=NOW)] == [trusted['url']]
    with pytest.raises(SourceSchemaError):
        news.parse({'message': 'limit exceeded'}, now=NOW)


@respx.mock
def test_fetch_uses_asset_query_and_propagates_failure():
    route = respx.get(news.URL).mock(return_value=httpx.Response(200, json={'articles': []}))
    with httpx.Client() as client:
        assert news.fetch(client, ASSETS['silver'], now=NOW) == []
    assert 'silver' in route.calls[0].request.url.params['query']


def test_search_failure_is_not_an_empty_success(monkeypatch):
    request = httpx.Request("GET", news.URL)
    response = httpx.Response(429, request=request)
    def fail(*args, **kwargs):
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)
    monkeypatch.setattr(news, "get_with_retries", fail)
    with httpx.Client() as client, pytest.raises(httpx.HTTPStatusError):
        news.fetch(client, ASSETS["gold"], now=NOW)
