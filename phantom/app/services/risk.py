from __future__ import annotations

from dataclasses import dataclass
from math import floor


@dataclass
class RiskDecision:
    allowed: bool
    volume: float
    reason: str | None = None


def normalize_down(volume: float, step: float = 0.01) -> float:
    if volume <= 0:
        return 0.0
    return round(floor((volume + 1e-9) / step) * step, 2)


def calculate_volume(source_volume: float, policy: dict, follower_equity: float) -> float:
    mode = policy.get("sizing_mode", "multiplier")
    if mode == "fixed":
        raw = float(policy.get("fixed_lot", 0.1))
    elif mode == "balance_ratio":
        raw = source_volume * max(float(policy.get("balance_ratio", 1.0)), 0) * max(follower_equity, 0) / 10000
    elif mode == "risk_pct":
        # Demo approximation. A live implementation must use contract tick metadata and SL distance.
        raw = max(float(policy.get("risk_pct", 0.5)), 0) * max(follower_equity, 0) / 100000
    else:
        raw = source_volume * max(float(policy.get("multiplier", 1.0)), 0)
    return min(normalize_down(raw), normalize_down(float(policy.get("max_lot", 1.0))))


def evaluate_entry(source: dict, policy: dict, follower: dict) -> RiskDecision:
    symbol = source["symbol"]
    side = source["side"]
    allowed_symbols = {item.strip().upper() for item in policy.get("allowed_symbols", "").split(",") if item.strip()}
    if allowed_symbols and symbol.upper() not in allowed_symbols:
        return RiskDecision(False, 0.0, f"Symbol {symbol} is not in the follower allowlist")
    side_filter = policy.get("side_filter", "BOTH")
    if side_filter == "BUY_ONLY" and side != "BUY":
        return RiskDecision(False, 0.0, "Follower direction filter blocks SELL entries")
    if side_filter == "SELL_ONLY" and side != "SELL":
        return RiskDecision(False, 0.0, "Follower direction filter blocks BUY entries")
    if not int(policy.get("copy_enabled", 1)):
        return RiskDecision(False, 0.0, "Follower copy toggle is disabled")
    if follower.get("connection_state") != "connected":
        return RiskDecision(False, 0.0, "Follower connector is not connected")
    if follower.get("readiness") != "ready":
        return RiskDecision(False, 0.0, "Follower terminal is not ready")
    if int(follower.get("active_positions", 0)) >= int(policy.get("max_open_positions", 8)):
        return RiskDecision(False, 0.0, "Follower max open positions cap reached")
    volume = calculate_volume(float(source["volume"]), policy, float(follower.get("equity", 0)))
    if volume <= 0:
        return RiskDecision(False, 0.0, "Normalized volume is below broker minimum")
    return RiskDecision(True, volume)


def validate_policy(payload: dict) -> list[str]:
    errors = []
    if payload.get("sizing_mode") not in {"fixed", "multiplier", "balance_ratio", "risk_pct"}:
        errors.append("Sizing mode is not supported")
    for key in ("multiplier", "fixed_lot", "balance_ratio", "risk_pct", "max_lot", "max_risk"):
        try:
            if float(payload.get(key, 0)) < 0:
                errors.append(f"{key} must be zero or greater")
        except (TypeError, ValueError):
            errors.append(f"{key} must be numeric")
    try:
        if int(payload.get("max_open_positions", 0)) < 1:
            errors.append("max_open_positions must be at least 1")
    except (TypeError, ValueError):
        errors.append("max_open_positions must be an integer")
    if payload.get("side_filter") not in {"BOTH", "BUY_ONLY", "SELL_ONLY"}:
        errors.append("Side filter is not supported")
    if not str(payload.get("allowed_symbols", "")).strip():
        errors.append("At least one allowed symbol is required")
    return errors
