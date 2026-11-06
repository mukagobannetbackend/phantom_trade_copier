from __future__ import annotations

import json
from random import choice

from ..db import get_db, set_setting, setting, utc_now
from .live_gate import preflight
from .risk import evaluate_entry


def audit(actor: str, action: str, object_type: str, object_id: str | None = None, metadata: dict | None = None):
    db = get_db()
    db.execute(
        "INSERT INTO audit_events(actor,action,object_type,object_id,metadata,created_at) VALUES(?,?,?,?,?,?)",
        (actor, action, object_type, object_id, json.dumps(metadata or {}, separators=(",", ":")), utc_now()),
    )
    db.commit()


def add_alert(severity: str, title: str, message: str, entity: str = "system"):
    db = get_db()
    db.execute("INSERT INTO alerts(severity,title,message,entity,created_at) VALUES(?,?,?,?,?)", (severity, title, message, entity, utc_now()))
    db.commit()


def engine_status():
    live = preflight()
    return {
        "state": setting("engine_state", "paused"),
        "mode": setting("mode", "SIMULATION"),
        "dataset": setting("dataset", "DEMO"),
        "emergency_stop": setting("emergency_stop", "0") == "1",
        "last_reconciliation": setting("last_reconciliation"),
        "live": live,
    }


def set_state(action: str):
    current = engine_status()
    if action == "start":
        if current["emergency_stop"]:
            return False, "Emergency stop is active. Reset it after reviewing the preflight state."
        if current["state"] == "running":
            return True, "Engine is already running."
        set_setting("engine_state", "running")
        audit("owner", "engine_started", "engine", metadata={"mode": "SIMULATION"})
        return True, "Simulation engine started. New entries are still isolated from brokers."
    if action == "pause":
        set_setting("engine_state", "paused")
        audit("owner", "engine_paused", "engine")
        return True, "Engine paused. New entry copies are blocked."
    if action == "resume":
        if current["emergency_stop"]:
            return False, "Emergency stop is active. Reset it before resuming."
        set_setting("engine_state", "running")
        audit("owner", "engine_resumed", "engine")
        return True, "Engine resumed in simulation mode."
    if action == "stop":
        set_setting("engine_state", "stopped")
        audit("owner", "engine_stopped", "engine")
        return True, "Engine stopped and queue cleared."
    if action == "emergency-stop":
        set_setting("engine_state", "emergency_stopped")
        set_setting("emergency_stop", "1")
        audit("owner", "emergency_stop_activated", "engine", metadata={"liquidate_positions": False})
        add_alert("critical", "Emergency stop active", "New submissions are blocked across all followers. Existing positions were not liquidated.")
        return True, "Emergency stop active. No new submissions will be accepted."
    if action == "reset-emergency":
        if current["emergency_stop"]:
            set_setting("emergency_stop", "0")
            set_setting("engine_state", "paused")
            audit("owner", "emergency_stop_reset", "engine", metadata={"reason": "owner_confirmation"})
            add_alert("info", "Emergency stop reset", "Engine remains paused until the owner explicitly starts or resumes it.")
            return True, "Emergency stop reset. Engine remains paused pending preflight."
        return True, "Emergency stop was not active."
    return False, "Unknown engine action."


def process_demo_event():
    db = get_db()
    state = engine_status()
    if state["emergency_stop"] or state["state"] not in {"running", "paused"}:
        return {"processed": False, "message": "Simulation is not accepting event processing in the current state."}
    event_num = db.execute("SELECT COUNT(*) FROM trades").fetchone()[0] + 1
    source_event_id = f"evt-demo-{event_num:03d}"
    existing = db.execute("SELECT id FROM trades WHERE source_event_id=?", (source_event_id,)).fetchone()
    if existing:
        return {"processed": False, "duplicate": True, "message": "Event already processed."}
    symbol = choice(["EURUSD", "GBPUSD", "XAUUSD"])
    side = choice(["BUY", "SELL"])
    source = {"symbol": symbol, "side": side, "volume": 0.40, "open_price": 1.08510 if symbol != "XAUUSD" else 2348.20}
    now = utc_now()
    db.execute(
        "INSERT INTO trades(source_event_id,source_ticket,symbol,side,volume,open_price,stop_loss,take_profit,event_type,event_time,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (source_event_id, f"M-{483000 + event_num}", symbol, side, source["volume"], source["open_price"], None, None, "OPEN", now, "detected", now),
    )
    trade_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    followers = db.execute("SELECT * FROM accounts WHERE role='follower' ORDER BY id").fetchall()
    results = []
    for follower_row in followers:
        follower = dict(follower_row)
        policy_row = db.execute("SELECT * FROM policies WHERE follower_id=?", (follower["id"],)).fetchone()
        policy = dict(policy_row) if policy_row else {}
        if state["state"] == "paused":
            decision = type("Decision", (), {"allowed": False, "volume": 0.0, "reason": "Engine paused; new entry copy blocked"})()
        else:
            decision = evaluate_entry(source, policy, follower)
        status = "success" if decision.allowed else "blocked"
        ticket = f"{follower['id'][:1].upper()}-{920000 + event_num}" if decision.allowed else None
        filled = decision.volume if decision.allowed else None
        filled_price = source["open_price"] + (0.00002 if decision.allowed and side == "BUY" else -0.00002 if decision.allowed else 0)
        slippage = 0.2 if decision.allowed else None
        db.execute(
            "INSERT INTO executions(trade_id,follower_id,follower_ticket,requested_volume,filled_volume,requested_price,filled_price,slippage,status,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (trade_id, follower["id"], ticket, decision.volume if decision.allowed else 0.0, filled, source["open_price"], filled_price if decision.allowed else None, slippage, status, decision.reason, now),
        )
        results.append({"follower_id": follower["id"], "status": status, "reason": decision.reason})
        if not decision.allowed and decision.reason and ("risk" in decision.reason.lower() or "cap" in decision.reason.lower() or "blocked" in decision.reason.lower()):
            add_alert("warning", "Copy blocked by policy", f"{follower['label']}: {decision.reason}", follower["id"])
    db.execute("UPDATE trades SET status=? WHERE id=?", ("copied" if any(r["status"] == "success" for r in results) else "blocked", trade_id))
    db.commit()
    audit("engine", "source_event_processed", "source_trade", source_event_id, {"results": results})
    return {"processed": True, "duplicate": False, "event_id": source_event_id, "results": results}
