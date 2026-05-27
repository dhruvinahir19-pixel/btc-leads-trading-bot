"""
order_manager.py - Handles individual order placement.
Uses limit-order optimization (best ask + 0.01%) with market fallback after 2s.
All methods use the demo API (testnet) for order placement.
"""
import time
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from backend.api.binance import get_demo_client, BinanceError
from backend.database.db import log_event


class OrderManager:
    """
    Manages order placement with:
    - Limit order at best price + 0.01% offset (saves on taker fees)
    - 2-second timeout, then fallback to market order
    - Order fill verification
    - TP/SL limit order placement
    """

    def __init__(self):
        self.client = get_demo_client()
        # How long to wait for a limit order fill before falling back to market
        self.LIMIT_TIMEOUT_SECONDS = 2.0
        # How many times to poll for fill status
        self.FILL_POLL_INTERVAL = 0.5
        # Offset from best bid/ask for entry
        self.LIMIT_OFFSET_PCT = 0.01 / 100  # 0.01% above best ask (for longs)

    # ─── Entry Orders ───────────────────────────────────────

    def enter_position(self, symbol: str, side: str,
                       position_size_usdt: float) -> Optional[dict]:
        """
        Enter a position using optimized limit order or market fallback.

        Strategy:
        1. Check order book for best ask/bid
        2. Place limit at best ask + 0.01% (for LONG) or best bid - 0.01% (for SHORT)
        3. Wait up to 2 seconds for fill
        4. If not filled, cancel limit and fallback to market order

        Args:
            symbol: e.g., 'FARTCOINUSDT'
            side: 'LONG' or 'SHORT'
            position_size_usdt: how much USDT to spend (e.g., $10.0)

        Returns:
            Dict with fill info: {'filled_qty', 'avg_price', 'order_id', 'method'}
            Or None if both limit and market fail
        """
        order_side = 'BUY' if side == 'LONG' else 'SELL'

        # Step 1: Get current price and calculate quantity
        try:
            current_price = self.client.get_ticker_price(symbol)
            lot_info = self.client.get_lot_size_info(symbol)
            qty_precision = self.client.get_quantity_precision(symbol)
        except Exception as e:
            log_event('ERROR', 'order', f"Failed to get price/lot for {symbol}: {e}")
            return None

        quantity = position_size_usdt / current_price
        if lot_info:
            step = lot_info.get('stepSize', 0.001)
            quantity = self._round_down(quantity, step)
            # Check min notional
            if quantity * current_price < 5.0:  # $5 min notional typical
                log_event('WARNING', 'order',
                          f"{symbol}: Position ${position_size_usdt} too small "
                          f"(min ~$5). Qty={quantity:.8f}, Price={current_price:.6f}")
                return None
        else:
            quantity = round(quantity, qty_precision)

        if quantity <= 0:
            log_event('ERROR', 'order', f"{symbol}: Invalid quantity {quantity}")
            return None

        # Step 2: Try limit order first (lower fees)
        limit_price = self._calculate_limit_price(symbol, side, current_price)
        log_event('INFO', 'order',
                  f"{symbol}: Trying limit {order_side} at {limit_price:.6f} "
                  f"(qty={quantity:.6f}, ${position_size_usdt:.2f})")

        try:
            # Use GTC (Good-Til-Cancelled) with 2-second polling for better fill odds
            limit_order = self.client.place_limit_order(
                symbol=symbol,
                side=order_side,
                quantity=quantity,
                price=limit_price,
                time_in_force='GTC'
            )

            if not limit_order:
                log_event('WARNING', 'order', f"{symbol}: Limit order returned empty, falling back")
                return self._market_order(symbol, order_side, quantity)

            order_id = limit_order.get('orderId')
            log_event('INFO', 'order',
                      f"{symbol}: Limit {order_side} placed at {limit_price:.6f} "
                      f"(orderId={order_id}), waiting {self.LIMIT_TIMEOUT_SECONDS}s for fill")

            # Poll for up to LIMIT_TIMEOUT_SECONDS
            if order_id:
                polled = self._poll_fill(symbol, order_id, quantity, 'limit')
                if polled:
                    return polled

            # Not filled after timeout - cancel and fallback to market
            log_event('INFO', 'order',
                      f"{symbol}: Limit not filled in {self.LIMIT_TIMEOUT_SECONDS}s, cancelling")
            try:
                self.client.cancel_order(symbol, order_id)
            except Exception:
                pass  # May already be filled by now

            # Final fill check after cancel attempt (prevents double position)
            if order_id:
                final_check = self._poll_fill(symbol, order_id, quantity, 'limit')
                if final_check:
                    return final_check

        except BinanceError as e:
            log_event('WARNING', 'order',
                      f"{symbol}: Limit order failed ({e}), falling back to market")

        # Step 3: Fallback to market order
        return self._market_order(symbol, order_side, quantity)

    def _calculate_limit_price(self, symbol: str, side: str,
                               current_price: float) -> float:
        """
        Calculate the limit order price for optimized entry.
        For LONG: best ask + 0.01% offset
        For SHORT: best bid - 0.01% offset
        """
        try:
            orderbook = self.client.get_order_book(symbol, limit=5)
            if orderbook:
                if side == 'LONG' and orderbook.get('asks'):
                    best_ask = float(orderbook['asks'][0][0])
                    return best_ask * (1 + self.LIMIT_OFFSET_PCT)
                elif side == 'SHORT' and orderbook.get('bids'):
                    best_bid = float(orderbook['bids'][0][0])
                    return best_bid * (1 - self.LIMIT_OFFSET_PCT)
        except Exception:
            pass

        # Fallback: use current price with offset
        if side == 'LONG':
            return current_price * (1 + self.LIMIT_OFFSET_PCT)
        else:
            return current_price * (1 - self.LIMIT_OFFSET_PCT)

    def _market_order(self, symbol: str, side: str,
                      quantity: float) -> Optional[dict]:
        """Place a market order as fallback."""
        try:
            log_event('INFO', 'order', f"{symbol}: Market {side} qty={quantity:.6f}")
            order = self.client.place_market_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
            )

            if order and order.get('status') == 'FILLED':
                filled_qty = float(order.get('executedQty', 0))
                cum_quote = float(order.get('cumQuote') or order.get('cummulativeQuoteQty', 0))
                avg_price = cum_quote / filled_qty if filled_qty > 0 else 0
                log_event('INFO', 'order',
                          f"{symbol}: Market order filled at {avg_price:.6f}")
                return {
                    'filled_qty': filled_qty,
                    'avg_price': avg_price,
                    'order_id': order.get('orderId'),
                    'method': 'market',
                }
            elif order:
                # Order placed but not yet filled - poll for fill
                order_id = order.get('orderId')
                if order_id:
                    polled = self._poll_fill(symbol, order_id, quantity, 'market')
                    if polled:
                        return polled
                    # If still not filled after polling, check one more time
                    # (testnet can be slow to fill market orders)
                    log_event('INFO', 'order',
                              f"{symbol}: Market order NEW after polling, checking fill...")
                    time.sleep(1.0)
                    try:
                        status = self.client.get_order_status(symbol, order_id)
                        if status.get('status') == 'FILLED':
                            filled_qty = float(status.get('executedQty', 0))
                            cum_quote = float(status.get('cumQuote') or status.get('cummulativeQuoteQty', 0))
                            avg_price = cum_quote / filled_qty if filled_qty > 0 else 0
                            return {
                                'filled_qty': filled_qty,
                                'avg_price': avg_price,
                                'order_id': order_id,
                                'method': 'market_delayed',
                            }
                    except Exception:
                        pass
                    log_event('WARNING', 'order',
                              f"{symbol}: Market order still not filled after polling")
                return None
            return None

        except BinanceError as e:
            log_event('ERROR', 'order', f"{symbol}: Market order failed: {e}")
            return None

    def _market_fill_remaining(self, symbol: str, side: str,
                                remaining_qty: float,
                                limit_order: dict,
                                original_qty: float,
                                limit_price: float,
                                filled_qty: float = 0) -> Optional[dict]:
        """Fill remaining quantity with market order after partial limit fill."""
        try:
            market_order = self.client.place_market_order(
                symbol=symbol,
                side=side,
                quantity=remaining_qty,
            )

            total_filled_qty = filled_qty
            total_cost = filled_qty * limit_price

            if market_order and market_order.get('status') == 'FILLED':
                m_filled = float(market_order.get('executedQty', 0))
                m_quote = float(market_order.get('cumQuote') or market_order.get('cummulativeQuoteQty', 0))
                total_filled_qty += m_filled
                total_cost += m_quote

            avg_price = total_cost / total_filled_qty if total_filled_qty > 0 else limit_price
            return {
                'filled_qty': total_filled_qty,
                'avg_price': avg_price,
                'order_id': limit_order.get('orderId'),
                'method': 'limit+market',
            }

        except BinanceError as e:
            log_event('ERROR', 'order',
                      f"{symbol}: Market fill remaining failed: {e}")
            if filled_qty > 0:
                return {
                    'filled_qty': filled_qty,
                    'avg_price': limit_price,
                    'order_id': limit_order.get('orderId'),
                    'method': 'limit_only',
                }
            return None

    def _poll_fill(self, symbol: str, order_id: int,
                   expected_qty: float, order_type: str) -> Optional[dict]:
        """Poll for order fill status for a short time."""
        for _ in range(4):  # ~2 seconds
            time.sleep(self.FILL_POLL_INTERVAL)
            try:
                status = self.client.get_order_status(symbol, order_id)
                if status.get('status') == 'FILLED':
                    filled_qty = float(status.get('executedQty', 0))
                    cum_quote = float(status.get('cumQuote') or status.get('cummulativeQuoteQty', 0))
                    avg_price = cum_quote / filled_qty if filled_qty > 0 else 0
                    return {
                        'filled_qty': filled_qty,
                        'avg_price': avg_price,
                        'order_id': order_id,
                        'method': f'{order_type}_poll',
                    }
            except Exception:
                continue
        return None

    # ─── Exit Orders ────────────────────────────────────────

    def place_tp_sl(self, symbol: str, side: str, quantity: float,
                    tp_price: float, sl_price: float) -> dict:
        """
        Place TP and SL orders after a successful entry.

        Uses Algo Order API for SL (STOP_LOSS) as required by Binance Futures.
        TP uses regular LIMIT reduceOnly order.

        For LONG: TP = SELL LIMIT at tp_price, SL = SELL STOP_LOSS at sl_price
        For SHORT: TP = BUY LIMIT at tp_price, SL = BUY STOP_LOSS at sl_price

        Returns:
            Dict with 'tp_order', 'sl_order' responses, and 'error' or None
        """
        try:
            result = self.client.place_tp_sl_orders(
                symbol=symbol,
                side=side,
                quantity=quantity,
                tp_price=tp_price,
                sl_price=sl_price,
            )
            if result.get('error'):
                log_event('ERROR', 'order', f"{symbol}: TP/SL placement failed: {result['error']}")
            else:
                log_event('INFO', 'order',
                          f"{symbol}: TP/SL placed (TP={tp_price:.6f}, SL={sl_price:.6f})")
            return result

        except Exception as e:
            log_event('ERROR', 'order', f"{symbol}: TP/SL exception: {e}")
            return {'tp_order': None, 'sl_order': None, 'error': str(e)}

    def cancel_tp_sl(self, symbol: str):
        """Cancel all open orders for a symbol (used during exits).
        Cancels both regular orders AND Algo orders (TP/SL placed via Algo API).
        """
        try:
            # Cancel regular orders
            self.client.cancel_all_orders(symbol)
            # Cancel Algo orders (TP/SL via Algo Order API)
            try:
                algo_orders = self.client.get_open_algo_orders(symbol)
                for algo in algo_orders:
                    algo_id = algo.get('algoId')
                    if algo_id:
                        self.client.cancel_algo_order(symbol, algo_id)
            except Exception:
                pass
            log_event('INFO', 'order', f"{symbol}: All orders (incl. Algo TP/SL) cancelled")
            return True
        except Exception as e:
            log_event('WARNING', 'order', f"{symbol}: Cancel orders warning: {e}")
            return False

    def exit_market(self, symbol: str, side: str, quantity: float) -> Optional[dict]:
        """
        Exit a position using market order.
        Used for emergency exits or when TP/SL fails.

        Args:
            symbol: e.g., 'FARTCOINUSDT'
            side: 'LONG' or 'SHORT' (the direction of the original position)
            quantity: quantity to exit
        """
        exit_side = 'SELL' if side == 'LONG' else 'BUY'
        return self._market_order(symbol, exit_side, quantity)

    # ─── Utility ────────────────────────────────────────────

    @staticmethod
    def _round_down(value: float, step: float) -> float:
        """Round down to the nearest valid step size."""
        if step <= 0:
            return value
        precision = len(str(step).split('.')[-1]) if '.' in str(step) else 8
        stepped = (value // step) * step
        return round(stepped, precision)
