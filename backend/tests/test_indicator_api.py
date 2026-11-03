from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import math

from fastapi.testclient import TestClient

from gold_advisor import api
from gold_advisor.api import app, get_session


def fake_rows(n: int):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(n):
        close = 50 + 5 * math.sin(i / 9) + i * 0.01
        rows.append(SimpleNamespace(bucket_start=start + timedelta(days=i), open=close - 0.2, high=close + 0.5, low=close - 0.6, close=close))
    return rows


def test_indicators_cover_exactly_the_requested_bars_with_warmup(monkeypatch):
    requested = {}

    def candles(session, query):
        requested["limit"] = query.limit
        return fake_rows(query.limit)

    monkeypatch.setattr(api.market_data, "candles", candles)
    app.dependency_overrides[get_session] = lambda: None
    try:
        body = TestClient(app).get("/api/v1/indicators", params={"asset": "silver", "timeframe": "1D", "limit": 50}).json()
    finally:
        app.dependency_overrides.clear()
    assert requested["limit"] == 50 + api.INDICATOR_WARMUP_BARS
    assert body["instrument"] == "XAG/USD" and len(body["points"]) == 50
    first = body["points"][0]["values"]
    assert first["sma_200"] is not None, "warmup bars make the 200-bar average available from the first bar shown"
    assert 0 <= first["rsi_14"] <= 100
    assert set(first) == set(api.INDICATOR_FIELDS)


def test_indicators_empty_history(monkeypatch):
    monkeypatch.setattr(api.market_data, "candles", lambda session, query: [])
    app.dependency_overrides[get_session] = lambda: None
    try:
        body = TestClient(app).get("/api/v1/indicators", params={"timeframe": "1h"}).json()
    finally:
        app.dependency_overrides.clear()
    assert body["points"] == []
