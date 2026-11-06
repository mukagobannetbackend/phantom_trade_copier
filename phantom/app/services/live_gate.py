from __future__ import annotations

import os
from typing import Any

from ..db import get_db, setting, utc_now
from .mt5_connector import connector_capabilities

REQUIRED_ACKS = {
    "demo_validation_passed": "Demo validation has passed on the target MT5 terminals",
    "broker_rules_reviewed": "Broker and prop-firm rules have been reviewed",
    "risk_limits_configured": "Volume, risk, drawdown, loss, and slippage limits are configured",
    "emergency_stop_tested": "Emergency stop behavior has been tested",
}


def _truthy(key: str) -> bool:
    return setting(key, "0") == "1"


def preflight() -> dict[str, Any]:
    db = get_db()
    master = db.execute("SELECT * FROM accounts WHERE role='master' AND enabled=1 LIMIT 1").fetchone()
    followers = db.execute("SELECT * FROM accounts WHERE role='follower' AND enabled=1").fetchall()
    reasons: list[str] = []
    if os.getenv("PHANTOM_LIVE_ENABLED", "0") != "1":
        reasons.append("Application live switch PHANTOM_LIVE_ENABLED is not enabled")
    if not connector_capabilities()["package_present"]:
        reasons.append("MetaTrader5 Python package is not installed on the target host")
    if not master:
        reasons.append("An enabled master account is required")
    if len(followers) < 1:
        reasons.append("At least one enabled follower account is required")
    if any(account["connection_state"] != "connected" or account["readiness"] != "ready" for account in [master, *followers] if account):
        reasons.append("Every enabled account must be connected and terminal-ready")
    if setting("emergency_stop", "0") == "1":
        reasons.append("Emergency stop is active")
    for key, description in REQUIRED_ACKS.items():
        if not _truthy(key):
            reasons.append(description)
    return {"ready": not reasons, "reasons": reasons, "acknowledgements": {key: _truthy(key) for key in REQUIRED_ACKS}, "connector": connector_capabilities(), "requested_mode": setting("mode", "SIMULATION"), "activation_state": setting("live_activation_state", "disabled"), "checked_at": utc_now()}


def set_acknowledgements(payload: dict[str, Any]) -> dict[str, Any]:
    db = get_db()
    for key in REQUIRED_ACKS:
        if key in payload:
            db.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (key, "1" if bool(payload[key]) else "0", utc_now()))
    db.commit()
    return preflight()


def activate_live(confirm: bool) -> tuple[bool, str, dict[str, Any]]:
    check = preflight()
    if not confirm:
        return False, "Explicit live activation confirmation is required.", check
    if not check["ready"]:
        return False, "Live mode remains locked until every preflight gate passes.", check
    db = get_db()
    db.execute("INSERT INTO settings(key,value,updated_at) VALUES('mode','LIVE',?) ON CONFLICT(key) DO UPDATE SET value='LIVE', updated_at=excluded.updated_at", (utc_now(),))
    db.execute("INSERT INTO settings(key,value,updated_at) VALUES('live_activation_state','active',?) ON CONFLICT(key) DO UPDATE SET value='active', updated_at=excluded.updated_at", (utc_now(),))
    db.commit()
    return True, "Live mode activated by explicit owner confirmation.", preflight()


def disable_live(reason: str = "owner_requested") -> dict[str, Any]:
    db = get_db()
    db.execute("INSERT INTO settings(key,value,updated_at) VALUES('mode','SIMULATION',?) ON CONFLICT(key) DO UPDATE SET value='SIMULATION', updated_at=excluded.updated_at", (utc_now(),))
    db.execute("INSERT INTO settings(key,value,updated_at) VALUES('live_activation_state','disabled',?) ON CONFLICT(key) DO UPDATE SET value='disabled', updated_at=excluded.updated_at", (utc_now(),))
    db.commit()
    return {"mode": "SIMULATION", "activation_state": "disabled", "reason": reason}
