from fastapi.testclient import TestClient

from gold_advisor.api import app, get_session


class FakeSession:
    def __init__(self):
        self.rows = {}

    def get(self, _model, key):
        return self.rows.get(key)

    def add(self, row):
        self.rows[row.key] = row


def test_drawings_round_trip_per_asset_and_reject_bad_shapes():
    session = FakeSession()
    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        line = {"id": "a1", "kind": "trend", "points": [{"time": 1793592000, "price": 4000}, {"time": 1793678400, "price": 4100}]}
        assert client.put("/api/v1/settings/drawings", params={"asset": "gold"}, json={"drawings": [line]}).status_code == 200
        assert client.get("/api/v1/settings/drawings", params={"asset": "gold"}).json()["drawings"] == [line]
        assert client.get("/api/v1/settings/drawings", params={"asset": "silver"}).json()["drawings"] == []
        one_point_trend = {**line, "points": line["points"][:1]}
        assert client.put("/api/v1/settings/drawings", params={"asset": "gold"}, json={"drawings": [one_point_trend]}).status_code == 422
    finally:
        app.dependency_overrides.clear()
