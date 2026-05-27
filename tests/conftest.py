"""
conftest.py — Shared test fixtures for the comprehensive test suite.

Provides:
- In-memory SQLite database (fresh per test)
- Mock Binance clients (data + demo)
- Test configuration overrides
- Helper factories for test data
"""
import os
import sys
import json
import pytest
import sqlite3
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Any, List

# ─── Ensure project root is on sys.path ─────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ─── Override configuration BEFORE any backend imports ─────
# We set env vars at module level, but backend.config._load_env() reads the
# real .env file and overwrites them on import. To prevent this, we temporarily
# rename .env so _load_env skips it, then rename it back.
import tempfile
from pathlib import Path

_env_backup: str | None = None

_env_path = Path(__file__).resolve().parent.parent / ".env"
_env_renamed = False
try:
    if _env_path.exists():
        import uuid
        _backup_name = f".env.test_backup_{uuid.uuid4().hex[:8]}"
        _env_path.rename(_env_path.parent / _backup_name)
        _env_backup = str(_env_path.parent / _backup_name)
        _env_renamed = True
except (PermissionError, OSError):
    # File may be locked by another process on Windows — just proceed
    _env_renamed = False

# Set our test env vars (these won't be overwritten if .env was renamed)
for _key, _val in {
    "BINANCE_API_KEY": "test_data_key",
    "BINANCE_SECRET_KEY": "test_data_secret",
    "BINANCE_DEMO_KEY": "test_demo_key",
    "BINANCE_DEMO_SECRET": "test_demo_secret",
    "SMTP_EMAIL": "test@example.com",
    "SMTP_PASSWORD": "test_app_password",
    "SMTP_TO": "recipient@example.com",
    "BTC_TRIGGER_PCT": "1.0",
    "TP_PCT": "1.0",
    "SL_PCT": "0.5",
    "POSITION_SIZE_USDT": "10.0",
    "MAX_COINS_PER_TRADE": "5",
    "MAX_DAILY_LOSS_USDT": "60.0",
    "MAX_TRADES_PER_DAY": "10",
    "MAX_CONSECUTIVE_LOSSES": "5",
    "ACCOUNT_SIZE_USDT": "1000.0",
    "SCAN_MAX_SYMBOLS": "645",
    "SCAN_DURATION_MINUTES": "30",
    "FIXED_COINS": "ETHUSDT,DOGEUSDT",
    "TOP_DYNAMIC_COINS": "3",
    "LOG_LEVEL": "CRITICAL",  # Suppress logs during tests
}.items():
    os.environ[_key] = _val

# Import config (with .env gone, _load_env will warn but not overwrite)
import importlib
import backend.config
importlib.reload(backend.config)

# Restore the real .env file so the production system still works
if _env_renamed and _env_backup:
    try:
        import shutil
        shutil.move(str(_env_backup), str(_env_path))
    except (PermissionError, OSError):
        pass  # Can't restore, file may be locked


