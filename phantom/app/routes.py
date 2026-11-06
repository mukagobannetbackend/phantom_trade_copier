from __future__ import annotations

import csv
import io
import json

from flask import Blueprint, Response, jsonify, render_template, request

from .db import as_dict, get_db, set_setting, setting, utc_now
from .services.engine import add_alert, audit, engine_status, process_demo_event, set_state
from .services.live_gate import activate_live, disable_live, preflight, set_acknowledgements
from .services.risk import validate_policy

ui_bp = Blueprint("ui", __name__)
api_bp = Blueprint("api", __name__)


@ui_bp.get("/")
def index():
    return render_template("index.html")


@api_bp.get("/health")
def api_health():
    return jsonify({"ok": True, "service": "phantom-trade-copier", "mode": setting("mode", "SIMULATION"), "database": "sqlite"})


@api_bp.get("/status")
def status():
    db = get_db()
    master = db.execute("SELECT * FROM accounts WHERE role='master' LIMIT 1").fetchone()
    followers = db.execute("SELECT * FROM accounts WHERE role='follower' ORDER BY id").fetchall()
    counts = db.execute("SELECT status, COUNT(*) AS count FROM executions GROUP BY status").fetchall()
    return jsonify({"engine": engine_status(), "master": as_dict(master), "followers": [as_dict(row) for row in followers], "execution_counts": {row["status"]: row["count"] for row in counts}})


@api_bp.get("/dashboard")
def dashboard():
    db = get_db()
    accounts = [as_dict(row) for row in db.execute("SELECT * FROM accounts ORDER BY role DESC, id").fetchall()]
    trade_rows = db.execute(
        "SELECT t.*, COUNT(e.id) AS execution_count, SUM(CASE WHEN e.status='success' THEN 1 ELSE 0 END) AS success_count FROM trades t LEFT JOIN executions e ON e.trade_id=t.id GROUP BY t.id ORDER BY t.id DESC LIMIT 12"
    ).fetchall()
    executions = db.execute(
        "SELECT e.*, a.label AS follower_label, t.source_ticket, t.symbol, t.side, t.event_type FROM executions e JOIN accounts a ON a.id=e.follower_id JOIN trades t ON t.id=e.trade_id ORDER BY e.id DESC LIMIT 12"
    ).fetchall()
    alerts = db.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 6").fetchall()
    audit_rows = db.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT 8").fetchall()
    success_count = db.execute("SELECT COUNT(*) FROM executions WHERE status='success'").fetchone()[0]
    failure_count = db.execute("SELECT COUNT(*) FROM executions WHERE status IN ('blocked','failed')").fetchone()[0]
    active_positions = sum(account["active_positions"] for account in accounts)
    followers = [account for account in accounts if account["role"] == "follower"]
    healthy_followers = sum(1 for follower in followers if follower["connection_state"] == "connected" and follower["readiness"] == "ready")
    return jsonify({
        "engine": engine_status(),
        "accounts": accounts,
        "metrics": {"success_count": success_count, "failure_count": failure_count, "active_positions": active_positions, "healthy_followers": healthy_followers, "total_followers": len(followers), "sync_lag": "420 ms", "floating_pl": round(sum(account["floating_pl"] for account in accounts), 2)},
        "trades": [as_dict(row) for row in trade_rows],
        "executions": [as_dict(row) for row in executions],
        "alerts": [as_dict(row) for row in alerts],
        "audit": [as_dict(row) for row in audit_rows],
        "settings": {"daily_loss_limit": setting("daily_loss_limit", "2.0"), "drawdown_limit": setting("drawdown_limit", "5.0"), "max_slippage": setting("max_slippage", "0.8")},
    })


@api_bp.post("/engine/<action>")
def engine_control(action):
    ok, message = set_state(action)
    return jsonify({"ok": ok, "message": message, "engine": engine_status()}), (200 if ok else 409)


@api_bp.post("/simulation/tick")
def simulation_tick():
    result = process_demo_event()
    return jsonify(result), (200 if result.get("processed") or result.get("duplicate") else 409)


@api_bp.get("/live/preflight")
def live_preflight():
    return jsonify(preflight())


@api_bp.post("/live/acknowledgements")
def live_acknowledgements():
    payload = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "preflight": set_acknowledgements(payload)})


@api_bp.post("/live/activate")
def live_activate():
    payload = request.get_json(silent=True) or {}
    ok, message, check = activate_live(bool(payload.get("confirm")))
    if ok:
        audit("owner", "live_mode_activated", "engine", metadata={"mode": "LIVE"})
    return jsonify({"ok": ok, "message": message, "preflight": check}), (200 if ok else 409)


@api_bp.post("/live/disable")
def live_disable():
    payload = request.get_json(silent=True) or {}
    result = disable_live(payload.get("reason", "owner_requested"))
    audit("owner", "live_mode_disabled", "engine", metadata=result)
    return jsonify({"ok": True, "result": result, "engine": engine_status()})


@api_bp.get("/accounts")
def accounts():
    rows = get_db().execute("SELECT * FROM accounts ORDER BY role DESC, id").fetchall()
    return jsonify([as_dict(row) for row in rows])


