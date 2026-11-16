"""Browser notifications (Web Push). Checked once per cycle, so they can be up to 30 minutes late.

Each event fires once: it is stored in ``alert_events`` under a unique key before it is sent, so
running the cycle again never repeats a message. A failure to send never fails the cycle. Without
GA_VAPID_PRIVATE_KEY and GA_VAPID_SUBJECT the feature is off.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from gold_advisor.assets import AssetDefinition
from gold_advisor.config import get_settings
from gold_advisor.domain import NEPAL_TZ, UTC
from gold_advisor.persistence.models import AlertEventRow, AppSettingRow, PushSubscriptionRow

log = logging.getLogger(__name__)

KINDS = {
    "advice": "The advice changed",
    "nepal": "Nepal published today's price",
    "second_half": "Time for the second half",
    "watch": "A watch level was crossed",
    "trade": "The silver trade plan changed",
}
SETTINGS_KEY = "alerts"
TTL_SECONDS = 3 * 3600


@dataclass(frozen=True)
class Alert:
    key: str
    kind: str
    asset_id: str
    title: str
    body: str
    url: str


def enabled() -> bool:
    cfg = get_settings()
    return bool(cfg.vapid_private_key and cfg.vapid_subject)


def settings(session: Session) -> dict[str, bool]:
    row = session.get(AppSettingRow, SETTINGS_KEY)
    stored = (row.value.get("value") if row else None) or {}
    return {kind: bool(stored.get(kind, True)) for kind in KINDS}


def _rupees(value: float) -> str:
    from gold_advisor.decision.rules import rupees

    return rupees(value)


def _first_sentence(text: str) -> str:
    head = text.split(". ")[0].strip()
    return head if head.endswith(".") else f"{head}."


def detect(asset: AssetDefinition, snapshot_id: str, new: dict, old: dict | None) -> list[Alert]:
    """Events between the previous snapshot (``old``) and the new one. Payloads as stored."""
    if old is None:
        return []
    label, today = asset.label, datetime.fromisoformat(new["created_at"]).astimezone(NEPAL_TZ).date()
    home, trade = f"/?asset={asset.id}", f"/trade?asset={asset.id}"
    out: list[Alert] = []
    d_new, d_old = new["decision"], old["decision"]
    if d_new["decision"] != d_old["decision"]:
        out.append(Alert(f"advice:{asset.id}:{snapshot_id}", "advice", asset.id, f"{label}: {d_new['headline']}",
                         _first_sentence(d_new["summary"]), home))
    n_new = (new["prices"].get("nepal_latest") or {})
    n_old = (old["prices"].get("nepal_latest") or {})
    if n_new.get("rate_date") and n_new.get("rate_date") != n_old.get("rate_date") and n_new.get("nepal_price"):
        price = n_new["nepal_price"]
        change = price - n_old["nepal_price"] if n_old.get("nepal_price") else None
        moved = "unchanged" if not change else f"{'up' if change > 0 else 'down'} {_rupees(abs(change))}"
        out.append(Alert(f"nepal:{asset.id}:{n_new['rate_date'][:10]}", "nepal", asset.id,
                         f"Nepal {label.lower()} today: {_rupees(price)}", f"Per tola, {moved} from the last price.", home))
    s_new, s_old = new.get("second_half") or {}, old.get("second_half") or {}
    if s_new.get("reached") and s_new.get("reached") != s_old.get("reached"):
        out.append(Alert(f"second_half:{asset.id}:{s_new['first_part_at']}:{s_new['reached']}", "second_half", asset.id,
                         f"{label}: time to buy the second half", s_new["plain"], home))
    w_new, w_old = new["prices"].get("world_usd_now"), old["prices"].get("world_usd_now")
    if w_new and w_old:
        factor = new.get("rupees_per_usd_oz")
        for level in new.get("watch_levels") or []:
            if (w_old - level) * (w_new - level) < 0:
                up = w_new > level
                about = f" (about {_rupees(level * factor)} per tola in Nepal)" if factor else ""
                out.append(Alert(f"watch:{asset.id}:{level}:{'up' if up else 'down'}:{today}", "watch", asset.id,
                                 f"World {label.lower()} {'rose above' if up else 'fell below'} your watch level",
                                 f"It crossed ${level:,.0f} an ounce{about}.", home))
    t_new, t_old = new.get("trade_plan") or {}, old.get("trade_plan") or {}
    if t_new.get("state") and t_old.get("state") and t_new["state"] != t_old["state"]:
        out.append(Alert(f"trade:{asset.id}:{snapshot_id}:{t_new['state']}", "trade", asset.id,
                         f"{label} trade plan: {t_new['plain']}", "Open the Trade screen for the rupee levels.", trade))
    return out


def record(session: Session, alerts: list[Alert]) -> list[Alert]:
    """Store the alerts; return only those never stored before (the ones to send)."""
    fresh = []
    for a in alerts:
        inserted = session.execute(
            insert(AlertEventRow)
            .values(key=a.key, kind=a.kind, asset_id=a.asset_id, title=a.title, body=a.body, url=a.url)
            .on_conflict_do_nothing(index_elements=["key"])
            .returning(AlertEventRow.id)
        ).first()
        if inserted:
            fresh.append(a)
    return fresh


def send(session: Session, title: str, body: str, url: str, endpoints: list[str] | None = None) -> int:
    """Push one message to every stored subscription (or the given ones). Returns how many succeeded.
    A subscription the push service no longer knows (404 or 410) is deleted."""
    from pywebpush import WebPushException, webpush

    cfg = get_settings()
    query = select(PushSubscriptionRow)
    if endpoints is not None:
        query = query.where(PushSubscriptionRow.endpoint.in_(endpoints))
    delivered = 0
    for sub in session.scalars(query).all():
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=json.dumps({"title": title, "body": body, "url": url}),
                vapid_private_key=cfg.vapid_private_key,
                vapid_claims={"sub": cfg.vapid_subject},
                ttl=TTL_SECONDS,
                timeout=10,
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                session.execute(delete(PushSubscriptionRow).where(PushSubscriptionRow.id == sub.id))
                log.info("push subscription %s removed (%s)", sub.id, status)
            else:
                sub.failure_count += 1
                log.warning("push to subscription %s failed: %s", sub.id, exc)
            continue
        sub.last_success_at, sub.failure_count = datetime.now(UTC), 0
        delivered += 1
    return delivered


def run(session_factory, assets: list[AssetDefinition]) -> list[str]:
    """End of the cycle: detect, store and send. Returns log lines."""
    from gold_advisor.persistence.models import AnalysisSnapshotRow

    lines = []
    if not enabled():
        return ["alerts skipped: GA_VAPID_PRIVATE_KEY / GA_VAPID_SUBJECT not set"]
    with session_factory() as session:
        wanted = settings(session)
        found: list[Alert] = []
        for asset in assets:
            rows = session.scalars(
                select(AnalysisSnapshotRow).where(AnalysisSnapshotRow.asset_id == asset.id)
                .order_by(AnalysisSnapshotRow.created_at.desc(), AnalysisSnapshotRow.id.desc()).limit(2)
            ).all()
            if len(rows) == 2:
                found += [a for a in detect(asset, rows[0].id, rows[0].payload, rows[1].payload) if wanted.get(a.kind, True)]
        fresh = record(session, found)
    for a in fresh:
        with session_factory() as session:
            delivered = send(session, a.title, a.body, a.url)
            row = session.scalars(select(AlertEventRow).where(AlertEventRow.key == a.key)).first()
            if row is not None:
                row.sent = delivered
        lines.append(f"alert {a.kind} {a.asset_id}: sent to {delivered} device(s)")
    return lines or ["alerts: nothing new"]
