import csv
import io

import pytest

from phantom.app import create_app
from phantom.app.services.risk import calculate_volume, normalize_down, validate_policy


@pytest.fixture()
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE_PATH": tmp_path / "test.db"})


@pytest.fixture()
def client(app):
    return app.test_client()


def test_volume_normalization_rounds_down():
    assert normalize_down(0.129) == 0.12
    assert normalize_down(0.0) == 0.0
    assert calculate_volume(0.8, {"sizing_mode": "multiplier", "multiplier": 0.75, "max_lot": 1}, 10000) == 0.6


def test_policy_validation_rejects_invalid_values():
    errors = validate_policy({"sizing_mode": "fixed", "fixed_lot": -1, "max_open_positions": 0, "side_filter": "NOPE", "allowed_symbols": ""})
    assert "fixed_lot must be zero or greater" in errors
    assert "max_open_positions must be at least 1" in errors
    assert "Side filter is not supported" in errors
    assert "At least one allowed symbol is required" in errors


def test_dashboard_and_duplicate_protection(client):
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200
    assert response.get_json()["metrics"]["total_followers"] == 2

    first = client.post("/api/v1/simulation/tick")
    assert first.status_code == 200
    assert first.get_json()["processed"] is True

    # The first generated ID is based on row count, so the next call produces a new stable event.
    second = client.post("/api/v1/simulation/tick")
    assert second.status_code == 200
    assert second.get_json()["processed"] is True

    trades = client.get("/api/v1/trades").get_json()
    assert len(trades) == 3
    detail = client.get(f"/api/v1/trades/{trades[0]['id']}")
    assert detail.status_code == 200
    assert len(detail.get_json()["executions"]) == 2


def test_engine_emergency_stop_blocks_start_and_reset_is_paused(client):
    stop = client.post("/api/v1/engine/emergency-stop")
    assert stop.status_code == 200
    start = client.post("/api/v1/engine/start")
    assert start.status_code == 409
    reset = client.post("/api/v1/engine/reset-emergency")
    assert reset.status_code == 200
    status = client.get("/api/v1/status").get_json()
    assert status["engine"]["emergency_stop"] is False
    assert status["engine"]["state"] == "paused"


def test_policy_save_and_csv_export(client):
    payload = {"sizing_mode": "fixed", "multiplier": 1, "fixed_lot": 0.2, "balance_ratio": 1, "risk_pct": 0.5, "max_lot": 1, "max_risk": 1, "max_open_positions": 4, "allowed_symbols": "EURUSD,GBPUSD", "side_filter": "BOTH", "sltp_sync": 1, "pending_order_copy": 0, "copy_enabled": 1}
    saved = client.put("/api/v1/followers/follower-01/policy", json=payload)
    assert saved.status_code == 200
    assert saved.get_json()["policy"]["sizing_mode"] == "fixed"
    csv_response = client.get("/api/v1/export/trades.csv")
    assert csv_response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_response.get_data(as_text=True))))
    assert rows and "source_event_id" in rows[0]


def test_live_mode_is_dormant_and_activation_is_blocked(client, monkeypatch):
    monkeypatch.delenv("PHANTOM_LIVE_ENABLED", raising=False)
    preflight = client.get("/api/v1/live/preflight")
    assert preflight.status_code == 200
    data = preflight.get_json()
    assert data["ready"] is False
    assert data["activation_state"] == "disabled"
    assert any("PHANTOM_LIVE_ENABLED" in reason for reason in data["reasons"])

    activation = client.post("/api/v1/live/activate", json={"confirm": True})
    assert activation.status_code == 409
    assert client.get("/api/v1/status").get_json()["engine"]["mode"] == "SIMULATION"
