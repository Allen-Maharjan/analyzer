"""Repository behaviour against real PostgreSQL/TimescaleDB.

Run with: GA_TEST_DATABASE_URL=postgresql+psycopg://... pytest -m integration
The target database is wiped and migrated; never point this at production.
"""

import os
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError

from gold_advisor.collectors.types import Candle, FxRate, LocalMetalRate, SpotQuote
from gold_advisor.domain import Instrument, MassUnit, Metal, PriceSide, Purity, Source, Timeframe
from gold_advisor.persistence import repository
from gold_advisor.persistence.models import CandleRow, LocalMetalRateRow, ObservationRevisionRow

URL = os.environ.get("GA_TEST_DATABASE_URL")
pytestmark = [pytest.mark.integration, pytest.mark.skipif(not URL, reason="GA_TEST_DATABASE_URL not set")]
BACKEND = os.path.dirname(os.path.dirname(__file__))


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    cfg = Config(os.path.join(BACKEND, "alembic.ini"))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")  # rollback path works
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with engine.connect() as conn:
        trans = conn.begin()
        with Session(bind=conn) as s:
            yield s
        trans.rollback()


def nepal_rate(price="274300", published_at=None) -> LocalMetalRate:
    return LocalMetalRate(
        source=Source.FENEGOSIDA,
        metal=Metal.GOLD,
        purity=Purity.HALLMARK,
        unit=MassUnit.TOLA,
        rate_date=date(2026, 11, 2),
        published_at=published_at,
        price_npr=Decimal(price),
        source_label="छापावाल सुन (१ तोला)",
    )


def candle(close="4005") -> Candle:
    return Candle(
        source=Source.DUKASCOPY,
        instrument=Instrument.XAUUSD,
        timeframe=Timeframe.H1,
        bucket_start=datetime(2026, 11, 2, 4, tzinfo=UTC),
        open=Decimal("4000"),
        high=Decimal("4010"),
        low=Decimal("3990"),
        close=Decimal(close),
        volume=None,
        price_side=PriceSide.BID,
    )


def test_hypertables_exist(session):
    names = set(session.scalars(text("SELECT hypertable_name FROM timescaledb_information.hypertables")))
    assert names == {"candles", "spot_quotes"}


def test_local_rate_is_idempotent_and_revisions_keep_history(session):
    published = datetime(2026, 11, 2, 4, 55, tzinfo=UTC)
    first = repository.save_local_rates(session, [nepal_rate(published_at=published)])
    again = repository.save_local_rates(session, [nepal_rate(published_at=published)])
    assert (first.inserted, again.unchanged) == (1, 1)

    # Date-only history must not erase the known publication time.
    date_only = repository.save_local_rates(session, [nepal_rate(published_at=None)])
    assert date_only.unchanged == 1

    corrected = repository.save_local_rates(session, [nepal_rate(price="274500", published_at=None)])
    assert corrected.revised == 1
    row = session.scalars(select(LocalMetalRateRow)).one()
    assert (row.price_npr, row.revision, row.published_at) == (Decimal("274500.00"), 1, published)
    revision = session.scalars(select(ObservationRevisionRow)).one()
    assert revision.previous["price_npr"] == "274300.00"
    assert revision.current["price_npr"] == "274500.00"


def test_candle_upsert_counts_and_revision(session):
    assert repository.save_candles(session, [candle()]).inserted == 1
    assert repository.save_candles(session, [candle()]).unchanged == 1
    assert repository.save_candles(session, [candle(close="4006")]).revised == 1
    row = session.scalars(select(CandleRow)).one()
    assert (row.close, row.revision, row.volume) == (Decimal("4006.0000"), 1, None)


def test_duplicate_candles_in_one_batch_do_not_fail(session):
    assert repository.save_candles(session, [candle(), candle(close="4001")]).inserted == 1


def test_inconsistent_candle_rejected_by_constraint(session):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        repository.save_candles(session, [replace(candle(), high=Decimal("3995"))])


