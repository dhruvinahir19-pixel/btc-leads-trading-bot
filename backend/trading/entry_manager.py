"""
entry_manager.py - Coordinated multi-coin entry system.
When a BTC trigger fires, enters up to 5 coins simultaneously.
Handles partial fills, individual coin failures, and coordinated entry.
"""
from typing import Optional
from datetime import datetime, timezone, timedelta

from backend.api.binance import get_demo_client
from backend.database.db import (
    log_event, trade_create,
    get_open_trades,
)
from backend.state.state_manager import (
    PositionState, RiskState, WeeklyScanState,
)
from backend.config import (
    POSITION_SIZE_USDT, MAX_COINS_PER_TRADE, TP_PCT, SL_PCT,
    FIXED_COINS, to_ist_timestamp,
)
from backend.core.signal import Signal, SignalGenerator
from backend.trading.order_manager import OrderManager
from backend.trading.risk_manager import RiskManager


class EntryManager:
    """
    Manages coordinated multi-coin entries.
    
    Flow:
    1. Signal fires (BTC > 1%)
    2. Get trading coins (fixed + dynamic)
    3. Get entry prices for each coin
    4. Enter each coin using OrderManager (limit→market optimization)
    5. Place TP/SL orders for each filled entry
    6. Record all trades in DB
    """

    def __init__(self):
        self.order_mgr = OrderManager()
        self.signal_gen = SignalGenerator()
        self.risk_mgr = RiskManager()
        self.demo_client = get_demo_client()

    def execute_signal(self, signal: Signal) -> dict:
        """
        Execute a trading signal by entering positions on all trading coins.

        Args:
            signal: Signal object from BTC trigger detection

        Returns:
            Dict with execution results:
            - 'entries': list of successful entries
            - 'failed': list of failed entries
            - 'skipped': reasons for skipped entries
        """
        result = {
            'signal_time': signal.trigger_time_ist,
            'signal_side': signal.side,
            'btc_return_pct': signal.btc_return_pct,
            'entries': [],
            'failed': [],
            'skipped': [],
        }

        # Step 1: Check risk gates
        risk_check = self.risk_mgr.check_entry_gates()
        if not risk_check['allowed']:
            result['skipped'].append({
                'reason': f"Risk gate blocked: {risk_check['reason']}",
            })
            log_event('INFO', 'entry', f"Entry blocked: {risk_check['reason']}")
            return result

        # Step 2: Get trading coins
        coins = WeeklyScanState.get_trading_coins()
        if not coins:
            # Fallback to fixed coins if weekly scan hasn't run yet
            coins = list(FIXED_COINS)

        # Limit to max coins
        coins = coins[:MAX_COINS_PER_TRADE]
        log_event('INFO', 'entry',
                  f"Signal {signal.side}: Preparing to enter {len(coins)} coins: {coins}")

        # Step 3: Get entry prices for each coin
        entry_prices = self.signal_gen.get_entry_prices(signal, coins)
        if not entry_prices:
            log_event('ERROR', 'entry', "No entry prices could be fetched for any coin")
            result['skipped'].append({'reason': 'no_entry_prices'})
            return result

        # Step 4: Check for overlapping positions
        active_symbols = {t['coin'] for t in get_open_trades()}
        coins_to_enter = [c for c in coins if c not in active_symbols]
        skipped_overlap = [c for c in coins if c in active_symbols]
        for c in skipped_overlap:
            result['skipped'].append({
                'coin': c,
                'reason': 'already_in_position',
            })

        if not coins_to_enter:
            log_event('INFO', 'entry', "All coins already in position, skipping")
            result['skipped'].append({'reason': 'all_coins_already_in_position'})
            return result

        # Step 5: Enter each coin
        for coin in coins_to_enter:
            price_info = entry_prices.get(coin)
            if not price_info:
                result['failed'].append({
                    'coin': coin,
                    'reason': 'no_price_info',
                })
                continue

            entry_price = price_info['entry']
            tp_price = price_info['tp']
            sl_price = price_info['sl']

            # Enter position
            enter_result = self.order_mgr.enter_position(
                symbol=coin,
                side=signal.side,
                position_size_usdt=POSITION_SIZE_USDT,
            )

            if not enter_result:
                result['failed'].append({
                    'coin': coin,
                    'reason': 'entry_order_failed',
                    'entry_price': entry_price,
                })
                log_event('WARNING', 'entry',
                          f"{coin}: Entry order failed")
                continue

            # Entry successful - create trade record
            filled_price = enter_result['avg_price']
            filled_qty = enter_result['filled_qty']

            # Recalculate TP/SL based on actual fill price
            if signal.side == 'LONG':
                actual_tp = filled_price * (1 + TP_PCT / 100)
                actual_sl = filled_price * (1 - SL_PCT / 100)
            else:
                actual_tp = filled_price * (1 - TP_PCT / 100)
                actual_sl = filled_price * (1 + SL_PCT / 100)

            # Insert into database
            trade_id = trade_create(
                trigger_time=signal.trigger_time_ist,
                coin=coin,
                side=signal.side,
                btc_return_pct=signal.btc_return_pct,
                entry_price=filled_price,
                tp_price=actual_tp,
                sl_price=actual_sl,
                position_size=POSITION_SIZE_USDT,
            )

            # Step 6: Place TP/SL orders
            tp_sl_result = self.order_mgr.place_tp_sl(
                symbol=coin,
                side=signal.side,
                quantity=filled_qty,
                tp_price=actual_tp,
                sl_price=actual_sl,
            )

            entry_record = {
                'trade_id': trade_id,
                'coin': coin,
                'side': signal.side,
                'entry_price': filled_price,
                'filled_qty': filled_qty,
                'position_size_usdt': POSITION_SIZE_USDT,
                'tp_price': actual_tp,
                'sl_price': actual_sl,
                'execution_method': enter_result.get('method', 'market'),
                'tp_sl_placed': tp_sl_result.get('error') is None,
                'tp_order_id': tp_sl_result.get('tp_order', {}).get('orderId'),
                'sl_order_id': tp_sl_result.get('sl_order', {}).get('orderId'),
            }

            if tp_sl_result.get('error'):
                entry_record['tp_sl_error'] = tp_sl_result['error']
                log_event('WARNING', 'entry',
                          f"{coin}: TP/SL placement error: {tp_sl_result['error']}")
            elif tp_sl_result.get('sl_fallback'):
                # SL placed via in-app monitoring (testnet limitation)
                entry_record['tp_sl_error'] = tp_sl_result.get('warning', 'sl_fallback')
                log_event('INFO', 'entry',
                          f"{coin}: TP placed on exchange, SL via in-app monitoring "
                          f"({tp_sl_result.get('warning', 'no_exchange_sl')})")

            result['entries'].append(entry_record)

            # Update risk counters
            RiskState.increment_daily_trades()

            log_event('INFO', 'entry',
                      f"{coin}: ENTERED {signal.side} @ {filled_price:.6f} "
                      f"(qty={filled_qty:.6f}) via {enter_result.get('method', 'unknown')}")

        # Summary
        total_requested = len(coins_to_enter)
        total_entered = len(result['entries'])
        log_event('INFO', 'entry',
                  f"Entry complete: {total_entered}/{total_requested} coins entered")

        return result
