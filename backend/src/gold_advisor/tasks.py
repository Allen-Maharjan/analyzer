"""Celery app, beat schedule, and lock-guarded task wrappers.

Run exactly one beat process. Each task holds a Redis lock so a slow run is never
overlapped by the next scheduled one.
"""

import logging
from collections.abc import Callable
from functools import lru_cache, wraps

import redis
from celery import Celery
from celery.schedules import crontab

from gold_advisor import jobs
from gold_advisor.assets import ASSETS, get_asset
from gold_advisor.config import get_settings
from gold_advisor.domain import Timeframe

log = logging.getLogger(__name__)

app = Celery("gold_advisor", broker=get_settings().redis_url)
app.conf.update(
    timezone="Asia/Kathmandu",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
)


@lru_cache
def _redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url)


def locked(name: str, ttl_seconds: int) -> Callable:
    """Skip the run if another worker holds the lock for this job."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            lock = _redis().lock(f"gold_advisor:lock:{name}", timeout=ttl_seconds, blocking=False)
            if not lock.acquire():
                log.info("skipping %s: previous run still in progress", name)
                return None
            try:
                fn(*args, **kwargs)
            finally:
                try:
                    lock.release()
                except redis.exceptions.LockError:
                    log.warning("lock for %s expired before release", name)

        return wrapper

    return decorator


# Collection failures are recorded in collection_runs and surface in /sources;
# the next scheduled run is the retry, so tasks do not re-raise into Celery retries.
def _quiet(fn: Callable[[], object]) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001 - already logged and recorded by run_job
        pass


@app.task(name="collect.gold_spot")
@locked("gold_spot", ttl_seconds=55)
def collect_gold_spot() -> None:
    for asset in ASSETS.values():
        _quiet(lambda: jobs.collect_gold_spot(asset))


@app.task(name="collect.nepal_today")
@locked("nepal_today", ttl_seconds=600)
def collect_nepal_today(force: bool = False) -> None:
    _quiet(lambda: jobs.collect_nepal_today(force=force))
    process_news.delay()
    run_analysis.delay()


@app.task(name="collect.nepal_history")
@locked("nepal_history", ttl_seconds=3600)
def collect_nepal_history(months: int | None = None) -> None:
    _quiet(lambda: jobs.collect_nepal_history(months))


@app.task(name="collect.fx")
@locked("fx", ttl_seconds=1800)
def collect_fx(force: bool = False) -> None:
    _quiet(lambda: jobs.collect_fx(force=force))
    run_analysis.delay()


@app.task(name="collect.macro")
@locked("macro", ttl_seconds=1800)
def collect_macro() -> None:
    _quiet(jobs.collect_macro)


@app.task(name="news.process")
@locked("news", ttl_seconds=600)
def process_news() -> None:
    from datetime import datetime

    from gold_advisor import news_service
    from gold_advisor.domain import UTC
    from gold_advisor.persistence.db import session_scope

    _quiet(lambda: news_service.process_pending(session_scope, get_settings().freenewsapi_key, lambda: datetime.now(UTC)))


@app.task(name="collect.events")
@locked("events", ttl_seconds=900)
def collect_events() -> None:
    _quiet(jobs.collect_events)


@app.task(name="analysis.run")
@locked("analysis", ttl_seconds=300)
def run_analysis() -> None:
    for asset in ASSETS.values():
        _quiet(lambda: jobs.run_analysis(asset))


@app.task(name="ai.schedule")
@locked("ai_schedule", ttl_seconds=120)
def schedule_ai() -> None:
    from gold_advisor.ai import service
    from gold_advisor.persistence.db import session_scope

    with session_scope() as session:
        for asset in ASSETS.values():
            log.info("ai schedule %s: %s", asset.id, service.maybe_schedule(session, asset=asset))


@app.task(name="collect.candles")
def collect_candles(timeframe: str, asset_id: str = "gold") -> None:
    tf = Timeframe(timeframe)
    for asset in (get_asset(asset_id),):
        locked(f"candles_{asset.id}_{tf.value}", ttl_seconds=3 * 3600)(lambda: _quiet(lambda: jobs.collect_candles(tf, asset)))()


app.conf.beat_schedule = {
    "gold-spot-every-60s": {"task": "collect.gold_spot", "schedule": 60.0},
    # Nepal gold and NRB dollar rates change once a day. These runs only call the source
    # until today's rate is stored, then skip. The refresh endpoint forces a call.
    "nepal-daily-window": {"task": "collect.nepal_today", "schedule": crontab(minute="0,30", hour="10-14")},
    "nepal-history-daily": {"task": "collect.nepal_history", "schedule": crontab(minute=30, hour=15), "args": (2,)},
    "nrb-daily-window": {"task": "collect.fx", "schedule": crontab(minute=15, hour="0,3,6,9,12,15,18")},
    "fred-every-6h": {"task": "collect.macro", "schedule": crontab(minute=20, hour="*/6")},
    "candles-15m": {"task": "collect.candles", "schedule": crontab(minute="2,17,32,47"), "args": ("15m",)},
    "candles-1h": {"task": "collect.candles", "schedule": crontab(minute=10), "args": ("1h",)},
    "fomc-every-6h": {"task": "collect.events", "schedule": crontab(minute=25, hour="*/6")},
    "analysis-every-15m": {"task": "analysis.run", "schedule": crontab(minute="5,20,35,50")},
    "ai-check-every-15m": {"task": "ai.schedule", "schedule": crontab(minute="8,23,38,53")},
    "candles-1d": {"task": "collect.candles", "schedule": crontab(minute=40, hour="*/6"), "args": ("1D",)},
}


@app.task(name="collect.spot")
def collect_spot(asset_id: str) -> None:
    asset = get_asset(asset_id)
    locked(f"spot_{asset.id}", ttl_seconds=55)(lambda: _quiet(lambda: jobs.collect_gold_spot(asset)))()

app.conf.beat_schedule.pop("gold-spot-every-60s")
for key in ("candles-15m", "candles-1h", "candles-1d"):
    entry = app.conf.beat_schedule.pop(key)
    for asset in ASSETS.values():
        app.conf.beat_schedule[f"{key}-{asset.id}"] = {**entry, "args": (*entry["args"], asset.id)}
for asset in ASSETS.values():
    app.conf.beat_schedule[f"spot-{asset.id}"] = {"task": "collect.spot", "schedule": 60.0, "args": (asset.id,)}