# ─── In-Memory Database Fixture ─────────────────────────────
@pytest.fixture
def db_conn():
    """
    Create a fresh in-memory SQLite database for each test.
    All tables are created. The connection is closed after the test.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")

    from backend.database.schema import create_all_tables
    create_all_tables(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _patch_db_path(db_conn):
    """
    Auto-use fixture that patches get_connection() to return the
    in-memory database. This ensures all test DB operations go to RAM.
    """
    import backend.database.db as db_module

    original_get_conn = db_module.get_connection

    def mock_get_connection():
        return db_conn

    with patch.object(db_module, "get_connection", side_effect=mock_get_connection):
        yield


# ─── Mock Binance Client Factory ────────────────────────────

class MockBinanceClient:
    """
    A mock Binance Futures API client for testing.

    Default behaviors return realistic-looking data without hitting
    any real API. Can be customized per test by setting attributes.
    """

    def __init__(self, use_demo: bool = False):
        self.use_demo = use_demo
        self.api_key = "test_demo_key" if use_demo else "test_data_key"
        self.api_secret = "test_demo_secret" if use_demo else "test_data_secret"
        self._orders: List[dict] = []
        self._positions: List[dict] = []
        self._open_orders_list: List[dict] = []
        self._algo_orders_list: List[dict] = []
        self._order_id_counter = 1000
        self._algo_id_counter = 5000
        self._balance = 10000.0
        self._prices: dict = {}
        self._exchange_info: Optional[dict] = None

    # ── Mock setup helpers ──────────────────────────────────

    def set_price(self, symbol: str, price: float):
        self._prices[symbol.upper()] = price

    def get_default_price(self, symbol: str) -> float:
        return self._prices.get(symbol.upper(), {
            "BTCUSDT": 65000.0,
            "ETHUSDT": 3450.0,
            "DOGEUSDT": 0.12,
            "FARTCOINUSDT": 0.05,
        }.get(symbol.upper(), 1.0))

    def set_balance(self, balance: float):
        self._balance = balance

    def set_position(self, symbol: str, amt: float, entry_price: float = 0):
        """Set a mock open position for a symbol."""
        existing = [p for p in self._positions if p["symbol"] == symbol.upper()]
        if existing:
            existing[0]["positionAmt"] = str(amt)
            existing[0]["entryPrice"] = str(entry_price) if entry_price else existing[0]["entryPrice"]
            existing[0]["markPrice"] = str(self.get_default_price(symbol))
        else:
            self._positions.append({
                "symbol": symbol.upper(),
                "positionAmt": str(amt),
                "entryPrice": str(entry_price if entry_price else self.get_default_price(symbol)),
                "markPrice": str(self.get_default_price(symbol)),
                "unRealizedProfit": "0.0",
            })

    def clear_positions(self):
        self._positions = []

    def add_open_order(self, order_id: int = None, symbol: str = "BTCUSDT",
                       side: str = "BUY", order_type: str = "LIMIT",
                       price: float = 100.0, orig_qty: float = 1.0,
                       executed_qty: float = 0.0, status: str = "NEW"):
        """Add a mock open order."""
        oid = order_id or self._next_order_id()
        self._open_orders_list.append({
            "orderId": oid,
            "symbol": symbol.upper(),
            "side": side,
            "type": order_type,
            "price": str(price),
            "origQty": str(orig_qty),
            "executedQty": str(executed_qty),
            "status": status,
            "cumQuote": str(price * executed_qty),
            "reduceOnly": False,
        })
        return oid

    def add_algo_order(self, algo_id: int = None, symbol: str = "BTCUSDT",
                       algo_type: str = "STOP_LOSS", trigger_price: float = 99.0,
                       executed_qty: float = 0.0, status: str = "NEW"):
        """Add a mock algo order (TP/SL via Algo API)."""
        aid = algo_id or self._next_algo_id()
        self._algo_orders_list.append({
            "algoId": aid,
            "symbol": symbol.upper(),
            "algoType": algo_type,
            "algoStatus": status,
            "triggerPrice": str(trigger_price),
            "executedQty": str(executed_qty),
            "totalQty": str(executed_qty if executed_qty > 0 else 1.0),
        })
        return aid

    def _next_order_id(self):
        self._order_id_counter += 1
        return self._order_id_counter

    def _next_algo_id(self):
        self._algo_id_counter += 1
        return self._algo_id_counter

    # ── Mocked API methods ──────────────────────────────────

    def get_exchange_info(self) -> dict:
        if self._exchange_info:
            return self._exchange_info
        # Provide a minimal realistic exchange info
        symbols = []
        for sym in ["BTCUSDT", "ETHUSDT", "DOGEUSDT", "FARTCOINUSDT"]:
            base = sym.replace("USDT", "")
            symbols.append({
                "symbol": sym,
                "contractType": "PERPETUAL",
                "status": "TRADING",
                "baseAsset": base,
                "quoteAsset": "USDT",
                "pricePrecision": 8 if base in ("DOGE", "FARTCOIN") else 2,
                "quantityPrecision": 8,
                "filters": [
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "1" if base in ("DOGE", "FARTCOIN") else "0.001",
                        "maxQty": "1000000",
                        "stepSize": "1" if base in ("DOGE", "FARTCOIN") else "0.001",
                    },
                    {
                        "filterType": "PRICE_FILTER",
                        "tickSize": "0.00001" if base in ("DOGE", "FARTCOIN") else "0.01",
                        "minPrice": "0.00001",
                        "maxPrice": "1000000",
                    },
                ],
            })
        return {"symbols": symbols, "timezone": "UTC", "serverTime": int(time.time() * 1000)}

    def get_klines(self, symbol: str, interval: str = "1h",
                   start_time: int = None, end_time: int = None,
                   limit: int = 500) -> list:
        """Return mock kline data."""
        price = self.get_default_price(symbol)
        now_ms = int(time.time() * 1000)
        hour_ms = 3600000
        candles = []
        for i in range(min(limit, 100)):
            ts = now_ms - (limit - i) * hour_ms
            noise = (i % 5 - 2) * 0.001 * price
            candles.append({
                "ts": ts,
                "o": price + noise,
                "h": price + noise * 1.5,
                "l": price - noise * 0.5,
                "c": price + noise * 0.8,
                "v": 1000 + i * 10,
            })
        if start_time:
            candles = [c for c in candles if c["ts"] >= start_time]
        if end_time:
            candles = [c for c in candles if c["ts"] <= end_time]
        return candles

    def get_ticker_price(self, symbol: str) -> float:
        return self.get_default_price(symbol)

    def get_usdt_balance(self) -> float:
        return self._balance

    def get_balance(self) -> list:
        return [{"asset": "USDT", "availableBalance": str(self._balance)}]

    def get_positions(self) -> list:
        return self._positions

    def get_position_for_symbol(self, symbol: str) -> Optional[dict]:
        for p in self._positions:
            if p["symbol"] == symbol.upper():
                return p
        return None

    def get_open_orders(self, symbol: str = None) -> list:
        if symbol:
            return [o for o in self._open_orders_list if o["symbol"] == symbol.upper()]
        return list(self._open_orders_list)

    def get_open_algo_orders(self, symbol: str = None) -> list:
        if symbol:
            return [a for a in self._algo_orders_list if a["symbol"] == symbol.upper()]
        return self._algo_orders_list

    def get_order_status(self, symbol: str, order_id: int) -> dict:
        for o in self._open_orders_list:
            if o["orderId"] == order_id:
                return o
        return {"orderId": order_id, "symbol": symbol.upper(), "status": "CANCELED",
                "executedQty": "0", "cumQuote": "0", "price": "0"}

    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        oid = self._next_order_id()
        price = self.get_default_price(symbol)
        order = {
            "orderId": oid,
            "symbol": symbol.upper(),
            "side": side,
            "type": "MARKET",
            "status": "FILLED",
            "executedQty": str(quantity),
            "cumQuote": str(quantity * price),
            "price": str(price),
            "origQty": str(quantity),
        }
        self._orders.append(order)
        return order

    def place_limit_order(self, symbol: str, side: str, quantity: float,
                          price: float, reduce_only: bool = False,
                          time_in_force: str = "GTC") -> dict:
        oid = self._next_order_id()
        order = {
            "orderId": oid,
            "symbol": symbol.upper(),
            "side": side,
            "type": "LIMIT",
            "status": "NEW",
            "executedQty": "0",
            "cumQuote": "0",
            "price": str(price),
            "origQty": str(quantity),
            "timeInForce": time_in_force,
            "reduceOnly": reduce_only,
        }
        self._open_orders_list.append(order)
        return order

    def place_algo_order(self, symbol: str, side: str, order_type: str,
                         quantity: float, price: float = None,
                         stop_price: float = None) -> dict:
        aid = self._next_algo_id()
        algo = {
            "algoId": aid,
            "symbol": symbol.upper(),
            "side": side,
            "algoType": order_type,
            "algoStatus": "NEW",
            "triggerPrice": str(stop_price or price or 0),
            "executedQty": "0",
            "totalQty": str(quantity),
        }
        self._algo_orders_list.append(algo)
        return {"data": [algo], "algoId": aid}

    def place_tp_sl_orders(self, symbol: str, side: str, quantity: float,
                           tp_price: float, sl_price: float) -> dict:
        """Place TP and SL orders."""
        tp_side = "SELL" if side == "LONG" else "BUY"
        tp_order = self.place_limit_order(symbol, tp_side, quantity, tp_price, reduce_only=True)
        try:
            sl_resp = self.place_algo_order(symbol, tp_side, "STOP_LOSS", quantity, stop_price=sl_price)
            sl_order = {"orderId": sl_resp.get("algoId")}
        except Exception:
            sl_order = None
        return {"tp_order": tp_order, "sl_order": sl_order}

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        self._open_orders_list = [o for o in self._open_orders_list if o["orderId"] != order_id]
        return {"status": "CANCELED"}

    def cancel_all_orders(self, symbol: str) -> list:
        self._open_orders_list = [o for o in self._open_orders_list if o["symbol"] != symbol.upper()]
        return []

    def cancel_algo_order(self, symbol: str, algo_order_id: int) -> dict:
        self._algo_orders_list = [a for a in self._algo_orders_list if a.get("algoId") != algo_order_id]
        return {"status": "CANCELED"}

    def get_lot_size_info(self, symbol: str) -> dict:
        info = self.get_exchange_info()
        for s in info.get("symbols", []):
            if s["symbol"] == symbol.upper():
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        return {
                            "minQty": float(f["minQty"]),
                            "maxQty": float(f["maxQty"]),
                            "stepSize": float(f["stepSize"]),
                        }
        return {}

    def get_price_precision(self, symbol: str) -> int:
        info = self.get_exchange_info()
        for s in info.get("symbols", []):
            if s["symbol"] == symbol.upper():
                return s.get("pricePrecision", 8)
        return 8

    def get_quantity_precision(self, symbol: str) -> int:
        info = self.get_exchange_info()
        for s in info.get("symbols", []):
            if s["symbol"] == symbol.upper():
                return s.get("quantityPrecision", 8)
        return 8

    def get_price_filter(self, symbol: str) -> dict:
        info = self.get_exchange_info()
        for s in info.get("symbols", []):
            if s["symbol"] == symbol.upper():
                for f in s.get("filters", []):
                    if f["filterType"] == "PRICE_FILTER":
                        return {
                            "tickSize": float(f["tickSize"]),
                            "minPrice": float(f["minPrice"]),
                            "maxPrice": float(f["maxPrice"]),
                        }
        return {}

    def round_price(self, symbol: str, price: float) -> float:
        pf = self.get_price_filter(symbol)
        if not pf or pf.get("tickSize", 0) <= 0:
            precision = self.get_price_precision(symbol)
            return round(price, precision)
        tick_size = pf["tickSize"]
        precision = len(str(tick_size).split(".")[-1]) if "." in str(tick_size) else 8
        rounded = (price // tick_size) * tick_size
        return round(rounded, precision)

    def round_quantity(self, symbol: str, quantity: float) -> float:
        lot_info = self.get_lot_size_info(symbol)
        if not lot_info:
            return quantity
        step = lot_info.get("stepSize", 0.001)
        precision = len(str(step).split(".")[-1]) if "." in str(step) else 8
        return round(quantity - (quantity % step), 8)

    def get_all_klines_range(self, symbol: str, interval: str,
                              start_time: int, end_time: int) -> list:
        """Mock getting all klines in a time range."""
        return self.get_klines(symbol, interval, start_time=start_time, limit=1500)

    def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        """Mock order book."""
        price = self.get_default_price(symbol)
        # Create mock order book with small spread
        ask_price = price * 1.0001
        bid_price = price * 0.9999
        return {
            "asks": [[str(ask_price), "1000"]],
            "bids": [[str(bid_price), "1000"]],
        }


@pytest.fixture
def mock_demo_client():
    """Provide a fresh MockBinanceClient configured as demo."""
    client = MockBinanceClient(use_demo=True)
    return client


@pytest.fixture
def mock_data_client():
    """Provide a fresh MockBinanceClient configured as data."""
    client = MockBinanceClient(use_demo=False)
    return client


@pytest.fixture(autouse=True)
def _patch_binance_clients(mock_demo_client, mock_data_client):
    """
    Auto-use fixture that patches get_demo_client() and get_data_client()
    at every import location so locally-imported references also get the mock.
    """
    import backend.api.binance as binance_module

    # These modules import get_demo_client / get_data_client at module level.
    # Patching at the definition site (binance_module) is not enough — each
    # import creates a local reference. We must patch each module's namespace.
    _demo_client_modules = [
        "backend.trading.order_manager",
        "backend.trading.entry_manager",
        "backend.trading.exit_manager",
        "backend.trading.tp_sl_manager",
        "backend.trading.reconciliation",
        "backend.api.binance",
    ]
    _data_client_modules = [
        "backend.core.signal",
        "backend.core.data_fetcher",
        "backend.api.binance",
    ]

    patchers = []
    for mod in _demo_client_modules:
        patchers.append(patch(f"{mod}.get_demo_client", return_value=mock_demo_client))
    for mod in _data_client_modules:
        patchers.append(patch(f"{mod}.get_data_client", return_value=mock_data_client))

    for p in patchers:
        p.start()
    yield
    for p in patchers:
        p.stop()


# ─── Test Data Factories ───────────────────────────────────

def make_trade_row(coin: str = "DOGEUSDT", side: str = "LONG",
                   entry_price: float = 0.12, tp_price: float = 0.1212,
                   sl_price: float = 0.1194, position_size: float = 10.0,
                   status: str = "open", pnl_usdt: float = None,
                   exit_reason: str = None, btc_return_pct: float = 1.5,
                   trigger_time: str = None):
    """Create a trade record dict for test assertions."""
    import random
    now_ist = (datetime.now(timezone.utc) + timedelta(hours=5.5)).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "coin": coin,
        "side": side,
        "entry_price": entry_price,
        "tp_price": tp_price,
        "sl_price": sl_price,
        "position_size": position_size,
        "status": status,
        "btc_return_pct": btc_return_pct,
        "trigger_time": trigger_time or now_ist,
        "exit_price": sl_price if status == "closed" else None,
        "exit_time": now_ist if status == "closed" else None,
        "pnl_usdt": pnl_usdt,
        "pnl_pct": ((sl_price - entry_price) / entry_price * 100) if status == "closed" and pnl_usdt is not None else None,
        "exit_reason": exit_reason,
    }


def seed_trade(conn: sqlite3.Connection, **kwargs):
    """Insert a trade record into the database for testing."""
    data = make_trade_row(**kwargs)
    trigger_time = data.pop("trigger_time")
    conn.execute(
        "INSERT INTO trades (trigger_time, coin, side, btc_return_pct, "
        "entry_price, tp_price, sl_price, position_size, status, "
        "exit_price, exit_time, pnl_usdt, exit_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (trigger_time, data["coin"], data["side"], data["btc_return_pct"],
         data["entry_price"], data["tp_price"], data["sl_price"], data["position_size"],
         data["status"], data["exit_price"], data["exit_time"], data["pnl_usdt"],
         data["exit_reason"])
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# Import time for kline timestamps
import time