def test_spot_quote_insert_only(session):
    quote = SpotQuote(Source.GOLD_API, Instrument.XAUUSD, datetime(2026, 11, 2, 5, 20, 22, tzinfo=UTC), Decimal("3907.199951"))
    assert repository.save_spot_quote(session, quote).inserted == 1
    assert repository.save_spot_quote(session, quote).unchanged == 1


def test_fx_rate_revision(session):
    rate = FxRate(Source.NRB, "USD", date(2026, 11, 2), 1, Decimal("151.63"), Decimal("152.23"), None, None)
    repository.save_fx_rates(session, [rate])
    result = repository.save_fx_rates(session, [replace(rate, sell=Decimal("152.30"))])
    assert result.revised == 1
    assert session.scalar(select(func.count()).select_from(ObservationRevisionRow)) == 1


def test_api_reports_unavailable_on_empty_database(engine):
    from fastapi.testclient import TestClient

    from gold_advisor.api import app

    client = TestClient(app)
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    sources = client.get("/api/v1/sources").json()
    assert {s["dataset"] for s in sources} >= {"xauusd_spot", "nepal_gold_hallmark_tola", "usd_npr", "fred_DGS10"}
    assert all(s["freshness"]["status"] == "unavailable" for s in sources)
    assert all(s["collector"]["status"] == "never_run" for s in sources)
    assert client.get("/api/v1/quotes/latest").status_code == 404
    fx = client.get("/api/v1/fx-rates", params={"currency": "usd"})
    assert fx.status_code == 422


def test_multi_asset_reads_plans_settings_and_snapshots(session):
    from fastapi.testclient import TestClient
    from gold_advisor.api import app, get_session
    from gold_advisor import analysis
    from gold_advisor.assets import ASSETS, GOLD
    from gold_advisor.persistence import market_data
    from gold_advisor.persistence.models import PurchasePlanRow
    silver = ASSETS['silver']
    now = datetime(2026, 11, 2, 5, 21, tzinfo=UTC)
    repository.save_candles(session, [candle(), replace(candle(), instrument=silver.instrument, close=Decimal('4001'))])
    for asset, price in [(GOLD, '3900'), (silver, '49')]:
        repository.save_spot_quote(session, SpotQuote(Source.GOLD_API, asset.instrument, now, Decimal(price)))
    assert market_data.latest_quote(session, silver, (Source.GOLD_API,)).price == 49
    assert market_data.candles(session, market_data.MarketQuery(silver, Timeframe.H1))[0].instrument == 'XAG/USD'
    gold_snap = analysis.build(session, now, GOLD)
    session.flush()
    silver_snap = analysis.build(session, now, silver)
    session.flush()
    assert gold_snap.payload['prices']['world_usd_now'] == 3900
    assert silver_snap.payload['prices']['world_usd_now'] == 49
    assert silver_snap.payload['watch_levels'] == []
    assert session.get(PurchasePlanRow, 'gold').waiting_since == now
    assert session.get(PurchasePlanRow, 'silver').waiting_since == now
    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        assert client.get('/api/v1/dashboard').json()['snapshot_id'] == gold_snap.id
        assert client.get('/api/v1/dashboard?asset=silver').json()['snapshot_id'] == silver_snap.id
        assert client.get(f'/api/v1/snapshots/{gold_snap.id}?asset=silver').status_code == 404
        assert 'xau_usd_now' not in client.get(f'/api/v1/snapshots/{silver_snap.id}?asset=silver').json()['prices']
        client.post('/api/v1/plan/purchased?asset=silver')
        assert client.get('/api/v1/plan?asset=silver').json()['completed_at']
        assert client.get('/api/v1/plan').json()['completed_at'] is None
        client.put('/api/v1/settings/watch-levels?asset=silver', json={'levels': [45, 50]})
        assert client.get('/api/v1/settings/watch-levels').json()['levels'] == [4000]
        assert client.get('/api/v1/settings/watch-levels?asset=silver').json()['levels'] == [45, 50]
    finally:
        app.dependency_overrides.clear()


