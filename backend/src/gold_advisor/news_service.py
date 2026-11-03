"""News refresh jobs, saved articles, status, and owner-confirmed news risks."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from gold_advisor.assets import ASSETS, AssetDefinition
from gold_advisor.collectors import freenews
from gold_advisor.domain import MassUnit, Source
from gold_advisor.persistence.models import LocalMetalRateRow, NewsArticleRow, NewsRefreshJobRow, NewsRiskRow

log = logging.getLogger(__name__)

SOURCE = "freenewsapi"
MAX_ATTEMPTS = 3
RUNNING_TIMEOUT = timedelta(minutes=15)
RETRY_AFTER = timedelta(minutes=20)
FRESH_FOR = timedelta(hours=24)
RISK_WINDOW = timedelta(hours=24)  # an article can be confirmed, and stays active, for 24 h after publication
MAX_REASON = 300
SHOWN_ARTICLES = 8


# --- Jobs ------------------------------------------------------------------------------


def enqueue(session: Session, asset: AssetDefinition, trigger: str, dedupe_key: str, now: datetime) -> bool:
    """Idempotent: the same (asset, dedupe_key) is only ever queued once."""
    stmt = (
        insert(NewsRefreshJobRow)
        .values(asset_id=asset.id, trigger=trigger, dedupe_key=dedupe_key[:128], status="pending", created_at=now)
        .on_conflict_do_nothing(constraint="uq_news_refresh_jobs_asset_id_dedupe_key")
        .returning(NewsRefreshJobRow.id)
    )
    return session.execute(stmt).first() is not None


# News also refreshes on a timer, so afternoon headlines appear without waiting for tomorrow's
# Nepal price. Budget: 2 assets x 8 refreshes x at most 20 requests = 320 of the 5,000 daily requests.
SCHEDULED_EVERY = timedelta(hours=3)


def enqueue_scheduled(session: Session, now: datetime, every: timedelta = SCHEDULED_EVERY) -> list[str]:
    """Queue a refresh for each asset whose newest refresh job (any trigger, any outcome) is older
    than ``every``. Idempotent within a time bucket."""
    queued = []
    bucket = int(now.timestamp() // every.total_seconds())
    for asset in ASSETS.values():
        if not asset.news_terms:
            continue
        newest = session.scalar(
            select(func.max(NewsRefreshJobRow.created_at)).where(NewsRefreshJobRow.asset_id == asset.id)
        )
        if newest is not None and now - newest < every:
            continue
        if enqueue(session, asset, "scheduled", f"scheduled:{bucket}", now):
            queued.append(asset.id)
    return queued


def today_prices(session: Session, rate_date) -> dict[str, float]:
    """Today's per-tola Nepal price for each metal asset, as stored right now."""
    out = {}
    for asset in ASSETS.values():
        if asset.metal is None:
            continue
        price = session.scalar(
            select(LocalMetalRateRow.price_npr).where(
                LocalMetalRateRow.source == Source.FENEGOSIDA.value,
                LocalMetalRateRow.metal == asset.metal.value,
                LocalMetalRateRow.purity == asset.purity.value,
                LocalMetalRateRow.unit == MassUnit.TOLA.value,
                LocalMetalRateRow.rate_date == rate_date,
            )
        )
        if price is not None:
            out[asset.id] = float(price)
    return out


def enqueue_for_price_changes(session: Session, before: dict[str, float], after: dict[str, float], rate_date, now: datetime) -> list[str]:
    """Call inside the same transaction as the price write, so the job commits with it."""
    queued = []
    for asset_id, price in after.items():
        old = before.get(asset_id)
        if old == price:
            continue
        trigger = "price_inserted" if old is None else "price_revised"
        if enqueue(session, ASSETS[asset_id], trigger, f"{rate_date}:{price:.2f}", now):
            queued.append(asset_id)
    return queued


def _claim(session: Session, now: datetime) -> NewsRefreshJobRow | None:
    return session.scalars(
        select(NewsRefreshJobRow)
        .where(
            NewsRefreshJobRow.attempts < MAX_ATTEMPTS,
            (NewsRefreshJobRow.status == "pending")
            | ((NewsRefreshJobRow.status == "running") & (NewsRefreshJobRow.started_at < now - RUNNING_TIMEOUT))
            # A failed job is retried by a later cycle, not straight away in the same one.
            | ((NewsRefreshJobRow.status == "failed") & (NewsRefreshJobRow.finished_at < now - RETRY_AFTER)),
        )
        .order_by(NewsRefreshJobRow.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()


def save_articles(session: Session, asset: AssetDefinition, articles: list[freenews.Article], now: datetime) -> int:
    for a in articles:
        values = dict(
            asset_id=asset.id, source=SOURCE, provider_id=a.provider_id, title=a.title, publisher=a.publisher,
            published_at=a.published_at, url=a.url, excerpt=a.excerpt, language=a.language, retrieved_at=now,
        )
        stmt = insert(NewsArticleRow).values(**values)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["asset_id", "source", "provider_id"],
                set_={k: stmt.excluded[k] for k in ("title", "publisher", "published_at", "url", "excerpt", "language", "retrieved_at")},
            )
        )
    return len(articles)