@api_bp.post("/accounts")
def create_account():
    payload = request.get_json(silent=True) or {}
    required = ["id", "label", "role", "broker", "login_masked", "terminal_path"]
    missing = [key for key in required if not str(payload.get(key, "")).strip()]
    if missing or payload.get("role") not in {"master", "follower"}:
        return jsonify({"ok": False, "error": "Valid id, label, role, broker, masked login, and terminal path are required."}), 400
    db = get_db()
    now = utc_now()
    try:
        db.execute("INSERT INTO accounts(id,label,role,broker,login_masked,terminal_path,connection_state,readiness,enabled,heartbeat,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (payload["id"], payload["label"], payload["role"], payload["broker"], payload["login_masked"], payload["terminal_path"], "disconnected", "unknown", int(payload.get("enabled", 1)), now, now))
        if payload["role"] == "follower":
            db.execute("INSERT INTO policies(follower_id,updated_at) VALUES(?,?)", (payload["id"], now))
        db.commit()
    except Exception as exc:
        db.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400
    audit("owner", "account_created", "account", payload["id"], {"role": payload["role"]})
    return jsonify({"ok": True, "account": as_dict(db.execute("SELECT * FROM accounts WHERE id=?", (payload["id"],)).fetchone())}), 201


@api_bp.patch("/accounts/<account_id>")
def update_account(account_id):
    payload = request.get_json(silent=True) or {}
    allowed = {"label", "enabled", "connection_state", "readiness", "terminal_path"}
    changes = {key: payload[key] for key in allowed if key in payload}
    if not changes:
        return jsonify({"ok": False, "error": "No editable fields supplied."}), 400
    db = get_db()
    if not db.execute("SELECT id FROM accounts WHERE id=?", (account_id,)).fetchone():
        return jsonify({"ok": False, "error": "Account not found."}), 404
    set_clause = ", ".join(f"{key}=?" for key in changes)
    db.execute(f"UPDATE accounts SET {set_clause}, updated_at=? WHERE id=?", [*changes.values(), utc_now(), account_id])
    db.commit()
    audit("owner", "account_updated", "account", account_id, {"fields": list(changes)})
    return jsonify({"ok": True, "account": as_dict(db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())})


@api_bp.get("/followers/<follower_id>/policy")
def get_policy(follower_id):
    row = get_db().execute("SELECT * FROM policies WHERE follower_id=?", (follower_id,)).fetchone()
    return (jsonify(as_dict(row)), 200) if row else (jsonify({"error": "Follower policy not found"}), 404)


@api_bp.put("/followers/<follower_id>/policy")
def update_policy(follower_id):
    payload = request.get_json(silent=True) or {}
    errors = validate_policy(payload)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    db = get_db()
    if not db.execute("SELECT id FROM accounts WHERE id=? AND role='follower'", (follower_id,)).fetchone():
        return jsonify({"ok": False, "error": "Follower not found."}), 404
    fields = ["sizing_mode", "multiplier", "fixed_lot", "balance_ratio", "risk_pct", "max_lot", "max_risk", "max_open_positions", "allowed_symbols", "side_filter", "sltp_sync", "pending_order_copy", "copy_enabled"]
    values = [payload.get(field) for field in fields]
    db.execute(f"UPDATE policies SET {', '.join(f'{field}=?' for field in fields)}, updated_at=? WHERE follower_id=?", [*values, utc_now(), follower_id])
    db.commit()
    audit("owner", "policy_saved", "follower_policy", follower_id, {"sizing_mode": payload.get("sizing_mode"), "max_lot": payload.get("max_lot")})
    return jsonify({"ok": True, "policy": as_dict(db.execute("SELECT * FROM policies WHERE follower_id=?", (follower_id,)).fetchone())})


@api_bp.get("/trades")
def trades():
    rows = get_db().execute("SELECT * FROM trades ORDER BY id DESC").fetchall()
    return jsonify([as_dict(row) for row in rows])


@api_bp.get("/trades/<int:trade_id>")
def trade_detail(trade_id):
    db = get_db()
    trade = db.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not trade:
        return jsonify({"error": "Trade not found"}), 404
    executions = db.execute("SELECT e.*, a.label AS follower_label FROM executions e JOIN accounts a ON a.id=e.follower_id WHERE trade_id=? ORDER BY e.id", (trade_id,)).fetchall()
    return jsonify({"trade": as_dict(trade), "executions": [as_dict(row) for row in executions]})


@api_bp.get("/alerts")
def alerts():
    return jsonify([as_dict(row) for row in get_db().execute("SELECT * FROM alerts ORDER BY id DESC").fetchall()])


@api_bp.get("/audit")
def audit_log():
    return jsonify([as_dict(row) for row in get_db().execute("SELECT * FROM audit_events ORDER BY id DESC").fetchall()])


@api_bp.get("/export/trades.csv")
def export_trades():
    db = get_db()
    cursor = db.execute("SELECT t.source_event_id,t.source_ticket,t.symbol,t.side,t.volume,t.open_price,t.event_type,t.event_time,t.status,e.follower_id,e.follower_ticket,e.requested_volume,e.filled_volume,e.requested_price,e.filled_price,e.slippage,e.status AS execution_status,e.reason FROM trades t LEFT JOIN executions e ON e.trade_id=t.id ORDER BY t.id DESC")
    rows = cursor.fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([column[0] for column in cursor.description])
    writer.writerows([tuple(row) for row in rows])
    audit("owner", "trades_exported", "export", "trades.csv", {"rows": len(rows)})
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=phantom-trades.csv"})
