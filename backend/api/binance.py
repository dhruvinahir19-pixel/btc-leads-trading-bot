"""
binance.py - Binance Futures API Client.
Dual-key support: Real API for data fetching, Demo API for order placement.
All methods include retry logic, rate limit awareness, and error handling.
"""
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.config import (
    BINANCE_API_KEY, BINANCE_API_SECRET,
    BINANCE_DEMO_KEY, BINANCE_DEMO_SECRET,
    BASE_URL, BASE_URL_TESTNET, SCAN_MAX_SYMBOLS,
)

# ─── Constants ──────────────────────────────────────────────
RECV_WINDOW = 5000  # 5 seconds
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
REQUEST_TIMEOUT = 15


def _log_warning(symbol: str, message: str):
    """Simple logger for the API client (avoids circular imports)."""
    import sys
    print(f"[WARNING] {symbol}: {message}", file=sys.stderr)


class BinanceError(Exception):
    """Custom exception for Binance API errors."""
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Binance API Error [{status_code}]: {body}")


class BinanceClient:
    """
    Binance Futures API client.
    
    Args:
        use_demo: If True, uses demo API keys for order placement.
                  If False, uses real API keys for data fetching.
    """
    
    def __init__(self, use_demo: bool = False):
        self.use_demo = use_demo
        
        if use_demo:
            self.base_url = BASE_URL_TESTNET  # Testnet for paper trading
            self.api_key = BINANCE_DEMO_KEY
            self.api_secret = BINANCE_DEMO_SECRET
        else:
            self.base_url = BASE_URL  # Mainnet for real data
            self.api_key = BINANCE_API_KEY
            self.api_secret = BINANCE_API_SECRET
    
    # ─── Request Helpers ─────────────────────────────────────
    
    def _sign(self, params: dict) -> dict:
        """Add signature to params dict. Returns the signed params."""
        if not self.api_secret:
            raise BinanceError(0, "API secret not configured. Check .env file.")
        
        query = urllib.parse.urlencode(params)
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        params['signature'] = signature
        return params
    
    def _request(self, method: str, path: str, params: Optional[dict] = None,
                 signed: bool = False) -> dict:
        """Make an HTTP request to Binance API with retry logic."""
        url = f"{self.base_url}{path}"
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        
        if self.api_key:
            headers['X-MBX-APIKEY'] = self.api_key
        
        if params is None:
            params = {}
        
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            params['recvWindow'] = RECV_WINDOW
            params = self._sign(params)
        
        query = urllib.parse.urlencode(params)
        if query:
            url = f"{url}?{query}"
        
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(url, headers=headers, method=method)
                resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
                raw = resp.read().decode('utf-8', errors='replace')
                
                # Check for Binance error codes in response
                data = json.loads(raw)
                if isinstance(data, dict) and 'code' in data and data['code'] < 0:
                    raise BinanceError(data['code'], data.get('msg', 'Unknown error'))
                
                return data
            
            except urllib.error.HTTPError as e:
                body = e.read().decode('utf-8', errors='replace')
                last_error = BinanceError(e.code, body)
                
                # Rate limit (429) or IP banned (418) or server error (5xx) -> retry
                if e.code in (408, 429, 418, 500, 502, 503, 504):
                    if attempt < MAX_RETRIES - 1:
                        # Parse Retry-After header if present (Binance sends it on 418/429)
                        retry_after = e.headers.get('Retry-After')
                        if retry_after:
                            try:
                                wait = int(retry_after)
                            except (ValueError, TypeError):
                                wait = RETRY_DELAY * (attempt + 1)
                            else:
                                _log_warning('binance',
                                             f"Rate limited. Waiting {wait}s (Retry-After header)")
                            time.sleep(wait)
                        else:
                            time.sleep(RETRY_DELAY * (attempt + 1))
                        continue
                else:
                    # Other errors (400, 401, 403) -> don't retry
                    break
            
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_error = BinanceError(0, str(e))
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                break
        
        raise last_error or BinanceError(0, "Max retries exceeded")
    
    def _get(self, path: str, params: Optional[dict] = None,
             signed: bool = False) -> dict:
        """GET request."""
        return self._request('GET', path, params, signed)
    
    def _post(self, path: str, params: Optional[dict] = None,
              signed: bool = False) -> dict:
        """POST request."""
        return self._request('POST', path, params, signed)
    
    def _delete(self, path: str, params: Optional[dict] = None,
                signed: bool = False) -> dict:
        """DELETE request."""
        return self._request('DELETE', path, params, signed)
    
    # ─── Market Data Endpoints ──────────────────────────────
    
    def get_exchange_info(self) -> dict:
        """Get exchange info - all trading pairs and their details."""
        return self._get('/fapi/v1/exchangeInfo')
    
    def get_klines(self, symbol: str, interval: str = '1h',
                   start_time: Optional[int] = None,
                   end_time: Optional[int] = None,
                   limit: int = 500) -> list:
        """
        Get kline/candlestick data.
        
        Args:
            symbol: e.g., 'BTCUSDT'
            interval: '1h', '4h', '1d', etc.
            start_time: milliseconds timestamp
            end_time: milliseconds timestamp
            limit: max 1500
        
        Returns:
            List of candle dicts with keys: ts, o, h, l, c, v
        """
        params = {'symbol': symbol.upper(), 'interval': interval, 'limit': min(limit, 1500)}
        if start_time:
            params['startTime'] = start_time
        if end_time:
            params['endTime'] = end_time
        
        data = self._get('/fapi/v1/klines', params)
        
        # Convert to dict list
        candles = []
        for c in data:
            candles.append({
                'ts': int(c[0]),
                'o': float(c[1]),
                'h': float(c[2]),
                'l': float(c[3]),
                'c': float(c[4]),
                'v': float(c[5]),
            })
        return candles
    
    def get_all_klines_range(self, symbol: str, interval: str,
                              start_time: int, end_time: int) -> list:
        """
        Get all klines in a time range, handling pagination.
        
        Uses limit=500 instead of max 1500 to keep per-call API weight
        at 2 (vs 10 for limit>1000). This prevents IP bans from
        rate limiting during the weekly 527-coin scan.
        
        Args:
            symbol: e.g., 'BTCUSDT'
            interval: '1h', '4h', etc.
            start_time: milliseconds timestamp
            end_time: milliseconds timestamp
        
        Returns:
            List of all candles in the range
        """
        all_candles = []
        current = start_time
        
        while current < end_time:
            candles = self.get_klines(symbol, interval, start_time=current,
                                      end_time=end_time, limit=500)
            if not candles:
                break
            all_candles.extend(candles)
            current = candles[-1]['ts'] + 1
            # Rate limit courtesy delay between paginated calls
            if current < end_time:
                time.sleep(0.2)
        
        return all_candles
    
    def get_ticker_price(self, symbol: str) -> float:
        """Get current price for a symbol."""
        data = self._get('/fapi/v1/ticker/price', {'symbol': symbol.upper()})
        return float(data['price'])
    
    def get_ticker_24hr(self, symbol: str) -> dict:
        """Get 24hr ticker stats."""
        return self._get('/fapi/v1/ticker/24hr', {'symbol': symbol.upper()})
    
    def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        """Get order book for a symbol."""
        return self._get('/fapi/v1/depth', {'symbol': symbol.upper(), 'limit': limit})
    
    # ─── Account Endpoints (Signed) ─────────────────────────
    
    def get_account_info(self) -> dict:
        """Get account information including balances."""
        return self._get('/fapi/v2/account', signed=True)
    
    def get_balance(self) -> list:
        """Get wallet balances."""
        data = self._get('/fapi/v2/account', signed=True)
        return data.get('assets', [])
    
    def get_usdt_balance(self) -> float:
        """Get available USDT balance."""
        balances = self.get_balance()
        for asset in balances:
            if asset['asset'] == 'USDT':
                return float(asset['availableBalance'])
        return 0.0
    
    def get_positions(self) -> list:
        """Get current open positions."""
        data = self._get('/fapi/v2/account', signed=True)
        positions = data.get('positions', [])
        # Filter to only positions with non-zero amount
        return [p for p in positions if abs(float(p.get('positionAmt', 0))) > 0]
    
    def get_position_for_symbol(self, symbol: str) -> Optional[dict]:
        """Get position for a specific symbol, or None if no position."""
        positions = self.get_positions()
        for p in positions:
            if p['symbol'] == symbol.upper():
                return p
        return None
    
    # ─── Order Endpoints (Signed, Demo API) ─────────────────
    
    def place_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        """
        Place a market order.
        
        Args:
            symbol: e.g., 'FARTCOINUSDT'
            side: 'BUY' or 'SELL'
            quantity: in coin units (not USDT)
        
        Returns:
            Order response dict
        """
        # Round quantity to valid step size
        try:
            quantity = self.round_quantity(symbol, quantity)
        except Exception:
            pass

        params = {
            'symbol': symbol.upper(),
            'side': side.upper(),
            'type': 'MARKET',
            'quantity': quantity,
        }
        return self._post('/fapi/v1/order', params, signed=True)
    
    def place_limit_order(self, symbol: str, side: str, quantity: float,
                          price: float, reduce_only: bool = False,
                          time_in_force: str = 'GTC') -> dict:
        """
        Place a limit order.
        
        Args:
            symbol: e.g., 'FARTCOINUSDT'
            side: 'BUY' or 'SELL'
            quantity: in coin units
            price: limit price (will be rounded to valid tick size)
            reduce_only: if True, only reduces position
            time_in_force: 'GTC' (good till cancelled) or 'IOC' (immediate or cancel)
        
        Returns:
            Order response dict
        """
        # Round price to valid tick size
        try:
            price = self.round_price(symbol, price)
        except Exception:
            pass

        params = {
            'symbol': symbol.upper(),
            'side': side.upper(),
            'type': 'LIMIT',
            'timeInForce': time_in_force,
            'quantity': quantity,
            'price': price,
        }
        if reduce_only:
            params['reduceOnly'] = 'true'
        
        return self._post('/fapi/v1/order', params, signed=True)
    
    def place_algo_order(self, symbol: str, side: str, order_type: str,
                           quantity: float, price: float = None,
                           stop_price: float = None) -> dict:
        """
        Place an Algo order via the Binance Futures Algo Order API.
        
        This is required for STOP_LOSS and TAKE_PROFIT order types
        (Binance Futures deprecated regular STOP_MARKET on /fapi/v1/order).
        
        Args:
            symbol: e.g., 'FARTCOINUSDT'
            side: 'BUY' or 'SELL'
            order_type: 'TAKE_PROFIT' or 'STOP_LOSS'
            quantity: in coin units
            price: required for TAKE_PROFIT (limit price)
            stop_price: required for STOP_LOSS (trigger price)
        
        Returns:
            Order response dict from Algo Order API
        """
        params = {
            'symbol': symbol.upper(),
            'side': side.upper(),
            'type': order_type.upper(),
            'quantity': quantity,
            'reduceOnly': 'true',
        }
        if price is not None:
            try:
                price = self.round_price(symbol, price)
            except Exception:
                pass
            params['price'] = price
        if stop_price is not None:
            try:
                stop_price = self.round_price(symbol, stop_price)
            except Exception:
                pass
            params['stopPrice'] = stop_price
        
        return self._post('/fapi/v1/algo/order', params, signed=True)

    def cancel_algo_order(self, symbol: str, algo_order_id: int) -> dict:
        """Cancel an Algo order (TP/SL placed via /fapi/v1/algo/order)."""
        params = {
            'symbol': symbol.upper(),
            'algoId': algo_order_id,
        }
        return self._delete('/fapi/v1/algo/order', params, signed=True)

    def get_open_algo_orders(self, symbol: str = None) -> list:
        """Get all open Algo orders (TP/SL orders)."""
        params = {}
        if symbol:
            params['symbol'] = symbol.upper()
        data = self._get('/fapi/v1/algo/openOrders', params, signed=True)
        return data.get('data', []) if isinstance(data, dict) else data

    def place_tp_sl_orders(self, symbol: str, side: str, quantity: float,
                           tp_price: float, sl_price: float) -> dict:
        """
        Place TP and SL orders simultaneously.
        
        Strategy:
        - TP uses regular LIMIT reduceOnly order (works on all environments)
        - SL tries Algo Order API (STOP_LOSS) first (required by mainnet,
          returns -4120 if regular STOP_MARKET endpoint is used)
        - Falls back to regular STOP_MARKET if Algo API unavailable
          (testnet may not support Algo endpoint, returns -5000)
        
        For LONG: TP = SELL LIMIT at tp_price, SL = SELL at sl_price
        For SHORT: TP = BUY LIMIT at tp_price, SL = BUY at sl_price
        
        Returns:
            Dict with 'tp_order', 'sl_order' responses, and 'error' or None
        """
        tp_side = 'SELL' if side == 'LONG' else 'BUY'
        sl_side = 'SELL' if side == 'LONG' else 'BUY'

        # Round prices to valid tick sizes
        try:
            tp_price = self.round_price(symbol, tp_price)
            sl_price = self.round_price(symbol, sl_price)
        except Exception:
            pass

        # 1. Place TP as regular LIMIT reduceOnly order
        try:
            tp_response = self.place_limit_order(
                symbol=symbol,
                side=tp_side,
                quantity=quantity,
                price=tp_price,
                reduce_only=True,
                time_in_force='GTC',
            )
        except BinanceError as e:
            return {'tp_order': None, 'sl_order': None, 'error': f"TP failed: {e}"}

        # 2. Place SL - try Algo API first, fallback to STOP_MARKET
        sl_response = None
        sl_error = None

        # Strategy A: Try Algo Order API (STOP_LOSS) - required on mainnet
        try:
            sl_response = self.place_algo_order(
                symbol=symbol,
                side=sl_side,
                order_type='STOP_LOSS',
                quantity=quantity,
                stop_price=sl_price,
            )
        except BinanceError as e:
            # -5000 = Algo API path not found (testnet limitation)
            # -2010 = filter failure (e.g., price tick issues)
            if e.status_code == 404 or ('-5000' in str(e)):
                sl_error = f"algo_api_unavailable: {e}"
            else:
                sl_error = str(e)

        # Strategy B: Fallback to regular STOP_MARKET if Algo API unavailable
        if sl_response is None:
            try:
                sl_params = {
                    'symbol': symbol.upper(),
                    'side': sl_side,
                    'type': 'STOP_MARKET',
                    'quantity': quantity,
                    'stopPrice': sl_price,
                    'reduceOnly': 'true',
                }
                sl_response = self._post('/fapi/v1/order', sl_params, signed=True)
            except BinanceError as e:
                sl_error = f"both_algo_and_stop_market_failed: {e}"

        if sl_error and sl_response is None:
            # SL placement failed on both Algo API and STOP_MARKET.
            # This is common on testnets. Do NOT cancel the TP order -
            # the in-app monitored SL in exit_manager will protect the position.
            _log_warning(symbol,
                         "SL exchange order not supported on this environment. "
                         "Using in-app monitored SL instead. TP order placed OK.")
            return {
                'tp_order': tp_response,
                'sl_order': None,
                'sl_fallback': 'in_app_monitoring',
                'warning': sl_error,
            }

        return {
            'tp_order': tp_response,
            'sl_order': sl_response,
            'sl_fallback': None,
        }
    
    def cancel_order(self, symbol: str, order_id: int) -> dict:
        """Cancel an open order."""
        params = {
            'symbol': symbol.upper(),
            'orderId': order_id,
        }
        return self._delete('/fapi/v1/order', params, signed=True)
    
    def cancel_all_orders(self, symbol: str) -> list:
        """Cancel all open orders for a symbol."""
        params = {'symbol': symbol.upper()}
        return self._delete('/fapi/v1/allOpenOrders', params, signed=True)
    
    def get_open_orders(self, symbol: Optional[str] = None) -> list:
        """Get all open orders, optionally filtered by symbol."""
        params = {}
        if symbol:
            params['symbol'] = symbol.upper()
        return self._get('/fapi/v1/openOrders', params, signed=True)
    
    def get_order_status(self, symbol: str, order_id: int) -> dict:
        """Check order status."""
        params = {
            'symbol': symbol.upper(),
            'orderId': order_id,
        }
        return self._get('/fapi/v1/order', params, signed=True)
    
    # ─── Utility ────────────────────────────────────────────
    
    def get_lot_size_info(self, symbol: str) -> dict:
        """Get lot size filters for a symbol (min/max qty, step size)."""
        info = self.get_exchange_info()
        for s in info.get('symbols', []):
            if s['symbol'] == symbol.upper():
                for f in s.get('filters', []):
                    if f['filterType'] == 'LOT_SIZE':
                        return {
                            'minQty': float(f['minQty']),
                            'maxQty': float(f['maxQty']),
                            'stepSize': float(f['stepSize']),
                        }
                return {}
        return {}
    
    def round_quantity(self, symbol: str, quantity: float) -> float:
        """Round quantity to valid step size for the symbol."""
        lot_info = self.get_lot_size_info(symbol)
        if not lot_info:
            return quantity
        step = lot_info.get('stepSize', 0.001)
        return round(quantity - (quantity % step), 8)
    
    def get_price_precision(self, symbol: str) -> int:
        """Get price precision (number of decimals) for a symbol."""
        info = self.get_exchange_info()
        for s in info.get('symbols', []):
            if s['symbol'] == symbol.upper():
                return s.get('pricePrecision', 8)
        return 8
    
    def get_quantity_precision(self, symbol: str) -> int:
        """Get quantity precision for a symbol."""
        info = self.get_exchange_info()
        for s in info.get('symbols', []):
            if s['symbol'] == symbol.upper():
                return s.get('quantityPrecision', 8)
        return 8

    def get_price_filter(self, symbol: str) -> dict:
        """Get price filter (tickSize) for a symbol.
        
        Returns dict with 'tickSize' or empty dict if not found.
        """
        info = self.get_exchange_info()
        for s in info.get('symbols', []):
            if s['symbol'] == symbol.upper():
                for f in s.get('filters', []):
                    if f['filterType'] == 'PRICE_FILTER':
                        return {
                            'tickSize': float(f['tickSize']),
                            'minPrice': float(f['minPrice']),
                            'maxPrice': float(f['maxPrice']),
                        }
                return {}
        return {}

    def round_price(self, symbol: str, price: float) -> float:
        """Round price to valid tick size for the symbol.
        
        Binance requires limit/stop prices to be multiples of
        the symbol's tickSize (e.g., 0.000010 for DOGEUSDT).
        """
        pf = self.get_price_filter(symbol)
        if not pf or pf.get('tickSize', 0) <= 0:
            # Fallback to pricePrecision rounding
            precision = self.get_price_precision(symbol)
            return round(price, precision)
        tick_size = pf['tickSize']
        precision = len(str(tick_size).split('.')[-1]) if '.' in str(tick_size) else 8
        # Round down to nearest valid tick
        rounded = (price // tick_size) * tick_size
        return round(rounded, precision)


# ─── Singleton instances ───────────────────────────────────

_data_client: Optional[BinanceClient] = None
_demo_client: Optional[BinanceClient] = None


def get_data_client() -> BinanceClient:
    """Get or create the data (real API) client."""
    global _data_client
    if _data_client is None:
        _data_client = BinanceClient(use_demo=False)
    return _data_client


def get_demo_client() -> BinanceClient:
    """Get or create the demo (order) client."""
    global _demo_client
    if _demo_client is None:
        _demo_client = BinanceClient(use_demo=True)
    return _demo_client


# ─── Test function ─────────────────────────────────────────

def test_connection() -> dict:
    """Test both API connections and return status."""
    results = {'data_api': False, 'demo_api': False, 'usdt_balance': 0, 'positions': 0}
    
    try:
        dc = get_data_client()
        info = dc.get_exchange_info()
        symbols = [s for s in info.get('symbols', [])
                   if s.get('contractType') == 'PERPETUAL' and s.get('quoteAsset') == 'USDT']
        results['data_api'] = True
        results['total_pairs'] = len(symbols)
        results['btc_price'] = dc.get_ticker_price('BTCUSDT')
    except Exception as e:
        results['data_error'] = str(e)
    
    try:
        dc = get_demo_client()
        balance = dc.get_usdt_balance()
        results['demo_api'] = True
        results['usdt_balance'] = balance
        positions = dc.get_positions()
        results['positions'] = len(positions)
    except Exception as e:
        results['demo_error'] = str(e)
    
    return results