def process_pending(session_scope, key: str, now_fn) -> list[str]:
    """Run every claimable job, one transaction per claim and per result. Returns log lines."""
    lines = []
    with freenews.make_news_client(key) if key.strip() else _no_client() as client:
        while True:
            with session_scope() as session:
                job = _claim(session, now_fn())
                if job is None:
                    break
                job.status, job.started_at, job.attempts = "running", now_fn(), job.attempts + 1
                job_id, asset = job.id, ASSETS.get(job.asset_id)
            if asset is None:
                with session_scope() as session:
                    _finish(session, job_id, "failed", now_fn(), error="unknown asset", attempts_done=True)
                continue
            if client is None:
                with session_scope() as session:
                    _finish(session, job_id, "failed", now_fn(), error="FREENEWSAPI_KEY is not configured", attempts_done=True)
                lines.append(f"news {asset.id}: skipped, FREENEWSAPI_KEY not set")
                break
            try:
                result = freenews.refresh(client, asset, now=now_fn())
            except freenews.NewsUnavailable as exc:
                with session_scope() as session:
                    _finish(session, job_id, "failed", now_fn(), error=str(exc)[:1000])
                lines.append(f"news {asset.id}: unavailable ({str(exc)[:120]})")
                continue
            with session_scope() as session:
                count = save_articles(session, asset, result.articles, now_fn())
                _finish(
                    session, job_id, "succeeded" if count else "empty", now_fn(),
                    error="; ".join(result.failures)[:1000] or None, requests=result.requests_used, count=count,
                )
            lines.append(f"news {asset.id}: {count} articles, {result.requests_used} requests, {len(result.failures)} partial failures")
    return lines


class _no_client:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def _finish(session, job_id, status, now, *, error=None, requests=0, count=0, attempts_done=False) -> None:
    values = dict(status=status, finished_at=now, error=error, requests_used=requests, article_count=count)
    if attempts_done:
        values["attempts"] = MAX_ATTEMPTS
    session.execute(update(NewsRefreshJobRow).where(NewsRefreshJobRow.id == job_id).values(**values))


# --- Reading ---------------------------------------------------------------------------


def recent_articles(session: Session, asset: AssetDefinition, limit: int = SHOWN_ARTICLES) -> list[NewsArticleRow]:
    return list(
        session.scalars(
            select(NewsArticleRow)
            .where(NewsArticleRow.asset_id == asset.id, NewsArticleRow.source == SOURCE)
            .order_by(NewsArticleRow.published_at.desc())
            .limit(limit)
        )
    )


def status(session: Session, asset: AssetDefinition, now: datetime) -> dict:
    """fresh | stale | empty | unavailable | pending, plus when news was last refreshed."""
    jobs = select(NewsRefreshJobRow).where(NewsRefreshJobRow.asset_id == asset.id)
    last_ok = session.scalars(
        jobs.where(NewsRefreshJobRow.status.in_(["succeeded", "empty"])).order_by(NewsRefreshJobRow.finished_at.desc()).limit(1)
    ).first()
    newest = session.scalars(jobs.order_by(NewsRefreshJobRow.created_at.desc()).limit(1)).first()
    pending = bool(newest and newest.status in ("pending", "running"))
    has_articles = bool(session.scalar(select(func.count()).where(NewsArticleRow.asset_id == asset.id)))
    if last_ok is None:
        state = "pending" if pending else ("stale" if has_articles else "unavailable")
    elif last_ok.status == "empty" and not has_articles:
        state = "empty"
    elif now - last_ok.finished_at <= FRESH_FOR:
        state = "fresh"
    else:
        state = "stale"
    failed = newest is not None and newest.status == "failed"
    return {
        "state": state,
        "refreshed_at": last_ok.finished_at if last_ok else None,
        "refreshing": pending,
        "last_error": (newest.error if failed else None),
        "last_attempt_failed": failed,
    }


# --- Owner-confirmed risks --------------------------------------------------------------


@dataclass(frozen=True)
class ActiveRisk:
    id: int
    reason: str
    confirmed_at: datetime
    expires_at: datetime
    article: NewsArticleRow | None


def active_risk(session: Session, asset: AssetDefinition, now: datetime) -> ActiveRisk | None:
    row = session.scalars(
        select(NewsRiskRow)
        .where(NewsRiskRow.asset_id == asset.id, NewsRiskRow.cleared_at.is_(None), NewsRiskRow.expires_at > now)
        .order_by(NewsRiskRow.confirmed_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    article = session.get(NewsArticleRow, (asset.id, row.source, row.provider_id))
    return ActiveRisk(row.id, row.reason, row.confirmed_at, row.expires_at, article)


class RiskRejected(ValueError):
    pass


def confirm_risk(session: Session, asset: AssetDefinition, provider_id: str, reason: str, now: datetime) -> NewsRiskRow:
    article = session.get(NewsArticleRow, (asset.id, SOURCE, provider_id))
    if article is None:
        raise RiskRejected("That article isn't one of this metal's saved news articles.")
    if not (now - RISK_WINDOW < article.published_at <= now + timedelta(minutes=5)):
        raise RiskRejected("Only articles published in the last 24 hours can be marked as a reason to wait.")
    reason = " ".join(reason.split())[:MAX_REASON]
    if not reason:
        raise RiskRejected("Please write a short reason.")
    clear_risk(session, asset, now)  # one active risk per asset
    row = NewsRiskRow(
        asset_id=asset.id, source=SOURCE, provider_id=provider_id, reason=reason, confirmed_at=now,
        expires_at=article.published_at + RISK_WINDOW,
    )
    session.add(row)
    session.flush()
    return row


def clear_risk(session: Session, asset: AssetDefinition, now: datetime) -> int:
    return session.execute(
        update(NewsRiskRow)
        .where(NewsRiskRow.asset_id == asset.id, NewsRiskRow.cleared_at.is_(None), NewsRiskRow.expires_at > now)
        .values(cleared_at=now)
    ).rowcount
