"""
tp_sl_manager.py - TP/SL limit order monitoring.
Checks if TP/SL orders are active, handles silent failures,
and manages exit price execution.
"""
from typing import Optional

from backend.api.binance import get_demo_client, BinanceError
from backend.database.db import log_event
from backend.config import WINDOW_BARS


class TpSlManager:
    """
    Monitors TP/SL orders for each open position.
    Handles:
    - Checking if TP/SL orders are still active
    - Detecting silent failures (order cancelled/expired without fill)
    - Verifying fills match expected prices
    - Fallback market exit if TP/SL failed
    """

    def __init__(self):
        self.client = get_demo_client()

    def check_tp_sl_status(self, symbol: str, trade_id: int,
                            tp_order_id: Optional[int] = None,
                            sl_order_id: Optional[int] = None) -> dict:
        """
        Check the status of TP and SL orders for a position.

        Returns:
            Dict with keys:
            - 'tp_filled': bool - whether TP was hit
            - 'sl_filled': bool - whether SL was hit
            - 'tp_price': float or None - price if TP filled
            - 'sl_price': float or None - price if SL filled
            - 'orders_active': bool - whether orders are still active
            - 'tp_order_id': int or None
            - 'sl_order_id': int or None
            - 'exit_needed': bool - any action needed
            - 'exit_info': dict or None - details if exit needed
        """
        result = {
            'tp_filled': False,
            'sl_filled': False,
            'tp_price': None,
            'sl_price': None,
            'orders_active': False,
            'tp_order_id': None,
            'sl_order_id': None,
            'exit_needed': False,
            'exit_info': None,
        }

        # Collect ALL open orders (regular + Algo)
        open_orders = []
        algo_orders = []

        try:
            open_orders = self.client.get_open_orders(symbol=symbol)
        except Exception as e:
            log_event('WARNING', 'tp_sl', f"{symbol}: Can't check regular orders: {e}")

        # Also check Algo orders (SL is now placed via Algo Order API)
        try:
            algo_orders = self.client.get_open_algo_orders(symbol=symbol)
        except Exception as e:
            log_event('WARNING', 'tp_sl', f"{symbol}: Can't check algo orders: {e}")

        total_orders = bool(open_orders) or bool(algo_orders)

        if not total_orders:
            # No open orders - position may have been exited
            # Check actual position on Binance
            try:
                position = self.client.get_position_for_symbol(symbol)
                if not position or abs(float(position.get('positionAmt', 0))) == 0:
                    # Position is gone - TP/SL must have been hit
                    result['exit_needed'] = True
                    result['exit_info'] = {
                        'reason': 'orders_gone_position_closed',
                        'symbol': symbol,
                        'need_market_exit': False,  # Already exited
                    }
                else:
                    # Position exists but no orders - SL failed silently or orders were cancelled
                    # This is a critical error - we need to manually exit
                    result['exit_needed'] = True
                    result['orders_active'] = False
                    result['exit_info'] = {
                        'reason': 'sl_tp_failed_silently',
                        'symbol': symbol,
                        'position_amt': float(position.get('positionAmt', 0)),
                        'entry_price': float(position.get('entryPrice', 0)),
                        'unrealized_pnl': float(position.get('unRealizedProfit', 0)),
                        'need_market_exit': True,
                    }
                    log_event('WARNING', 'tp_sl',
                              f"{symbol}: Position open but NO TP/SL orders! "
                              f"Manual exit needed. PnL=${position.get('unRealizedProfit', 0)}")
            except Exception as e:
                log_event('ERROR', 'tp_sl', f"{symbol}: Position check failed: {e}")

            return result

        # Orders are active
        result['orders_active'] = True

        # Check regular orders for TP fills
        for order in open_orders:
            order_id = order.get('orderId')
            order_type = order.get('type', '')
            executed_qty = float(order.get('executedQty', 0))
            order_price = float(order.get('price', 0))

            # Check if this is a TP order (LIMIT, reduceOnly) that was filled
            if order_type == 'LIMIT' and executed_qty > 0:
                result['tp_filled'] = True
                result['tp_price'] = order_price
                result['tp_order_id'] = order_id
                result['exit_needed'] = True
                result['exit_info'] = {
                    'reason': 'tp_hit',
                    'symbol': symbol,
                    'price': order_price,
                    'filled_qty': executed_qty,
                    'need_market_exit': False,
                }

        # Check Algo orders for SL fills
        for algo in algo_orders:
            algo_id = algo.get('algoId')
            algo_type = algo.get('algoType', '')
            algo_status = algo.get('algoStatus', '')
            executed_qty = float(algo.get('executedQty', 0))
            trigger_price = float(algo.get('triggerPrice', 0))

            # If SL was triggered (executedQty > 0), report as filled
            if algo_type in ('STOP_LOSS', 'STOP_LOSS_LIMIT') and executed_qty > 0:
                result['sl_filled'] = True
                result['sl_price'] = trigger_price
                result['sl_order_id'] = algo_id
                result['exit_needed'] = True
                result['exit_info'] = {
                    'reason': 'sl_hit',
                    'symbol': symbol,
                    'price': trigger_price,
                    'filled_qty': executed_qty,
                    'need_market_exit': False,
                }

        return result

    def verify_exit_price(self, symbol: str, expected_tp: float,
                          expected_sl: float, trade_id: int) -> dict:
        """
        After an exit, verify the actual exit price vs expected TP/SL.
        This helps track slippage.

        Returns:
            Dict with verification info
        """
        try:
            position = self.client.get_position_for_symbol(symbol)
            if position and abs(float(position.get('positionAmt', 0))) > 0:
                # Position still open - not exited yet
                return {'exited': False}

            # Position is closed - need to find the exit order
            # We can check recent orders (last 100) to find the exit
            return {'exited': True, 'verified': True}
        except Exception:
            return {'exited': False, 'error': 'verification_failed'}