def test_nepse_adapter_daily_prices_use_generic_repository(session):
    from gold_advisor.assets import GOLD, MarketCalendar
    from gold_advisor.persistence.market_data import MarketQuery, candles
    # A lightweight adapter emits canonical observations; it has no metal or FX dependency.
    equity = replace(GOLD, id='nepse:NABIL', instrument='NEPSE:NABIL', quote_currency='NPR', price_unit='share',
                     metal=None, purity=None, analysis_profile='equity', timeframes=(Timeframe.D1,),
                     calendar=MarketCalendar(lambda at: True, lambda at: at))
    observation = replace(candle(), instrument=equity.instrument, timeframe=Timeframe.D1)
    repository.save_candles(session, [observation])
    rows = candles(session, MarketQuery(equity, Timeframe.D1))
    assert len(rows) == 1 and rows[0].close == observation.close


def test_ai_results_and_open_jobs_are_asset_scoped(session):
    from gold_advisor import analysis
    from gold_advisor.ai import service
    from gold_advisor.assets import ASSETS, GOLD
    now = datetime(2026, 11, 2, 5, 21, tzinfo=UTC)
    for asset in (GOLD, ASSETS['silver']):
        analysis.build(session, now, asset)
        session.flush()
        job = service.enqueue(session, 'manual', now, asset)
        assert job.asset_id == asset.id
        assert job.input['asset']['id'] == asset.id
        assert service.latest(session, asset)['latest_run']['id'] == job.id
        assert service.enqueue(session, 'manual', now, asset) is None


def test_populated_legacy_migration(engine):
    """Use a separate schema lifecycle in the disposable test database only."""
    cfg = Config(os.path.join(BACKEND, 'alembic.ini'))
    command.downgrade(cfg, '0003_ai')
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO purchase_plan (id, waiting_since) VALUES (1, '2026-01-01T00:00:00Z')"))
        conn.execute(text("INSERT INTO app_settings (key, value) VALUES ('watch_levels', '{\"value\":[4100]}')"))
        conn.execute(text("INSERT INTO analysis_snapshots (id, created_at, versions, decision, payload) VALUES ('legacy', now(), '{}', 'WAIT', CAST(:payload AS jsonb))"), {"payload": '{"prices":{"xau_usd_now":4100}}'})
    command.upgrade(cfg, 'head')
    with engine.begin() as conn:
        assert conn.execute(text("SELECT asset_id FROM analysis_snapshots WHERE id='legacy'")).scalar_one() == 'gold'
        assert conn.execute(text("SELECT asset_id FROM purchase_plan")).scalar_one() == 'gold'
        assert conn.execute(text("SELECT value FROM app_settings WHERE key='watch_levels:gold'")).scalar_one()['value'] == [4100]
        with pytest.raises(DBAPIError):
            with conn.begin_nested():
                conn.execute(text("UPDATE analysis_snapshots SET decision='BUY' WHERE id='legacy'"))
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO purchase_plan (asset_id) VALUES ('silver')"))
    with pytest.raises(DBAPIError):
        command.downgrade(cfg, '0003_ai')
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM purchase_plan WHERE asset_id='silver'"))
    command.downgrade(cfg, '0003_ai')
    command.upgrade(cfg, 'head')
    # Preserve evidence, and leave the disposable database clean for any later tests.


def test_recorded_decisions_are_bounded_and_asset_scoped(session):
    from datetime import timedelta
    from gold_advisor.assets import GOLD, ASSETS
    from gold_advisor.persistence.market_data import recorded_decisions
    from gold_advisor.persistence.models import AnalysisSnapshotRow

    now = datetime(2099, 11, 2, tzinfo=UTC)
    for ident, asset, stamp in [('old', 'gold', now - timedelta(days=2)), ('gold', 'gold', now), ('silver', 'silver', now)]:
        session.add(AnalysisSnapshotRow(id=ident, asset_id=asset, created_at=stamp, versions={}, decision='WAIT', payload={}))
    session.flush()
    assert [r.id for r in recorded_decisions(session, GOLD, now - timedelta(days=1))] == ['gold']
    assert [r.id for r in recorded_decisions(session, ASSETS['silver'], now - timedelta(days=3))] == ['silver']
    with pytest.raises(ValueError):
        recorded_decisions(session, GOLD, now, limit=0)
