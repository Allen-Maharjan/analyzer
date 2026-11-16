from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from gold_advisor import api
from gold_advisor.config import get_settings
from gold_advisor.domain import NEPAL_TZ, UTC


class FakeSession:
    def __init__(self, newest):
        self.newest = newest

    def scalar(self, _query):
        return self.newest


def test_cron_tick_needs_its_own_token_and_never_the_internal_one(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "internal_token", "internal-token")
    monkeypatch.setattr(api, "ensure_fresh", lambda session, now: (True, "update started"))
    api.app.dependency_overrides[api.get_session] = lambda: None
    try:
        client = TestClient(api.app)
        monkeypatch.setattr(settings, "cron_token", "")
        assert client.post("/api/v1/cron/tick", headers={"Authorization": "Bearer x"}).status_code == 404
        monkeypatch.setattr(settings, "cron_token", "cron-token")
        assert client.post("/api/v1/cron/tick", headers={"x-internal-token": "internal-token"}).status_code == 401
        ok = client.post("/api/v1/cron/tick", headers={"Authorization": "Bearer cron-token"})
        assert ok.status_code == 200 and ok.json() == {"started": True, "reason": "update started", "updating": True}
    finally:
        api.app.dependency_overrides.clear()


def test_ensure_fresh_skips_young_advice_and_nepal_saturday(monkeypatch):
    monkeypatch.setattr(api, "cooldown_passed", lambda *a: True)
    monkeypatch.setattr(api, "dispatch_cycle", lambda force_daily=False: True)
    monday = datetime(2026, 11, 16, 14, 0, tzinfo=NEPAL_TZ).astimezone(UTC)
    assert api.ensure_fresh(FakeSession(monday - timedelta(minutes=10)), monday)[0] is False
    assert api.ensure_fresh(FakeSession(monday - timedelta(minutes=40)), monday) == (True, "update started")
    saturday = datetime(2026, 11, 14, 14, 0, tzinfo=NEPAL_TZ).astimezone(UTC)
    assert api.ensure_fresh(FakeSession(saturday - timedelta(hours=3)), saturday)[0] is False
