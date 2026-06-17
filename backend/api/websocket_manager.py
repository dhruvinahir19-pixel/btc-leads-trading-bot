"""
websocket_manager.py — Binance Futures WebSocket stream manager.

Subscribes to real-time market data streams so the bot NEVER needs to
call REST endpoints for live data (prices, tickers, klines).

Runs as a background daemon thread using the synchronous
websocket-client library (not async websockets).

Streams subscribed:
  - btcusdt@kline_1h   → latest closed BTC 1H candle (for signal triggers)
  - btcusdt@ticker      → live BTC price (for dashboard)
  - !ticker@arr         → live prices for ALL symbols (for future use)

Auto-reconnects on disconnect with 5s delay.
"""
import json
import threading
import time
from typing import Optional

import websocket

from backend.logging_setup import get_logger

logger = get_logger("ws")

# ─── Constants ──────────────────────────────────────────────
# Binance Futures WebSocket base URL (USD-M futures)
WSS_BASE = "wss://fstream.binance.com/stream"

# Streams to subscribe to (combined stream URL format)
STREAMS = "btcusdt@kline_1h/btcusdt@ticker/!ticker@arr"

# Reconnect delay after unexpected disconnect (seconds)
RECONNECT_DELAY = 5

# ─── Thread-Safe Shared State ───────────────────────────────
# All state is protected by _lock. Reads and writes are atomic.
_lock = threading.Lock()

# Latest BTC price from btcusdt@ticker stream (updated ~every 250ms)
_btc_price: float = 0.0

# Latest BTC 1H candle that has CLOSED (x: true from kline stream)
# Set only when the candle closes, not on partial updates.
_btc_candle: Optional[dict] = None

# Previous BTC 1H candle (the one before the latest closed one)
# Needed to calculate return % between consecutive candles.
_prev_btc_candle: Optional[dict] = None

# All symbol prices from !ticker@arr stream (updated ~every 250ms)
_all_prices: dict = {}

# Connection state
_connected: bool = False
_ws: Optional[websocket.WebSocketApp] = None
_should_stop: bool = False


# ─── Callbacks ──────────────────────────────────────────────

def _on_message(ws, message: str):
    """Handle incoming WebSocket message from combined stream."""
    global _btc_price, _btc_candle, _prev_btc_candle, _all_prices

    try:
        data = json.loads(message)
        stream = data.get('stream', '')
        payload = data.get('data', {})

        if stream == 'btcusdt@kline_1h':
            k = payload.get('k', {})
            if k.get('x', False):  # Candle is closed (x: true)
                new_candle = {
                    'ts': k['t'],  # Open time in ms
                    'o': float(k['o']),
                    'h': float(k['h']),
                    'l': float(k['l']),
                    'c': float(k['c']),
                    'v': float(k['v']),
                }
                with _lock:
                    # Shift current candle to prev, replace with new
                    if _btc_candle is not None:
                        _prev_btc_candle = _btc_candle
                    _btc_candle = new_candle
                logger.debug(f"WS kline closed: BTC={new_candle['c']:.2f}")

        elif stream == 'btcusdt@ticker':
            price = float(payload.get('c', 0))
            with _lock:
                _btc_price = price

        elif stream == '!ticker@arr':
            if isinstance(payload, list):
                prices = {}
                for item in payload:
                    try:
                        prices[item['s']] = float(item['c'])
                    except (KeyError, ValueError, TypeError):
                        pass
                with _lock:
                    _all_prices = prices

    except Exception as e:
        logger.debug(f"WS message parse error: {e}")


def _on_open(ws):
    """Handle WebSocket connection opened."""
    global _connected
    with _lock:
        _connected = True
    logger.info("WebSocket connected to Binance Futures")


def _on_close(ws, close_status_code, close_msg):
    """Handle WebSocket connection closed."""
    global _connected
    with _lock:
        _connected = False
    logger.info(f"WebSocket closed (code={close_status_code})")


def _on_error(ws, error):
    """Handle WebSocket error (non-fatal, run_forever continues)."""
    logger.debug(f"WebSocket error: {error}")


# ─── Connection Loop ────────────────────────────────────────

def _run_loop():
    """Main WebSocket loop with auto-reconnect.

    Uses a blocking loop around ws.run_forever(). When the connection
    drops, run_forever() returns and the loop reconnects after 5s.
    """
    global _ws
    while not _should_stop:
        try:
            # Combined stream URL: / between streams is the DELIMITER, NOT a path
            # Do NOT URL-encode the slashes — Binance expects raw / between streams.
            # Characters @ and ! are accepted as-is by Binance's server.
            url = f"{WSS_BASE}?streams={STREAMS}"

            _ws = websocket.WebSocketApp(
                url,
                on_message=_on_message,
                on_open=_on_open,
                on_close=_on_close,
                on_error=_on_error,
            )
            # run_forever blocks the thread until disconnect
            _ws.run_forever(ping_interval=30, ping_timeout=10)

        except Exception as e:
            logger.warning(f"WebSocket connection error: {e}")

        # Reconnect loop
        if not _should_stop:
            logger.info(f"WebSocket reconnecting in {RECONNECT_DELAY}s...")
            for _ in range(RECONNECT_DELAY):
                if _should_stop:
                    break
                time.sleep(1)


# ─── Public API ─────────────────────────────────────────────

def start():
    """Start the WebSocket daemon thread.

    Spawns a single daemon thread that connects to Binance Futures
    WebSocket and maintains the shared state. Call this once at
    application startup (in lifespan).
    """
    global _should_stop
    _should_stop = False
    thread = threading.Thread(target=_run_loop, daemon=True, name="ws-manager")
    thread.start()
    logger.info("WebSocket manager daemon thread started")


def stop():
    """Signal the WebSocket thread to stop and close the connection."""
    global _should_stop, _ws
    _should_stop = True
    if _ws:
        try:
            _ws.close()
        except Exception:
            pass
    logger.info("WebSocket manager stopped")


def get_btc_price() -> float:
    """Get the latest BTC price from the live WebSocket stream.

    Returns 0.0 if no data received yet (connection not established).
    """
    with _lock:
        return _btc_price


def get_all_prices() -> dict:
    """Get latest prices for ALL symbols from the !ticker@arr stream.

    Returns:
        Dict of {symbol: price}, e.g. {"BTCUSDT": 73260.0, "ETHUSDT": 3450.5}
        Empty dict if no data received yet.
    """
    with _lock:
        return dict(_all_prices)


def get_btc_candle() -> Optional[dict]:
    """Get the latest CLOSED BTC 1H candle from the WebSocket.

    Only returns candles that have fully closed (x: true from kline stream).
    Returns None if no candle has been received yet.

    Candle dict keys: ts, o, h, l, c, v
    """
    with _lock:
        return _btc_candle


def get_prev_btc_candle() -> Optional[dict]:
    """Get the PREVIOUS closed BTC 1H candle (before the latest).

    Needed to calculate the return % between consecutive candles.
    Returns None if only one candle has been received so far.
    """
    with _lock:
        return _prev_btc_candle


def is_connected() -> bool:
    """Check if the WebSocket is currently connected and receiving data."""
    with _lock:
        return _connected
