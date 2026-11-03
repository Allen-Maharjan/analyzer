"""News jobs and owner-confirmed risks against real PostgreSQL.

Run with: GA_TEST_DATABASE_URL=postgresql+psycopg://... pytest -m integration
The target database is wiped and migrated; never point this at production.
"""

import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text

from gold_advisor.assets import ASSETS
from gold_advisor.collectors import freenews
from gold_advisor.collectors.types import CollectionResult, LocalMetalRate
from gold_advisor.domain import MassUnit, Metal, Purity, Source

URL = os.environ.get("GA_TEST_DATABASE_URL")
pytestmark = [pytest.mark.integration, pytest.mark.skipif(not URL, reason="GA_TEST_DATABASE_URL not set")]
BACKEND = os.path.dirname(os.path.dirname(__file__))
TODAY = date(2026, 11, 3)
NOW = datetime(2026, 11, 3, 5, 0, tzinfo=UTC)
GOLD, SILVER = ASSETS["gold"], ASSETS["silver"]


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    from gold_advisor.persistence import db

    # Match Neon (no TimescaleDB): its background worker breaks on repeated schema resets.
    # monkeypatch restores it, so other integration modules still get their hypertables.
    monkeypatch.setenv("GA_SKIP_TIMESCALE", "1")
    db.get_engine().dispose()  # pooled app connections would point at the dropped tables
    eng = create_engine(URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public; DROP EXTENSION IF EXISTS timescaledb CASCADE"))
    command.upgrade(Config(os.path.join(BACKEND, "alembic.ini")), "head")
    eng.dispose()
    yield


def rate(metal: Metal, price: str, day: date = TODAY) -> LocalMetalRate:
    purity = Purity.HALLMARK if metal is Metal.GOLD else Purity.PURE_SILVER
    return LocalMetalRate(Source.FENEGOSIDA, metal, purity, MassUnit.TOLA, day, NOW, Decimal(price), "label")


@pytest.fixture
def nepal(monkeypatch):
    """Run the real collect_nepal_today with a fake FENEGOSIDA response."""
    from gold_advisor import jobs
    from gold_advisor.collectors import fenegosida

    state = {"rates": []}
    monkeypatch.setattr(fenegosida, "fetch_today", lambda client: (state["rates"], []))
    monkeypatch.setattr(jobs, "_nepal_today", lambda: TODAY)
    monkeypatch.setattr(jobs, "_now", lambda: NOW)

    def run(*rates):
        state["rates"] = list(rates)
        return jobs.collect_nepal_today(force=True)

    return run


def jobs_for(asset_id=None):
    from gold_advisor.persistence.db import session_scope
    from gold_advisor.persistence.models import NewsRefreshJobRow

    with session_scope() as s:
        q = select(NewsRefreshJobRow.asset_id, NewsRefreshJobRow.trigger).order_by(NewsRefreshJobRow.id)
        if asset_id:
            q = q.where(NewsRefreshJobRow.asset_id == asset_id)
        return [tuple(r) for r in s.execute(q)]


def test_inserted_revised_and_unchanged_prices(nepal):
    nepal(rate(Metal.GOLD, "274300"), rate(Metal.SILVER, "3720"))
    assert jobs_for() == [("gold", "price_inserted"), ("silver", "price_inserted")]
    nepal(rate(Metal.GOLD, "274300"), rate(Metal.SILVER, "3720"))  # repeated reload: nothing new
    assert len(jobs_for()) == 2
    nepal(rate(Metal.GOLD, "274500"), rate(Metal.SILVER, "3720"))  # gold corrected
    assert jobs_for("gold") == [("gold", "price_inserted"), ("gold", "price_revised")]
    assert len(jobs_for("silver")) == 1


def test_history_backfill_does_not_queue_news(monkeypatch):
    from gold_advisor import jobs
    from gold_advisor.collectors import fenegosida

    monkeypatch.setattr(fenegosida, "fetch_month", lambda client, month: ([rate(Metal.GOLD, "270000", date(2026, 10, 1))], []))
    monkeypatch.setattr(jobs.time, "sleep", lambda _: None)
    jobs.collect_nepal_history(1)
    assert jobs_for() == []


def test_job_survives_failed_write_transaction(nepal, monkeypatch):
    from gold_advisor.persistence import repository

    def boom(*a, **k):
        raise RuntimeError("database went away")

    monkeypatch.setattr(repository, "save_local_rates", boom)
    with pytest.raises(RuntimeError):
        nepal(rate(Metal.GOLD, "274300"))
    assert jobs_for() == []  # no job without the committed price


def test_process_pending_saves_articles_and_retries_failures(nepal, monkeypatch):
    from gold_advisor import news_service
    from gold_advisor.persistence.db import session_scope

    nepal(rate(Metal.GOLD, "274300"), rate(Metal.SILVER, "3720"))
    article = freenews.Article("abcd1234-0000", "Gold slips", "Reuters", NOW - timedelta(hours=1), "https://r.com/a", "Excerpt", "en")
    calls = []

    def fake_refresh(client, asset, *, now):
        calls.append(asset.id)
        if asset.id == "silver":
            raise freenews.NewsUnavailable("HTTP 500")
        return freenews.RefreshResult([article], requests_used=6)

    monkeypatch.setattr(freenews, "refresh", fake_refresh)
    monkeypatch.setattr(freenews, "make_news_client", lambda key: _Dummy())
    news_service.process_pending(session_scope, "key", lambda: NOW)
    assert calls == ["gold", "silver"]  # each job ran once
    with session_scope() as s:
        assert news_service.status(s, GOLD, NOW)["state"] == "fresh"
        assert news_service.status(s, SILVER, NOW)["state"] == "unavailable"
        assert [a.title for a in news_service.recent_articles(s, GOLD)] == ["Gold slips"]
        assert news_service.recent_articles(s, SILVER) == []
    # A later cycle (after RETRY_AFTER) retries the failed silver job.
    later = NOW + news_service.RETRY_AFTER + timedelta(minutes=1)
    news_service.process_pending(session_scope, "key", lambda: later)
    assert calls == ["gold", "silver", "silver"]


class _Dummy:
    def __enter__(self):
        return object()

    def __exit__(self, *exc):
        return False


def test_risk_confirm_expiry_clear_and_isolation():
    from gold_advisor import news_service
    from gold_advisor.persistence.db import session_scope

    fresh = freenews.Article("fresh0000-01", "War fears", "Reuters", NOW - timedelta(hours=2), "https://r.com/w", "", "en")
    old = freenews.Article("old000000-01", "Old story", "Reuters", NOW - timedelta(hours=30), "https://r.com/o", "", "en")
    with session_scope() as s:
        news_service.save_articles(s, GOLD, [fresh, old], NOW)
    with session_scope() as s:
        with pytest.raises(news_service.RiskRejected):
            news_service.confirm_risk(s, GOLD, old.provider_id, "too old", NOW)
        with pytest.raises(news_service.RiskRejected):
            news_service.confirm_risk(s, SILVER, fresh.provider_id, "wrong asset", NOW)
        row = news_service.confirm_risk(s, GOLD, fresh.provider_id, "  War   risk  ", NOW)
        assert row.reason == "War risk" and row.expires_at == fresh.published_at + timedelta(hours=24)
    with session_scope() as s:
        assert news_service.active_risk(s, GOLD, NOW).article.title == "War fears"
        assert news_service.active_risk(s, SILVER, NOW) is None
        assert news_service.active_risk(s, GOLD, row.expires_at + timedelta(seconds=1)) is None  # expired
        assert news_service.clear_risk(s, GOLD, NOW) == 1
    with session_scope() as s:
        assert news_service.active_risk(s, GOLD, NOW) is None
