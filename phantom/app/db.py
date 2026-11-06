from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def db_path() -> str:
    configured = current_app.config.get("DATABASE_PATH")
    if configured:
        return str(configured)
    configured = os.getenv("PHANTOM_DATABASE_PATH")
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = Path(current_app.instance_path) / path
        return str(path)
    return str(Path(current_app.instance_path) / "phantom.db")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        path = Path(db_path())
        path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('master','follower')),
            broker TEXT NOT NULL,
            login_masked TEXT NOT NULL,
            terminal_path TEXT NOT NULL,
            connection_state TEXT NOT NULL,
            readiness TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            heartbeat TEXT NOT NULL,
            balance REAL NOT NULL DEFAULT 0,
            equity REAL NOT NULL DEFAULT 0,
            margin REAL NOT NULL DEFAULT 0,
            free_margin REAL NOT NULL DEFAULT 0,
            floating_pl REAL NOT NULL DEFAULT 0,
            active_positions INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS policies (
            follower_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
            sizing_mode TEXT NOT NULL DEFAULT 'multiplier',
            multiplier REAL NOT NULL DEFAULT 1.0,
            fixed_lot REAL NOT NULL DEFAULT 0.10,
            balance_ratio REAL NOT NULL DEFAULT 1.0,
            risk_pct REAL NOT NULL DEFAULT 0.50,
            max_lot REAL NOT NULL DEFAULT 1.00,
            max_risk REAL NOT NULL DEFAULT 1.00,
            max_open_positions INTEGER NOT NULL DEFAULT 8,
            allowed_symbols TEXT NOT NULL DEFAULT 'EURUSD,GBPUSD,XAUUSD',
            side_filter TEXT NOT NULL DEFAULT 'BOTH',
            sltp_sync INTEGER NOT NULL DEFAULT 1,
            pending_order_copy INTEGER NOT NULL DEFAULT 0,
            copy_enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_event_id TEXT UNIQUE NOT NULL,
            source_ticket TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            volume REAL NOT NULL,
            open_price REAL NOT NULL,
            stop_loss REAL,
            take_profit REAL,
            event_type TEXT NOT NULL,
            event_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'detected',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
            follower_id TEXT NOT NULL REFERENCES accounts(id),
            follower_ticket TEXT,
            requested_volume REAL NOT NULL,
            filled_volume REAL,
            requested_price REAL,
            filled_price REAL,
            slippage REAL,
            status TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(trade_id, follower_id)
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            entity TEXT,
            acknowledged INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            object_type TEXT NOT NULL,
            object_id TEXT,
            metadata TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    db.commit()
    if db.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
        _seed(db)


def _seed(db: sqlite3.Connection):
    now = utc_now()
    settings = {
        "engine_state": "paused",
        "mode": "SIMULATION",
        "dataset": "DEMO",
        "emergency_stop": "0",
        "daily_loss_limit": "2.0",
        "drawdown_limit": "5.0",
        "max_slippage": "0.8",
        "last_reconciliation": now,
    }
    db.executemany("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?)", [(k, v, now) for k, v in settings.items()])
    accounts = [
        ("master-01", "Atlas Master", "master", "Apex Demo", "•••• 8142", "C:\\MT5\\Atlas-Master", "connected", "ready", 1, now, 25000.00, 25284.70, 1480.20, 23804.50, 284.70, 2, now),
        ("follower-01", "Nova Follower", "follower", "Apex Demo", "•••• 4921", "C:\\MT5\\Nova-Follower", "connected", "ready", 1, now, 10000.00, 10118.42, 620.90, 9497.52, 118.42, 2, now),
        ("follower-02", "Helios Follower", "follower", "Vertex Demo", "•••• 7718", "C:\\MT5\\Helios-Follower", "stale", "review", 1, now, 7500.00, 7429.60, 510.10, 6919.50, -70.40, 1, now),
    ]
    db.executemany(
        "INSERT INTO accounts(id,label,role,broker,login_masked,terminal_path,connection_state,readiness,enabled,heartbeat,balance,equity,margin,free_margin,floating_pl,active_positions,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        accounts,
    )
    policies = [
        ("follower-01", "multiplier", 0.75, 0.10, 1.0, 0.50, 1.00, 1.00, 8, "EURUSD,GBPUSD,XAUUSD", "BOTH", 1, 0, 1, now),
        ("follower-02", "fixed", 1.0, 0.05, 1.0, 0.25, 0.50, 0.50, 5, "EURUSD,GBPUSD", "BUY_ONLY", 1, 0, 1, now),
    ]
    db.executemany(
        "INSERT INTO policies(follower_id,sizing_mode,multiplier,fixed_lot,balance_ratio,risk_pct,max_lot,max_risk,max_open_positions,allowed_symbols,side_filter,sltp_sync,pending_order_copy,copy_enabled,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        policies,
    )
    db.execute(
        "INSERT INTO trades(source_event_id,source_ticket,symbol,side,volume,open_price,stop_loss,take_profit,event_type,event_time,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        ("evt-20261106-001", "M-482901", "EURUSD", "BUY", 0.80, 1.08342, 1.08042, 1.08942, "OPEN", now, "copied", now),
    )
    trade_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.executemany(
        "INSERT INTO executions(trade_id,follower_id,follower_ticket,requested_volume,filled_volume,requested_price,filled_price,slippage,status,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [
            (trade_id, "follower-01", "N-772104", 0.60, 0.60, 1.08344, 1.08346, 0.2, "success", None, now),
            (trade_id, "follower-02", None, 0.40, None, 1.08344, None, None, "blocked", "Side filter allows BUY only; connector is stale", now),
        ],
    )
    alerts = [
        ("warning", "Follower heartbeat stale", "Helios Follower has not confirmed a terminal heartbeat in 41s.", "follower-02", 0, now),
        ("success", "Copy cycle completed", "Atlas Master → Nova Follower copied 1 open event with 0.2 pts slippage.", "evt-20261106-001", 0, now),
        ("info", "Simulation safeguards active", "No broker orders can be submitted from this build.", "system", 0, now),
    ]
    db.executemany("INSERT INTO alerts(severity,title,message,entity,acknowledged,created_at) VALUES(?,?,?,?,?,?)", alerts)
    audit = [
        ("system", "seed_demo_dataset", "system", "DEMO", '{"mode":"SIMULATION"}', now),
        ("owner", "policy_saved", "follower_policy", "follower-01", '{"sizing_mode":"multiplier","multiplier":0.75}', now),
        ("engine", "source_event_copied", "source_trade", "evt-20261106-001", '{"success":1,"blocked":1}', now),
    ]
    db.executemany("INSERT INTO audit_events(actor,action,object_type,object_id,metadata,created_at) VALUES(?,?,?,?,?,?)", audit)
    db.commit()


def setting(key: str, default=None):
    row = get_db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value):
    db = get_db()
    db.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (key, str(value), utc_now()))
    db.commit()


def as_dict(row):
    return dict(row) if row else None
