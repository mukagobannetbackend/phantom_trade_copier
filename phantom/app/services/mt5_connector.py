"""MT5 connector seam.

The live adapter is intentionally lazy and refuses to run unless the application
and operator activation gates are both open. This module can be installed on a
Windows host with the MetaTrader5 package without changing Flask routes.
"""
from __future__ import annotations

import importlib.util
import os
from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass
class MarketOrderRequest:
    symbol: str
    side: str
    volume: float
    stop_loss: float | None = None
    take_profit: float | None = None
    deviation: int = 20
    source_event_id: str | None = None


@dataclass
class ExecutionReceipt:
    accepted: bool
    ticket: str | None
    requested_volume: float
    filled_volume: float | None
    requested_price: float | None
    filled_price: float | None
    retcode: int | None
    message: str
    raw: dict[str, Any] | None = None


class MT5Connector(Protocol):
    def connect(self, terminal_path: str | None = None) -> bool: ...
    def account_snapshot(self) -> dict[str, Any]: ...
    def positions(self) -> list[dict[str, Any]]: ...
    def send_market_order(self, request: MarketOrderRequest) -> ExecutionReceipt: ...
    def modify_position(self, ticket: str, stop_loss: float | None, take_profit: float | None) -> bool: ...
    def close_position(self, ticket: str, volume: float | None = None) -> bool: ...


class SimulatedMT5Connector:
    """Safe adapter used by the current dashboard and test suite."""

    def connect(self, terminal_path: str | None = None) -> bool:
        return True

    def account_snapshot(self) -> dict[str, Any]:
        return {"connected": True, "mode": "SIMULATION", "balance": 0, "equity": 0, "margin": 0}

    def positions(self) -> list[dict[str, Any]]:
        return []

    def send_market_order(self, request: MarketOrderRequest) -> ExecutionReceipt:
        return ExecutionReceipt(False, None, request.volume, None, None, None, None, "Simulation adapter never submits broker orders")

    def modify_position(self, ticket: str, stop_loss: float | None, take_profit: float | None) -> bool:
        return False

    def close_position(self, ticket: str, volume: float | None = None) -> bool:
        return False


class MT5PythonConnector:
    """Thin, lazy wrapper around the official MetaTrader5 Python package.

    The constructor does not import or initialize MetaTrader5 until used. The
    caller must enforce the application live-mode gate before constructing this
    adapter. The package is not installed in the current sandbox.
    """

    def __init__(self, terminal_path: str | None = None):
        self.terminal_path = terminal_path
        self._mt5 = None

    def _module(self):
        if self._mt5 is None:
            try:
                import MetaTrader5 as mt5  # type: ignore
            except ImportError as exc:
                raise RuntimeError("MetaTrader5 package is not installed on this host") from exc
            self._mt5 = mt5
        return self._mt5

    def connect(self, terminal_path: str | None = None) -> bool:
        mt5 = self._module()
        path = terminal_path or self.terminal_path
        return bool(mt5.initialize(path=path) if path else mt5.initialize())

    def account_snapshot(self) -> dict[str, Any]:
        info = self._module().account_info()
        if info is None:
            return {"connected": False, "error": "account_info returned no data"}
        return {"connected": True, "login": info.login, "balance": info.balance, "equity": info.equity, "margin": info.margin, "free_margin": info.margin_free, "floating_pl": info.profit}

    def positions(self) -> list[dict[str, Any]]:
        positions = self._module().positions_get() or []
        return [{"ticket": position.ticket, "symbol": position.symbol, "volume": position.volume, "type": position.type, "price_open": position.price_open, "sl": position.sl, "tp": position.tp, "profit": position.profit} for position in positions]

    def send_market_order(self, request: MarketOrderRequest) -> ExecutionReceipt:
        mt5 = self._module()
        tick = mt5.symbol_info_tick(request.symbol)
        if tick is None:
            return ExecutionReceipt(False, None, request.volume, None, None, None, None, f"Symbol {request.symbol} has no tick data")
        order_type = mt5.ORDER_TYPE_BUY if request.side == "BUY" else mt5.ORDER_TYPE_SELL
        price = tick.ask if request.side == "BUY" else tick.bid
        result = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "symbol": request.symbol, "volume": request.volume, "type": order_type, "price": price, "sl": request.stop_loss or 0.0, "tp": request.take_profit or 0.0, "deviation": request.deviation, "magic": 902611, "comment": f"phantom:{request.source_event_id or 'manual'}", "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_RETURN})
        if result is None:
            return ExecutionReceipt(False, None, request.volume, None, price, None, None, "order_send returned no result")
        accepted = result.retcode == mt5.TRADE_RETCODE_DONE
        return ExecutionReceipt(accepted, str(result.order or result.deal) if accepted else None, request.volume, result.volume if accepted else None, price, result.price if accepted else None, result.retcode, str(result.comment), {"retcode": result.retcode, "comment": result.comment})

    def modify_position(self, ticket: str, stop_loss: float | None, take_profit: float | None) -> bool:
        mt5 = self._module()
        result = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": int(ticket), "sl": stop_loss or 0.0, "tp": take_profit or 0.0})
        return bool(result and result.retcode == mt5.TRADE_RETCODE_DONE)

    def close_position(self, ticket: str, volume: float | None = None) -> bool:
        # Closing requires the live position side, tick and broker filling mode;
        # keep this explicit for the Windows integration milestone rather than
        # guessing from a ticket alone.
        raise NotImplementedError("Close-position routing must resolve the live position side before submission")


def connector_capabilities() -> dict[str, Any]:
    package_present = importlib.util.find_spec("MetaTrader5") is not None
    application_enabled = os.getenv("PHANTOM_LIVE_ENABLED", "0") == "1"
    return {"package_present": package_present, "application_enabled": application_enabled, "provider": "MetaTrader5 Python package" if package_present else "not installed", "supports": ["master monitoring", "market execution", "SL/TP modification", "position reconciliation"], "disabled_by_default": True}


def connector_receipt(request: MarketOrderRequest, receipt: ExecutionReceipt) -> dict[str, Any]:
    return {"request": asdict(request), "receipt": asdict(receipt)}
