"""
exit_manager.py - Exit management system.
Monitors open positions for TP/SL hits and 4H window timeout.
Handles: TP/SL checks, 4H timeout exits, window-based exit strategy.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.database.db import (
    log_event, get_open_trades, trade_close,
)
from backend.config import WINDOW_BARS, POSITION_SIZE_USDT, TP_PCT, SL_PCT
from backend.state.state_manager import PositionState, RiskState
from backend.trading.order_manager import OrderManager
from backend.trading.tp_sl_manager import TpSlManager
from backend.api.binance import get_demo_client


class ExitManager:
    """
    Manages exits for all open positions.
    
    Exit types:
    1. TP hit → record win, close trade
    2. SL hit → record loss, close trade
    3. 4H window timeout → close at market (with stop-loss as minimum)
    4. Manual exit (via API)
    """

    def __init__(self):
        self.order_mgr = OrderManager()
        self.tp_sl_mgr = TpSlManager()
        self.demo_client = get_demo_client()

    def check_all_positions(self) -> list:
        """
        Check all open positions for exit conditions.
        Called every 60 seconds when in trade.

        Returns:
            List of exit events that occurred
        """
        events = []
        open_trades = get_open_trades()

        if not open_trades:
            return events

        for trade in open_trades:
            exit_event = self._check_single_position(trade)
            if exit_event:
                events.append(exit_event)

        return events

    def _check_single_position(self, trade: dict) -> Optional[dict]:
        """
        Check a single position for exit conditions.

        Checks:
        1. TP/SL order status (did they fill?)
        2. In-app price SL check (safety net - works on all environments)
        3. 4H window timeout?
        4. Position still exists on Binance?
        """
        symbol = trade['coin']
        trade_id = trade['id']
        side = trade['side']
        entry_price = trade['entry_price']
        tp_price = trade['tp_price']
        sl_price = trade['sl_price']
        trigger_time = trade['trigger_time']

        # Step 1: Check TP/SL order status
        tp_sl_status = self.tp_sl_mgr.check_tp_sl_status(
            symbol=symbol,
            trade_id=trade_id,
        )

        # Case A: TP was hit (via exchange LIMIT order)
        if tp_sl_status.get('tp_filled') or \
           tp_sl_status.get('exit_info', {}).get('reason') == 'tp_hit':
            return self._handle_tp_hit(trade, tp_sl_status)

        # Case B: SL was hit (via exchange order - may not exist on testnet)
        if tp_sl_status.get('sl_filled') or \
           tp_sl_status.get('exit_info', {}).get('reason') == 'sl_hit':
            return self._handle_sl_hit(trade, tp_sl_status)

        # Case B2: In-app monitored SL check (safety net for testnet/mainnet)
        # Check if current market price has breached the SL threshold
        sl_breached = self._check_price_sl(symbol, side, sl_price)
        if sl_breached:
            return self._handle_price_sl_hit(trade, sl_breached)

        # Case C: Orders failed silently (position open but no orders)
        exit_info = tp_sl_status.get('exit_info', {})
        if exit_info and exit_info.get('reason') == 'sl_tp_failed_silently':
            return self._handle_silent_failure(trade, exit_info)

        # Case D: Check 4H window timeout
        if self._is_window_expired(trigger_time):
            return self._handle_timeout(trade)

        # Case E: Position closed externally
        if exit_info and exit_info.get('reason') == 'orders_gone_position_closed':
            return self._handle_external_exit(trade)

        return None

    # ─── In-App Monitored SL ─────────────────────────────────

    def _check_price_sl(self, symbol: str, side: str,
                        sl_price: float) -> Optional[float]:
        """
        Check if current market price has breached the SL threshold.
        This is an in-app safety net that works regardless of whether
        exchange SL orders were placed (testnet may not support them).

        Args:
            symbol: e.g., 'FARTCOINUSDT'
            side: 'LONG' or 'SHORT'
            sl_price: stop-loss price from trade record

        Returns:
            Current market price if SL is breached, None otherwise
        """
        try:
            current_price = self.demo_client.get_ticker_price(symbol)
            if side == 'LONG' and current_price <= sl_price:
                log_event('INFO', 'exit',
                          f"{symbol}: In-app SL triggered! Price ${current_price:.6f} <= SL ${sl_price:.6f}")
                return current_price
            elif side == 'SHORT' and current_price >= sl_price:
                log_event('INFO', 'exit',
                          f"{symbol}: In-app SL triggered! Price ${current_price:.6f} >= SL ${sl_price:.6f}")
                return current_price
        except Exception as e:
            log_event('WARNING', 'exit',
                      f"{symbol}: In-app SL price check failed: {e}")
        return None

    def _handle_price_sl_hit(self, trade: dict,
                              current_price: float) -> dict:
        """
        Handle SL hit detected by in-app price monitoring.
        Cancels any TP orders and exits at market.
        """
        symbol = trade['coin']
        trade_id = trade['id']
        side = trade['side']
        entry_price = trade['entry_price']
        position_size = trade.get('position_size', POSITION_SIZE_USDT)

        log_event('INFO', 'exit',
                  f"{symbol}: In-app SL exit initiated at ${current_price:.6f}")

        # Cancel any existing TP orders
        self.order_mgr.cancel_tp_sl(symbol)

        # Get actual position quantity from Binance
        try:
            position = self.demo_client.get_position_for_symbol(symbol)
            if position and abs(float(position.get('positionAmt', 0))) > 0:
                amt = abs(float(position['positionAmt']))
            else:
                amt = 0
        except Exception:
            amt = 0

        if amt <= 0:
            # Position already closed
            now_ist = self._now_ist_str()
            trade_close(
                trade_id=trade_id,
                exit_price=current_price,
                exit_time=now_ist,
                pnl_usdt=0,
                pnl_pct=0,
                exit_reason='sl_hit',
            )
            return {'type': 'sl_hit_already_closed', 'symbol': symbol, 'side': side, 'entry_price': entry_price, 'exit_price': current_price, 'pnl_usdt': 0, 'pnl_pct': 0}

        # Market exit
        exit_result = self.order_mgr.exit_market(symbol, side, amt)
        exit_price = exit_result.get('avg_price', current_price) if exit_result else current_price

        # Calculate PnL
        if side == 'LONG':
            pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * 100
        pnl_usdt = position_size * (pnl_pct / 100)

        now_ist = self._now_ist_str()

        trade_close(
            trade_id=trade_id,
            exit_price=exit_price,
            exit_time=now_ist,
            pnl_usdt=pnl_usdt,
            pnl_pct=pnl_pct,
            exit_reason='sl_hit',
        )

        RiskState.record_loss()

        event = {
            'type': 'app_sl_hit',
            'symbol': symbol,
            'side': side,
            'trade_id': trade_id,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl_usdt': pnl_usdt,
            'pnl_pct': pnl_pct,
            'exit_time': now_ist,
        }

        log_event('INFO', 'exit',
                  f"{symbol}: APP SL HIT @ {exit_price:.6f} | PnL=-${abs(pnl_usdt):.2f} ({pnl_pct:.1f}%)")
        return event

    def _handle_tp_hit(self, trade: dict, status: dict) -> dict:
        """Handle a take-profit hit."""
        symbol = trade['coin']
        trade_id = trade['id']
        entry_price = trade['entry_price']
        side = trade['side']
        position_size = trade.get('position_size', POSITION_SIZE_USDT)

        # Get actual fill price from the TP order
        exit_price = status.get('tp_price') or trade['tp_price']

        # Calculate actual PnL from fill prices
        if side == 'LONG':
            pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * 100
        pnl_usdt = position_size * (pnl_pct / 100)

        now_ist = self._now_ist_str()

        # Close trade in DB
        trade_close(
            trade_id=trade_id,
            exit_price=exit_price,
            exit_time=now_ist,
            pnl_usdt=pnl_usdt,
            pnl_pct=pnl_pct,
            exit_reason='tp_hit',
        )

        # Update risk state
        RiskState.record_win()

        event = {
            'type': 'tp_hit',
            'symbol': symbol,
            'side': side,
            'trade_id': trade_id,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl_usdt': pnl_usdt,
            'pnl_pct': pnl_pct,
            'exit_time': now_ist,
        }

        log_event('INFO', 'exit',
                  f"{symbol}: TP HIT @ {exit_price:.6f} | PnL=+${pnl_usdt:.2f} ({pnl_pct:.1f}%)")
        return event

    def _handle_sl_hit(self, trade: dict, status: dict) -> dict:
        """Handle a stop-loss hit."""
        symbol = trade['coin']
        trade_id = trade['id']
        entry_price = trade['entry_price']
        side = trade['side']
        position_size = trade.get('position_size', POSITION_SIZE_USDT)

        # Get actual fill price from the SL order
        exit_price = status.get('sl_price') or trade['sl_price']

        # Calculate actual PnL from fill prices
        if side == 'LONG':
            pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * 100
        pnl_usdt = position_size * (pnl_pct / 100)

        now_ist = self._now_ist_str()

        trade_close(
            trade_id=trade_id,
            exit_price=exit_price,
            exit_time=now_ist,
            pnl_usdt=pnl_usdt,
            pnl_pct=pnl_pct,
            exit_reason='sl_hit',
        )

        RiskState.record_loss()

        event = {
            'type': 'sl_hit',
            'symbol': symbol,
            'side': side,
            'trade_id': trade_id,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl_usdt': pnl_usdt,
            'pnl_pct': pnl_pct,
            'exit_time': now_ist,
        }

        log_event('INFO', 'exit',
                  f"{symbol}: SL HIT @ {exit_price:.6f} | PnL=-${abs(pnl_usdt):.2f} ({pnl_pct:.1f}%)")
        return event

    def _handle_timeout(self, trade: dict) -> dict:
        """Handle 4H window timeout - exit at market."""
        symbol = trade['coin']
        trade_id = trade['id']
        side = trade['side']
        entry_price = trade['entry_price']
        position_size = trade.get('position_size', POSITION_SIZE_USDT)

        log_event('INFO', 'exit',
                  f"{symbol}: 4H window expired, exiting at market")

        # Get current position size from Binance
        try:
            position = self.demo_client.get_position_for_symbol(symbol)
            if not position or abs(float(position.get('positionAmt', 0))) == 0:
                # Position already closed
                now_ist = self._now_ist_str()
                trade_close(
                    trade_id=trade_id,
                    exit_price=entry_price,
                    exit_time=now_ist,
                    pnl_usdt=0,
                    pnl_pct=0,
                    exit_reason='timeout',
                )
                return {
                    'type': 'timeout_already_closed',
                    'symbol': symbol,
                    'side': side,
                    'trade_id': trade_id,
                    'entry_price': entry_price,
                    'exit_price': entry_price,
                    'pnl_usdt': 0,
                    'pnl_pct': 0,
                    'exit_time': now_ist,
                }

            amt = abs(float(position['positionAmt']))
            current_price = float(position.get('markPrice', 0))

            # Cancel existing TP/SL orders
            self.order_mgr.cancel_tp_sl(symbol)

            # Market exit
            exit_result = self.order_mgr.exit_market(symbol, side, amt)
            if exit_result:
                exit_price = exit_result.get('avg_price', current_price)
            else:
                exit_price = current_price

            # Calculate PnL
            if side == 'LONG':
                pnl_pct = (exit_price - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - exit_price) / entry_price * 100
            pnl_usdt = position_size * (pnl_pct / 100)

            now_ist = self._now_ist_str()

            trade_close(
                trade_id=trade_id,
                exit_price=exit_price,
                exit_time=now_ist,
                pnl_usdt=pnl_usdt,
                pnl_pct=pnl_pct,
                exit_reason='timeout',
            )

            # Only record as loss if negative
            if pnl_pct < 0:
                RiskState.record_loss()
            else:
                RiskState.record_win()

            log_event('INFO', 'exit',
                      f"{symbol}: TIMEOUT EXIT @ {exit_price:.6f} | PnL=${pnl_usdt:.2f} ({pnl_pct:.1f}%)")
            return {
                'type': 'timeout',
                'symbol': symbol,
                'side': side,
                'trade_id': trade_id,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'pnl_usdt': pnl_usdt,
                'pnl_pct': pnl_pct,
                'exit_time': now_ist,
            }

        except Exception as e:
            log_event('ERROR', 'exit',
                      f"{symbol}: Timeout exit failed: {e}")
            return None

    def _handle_silent_failure(self, trade: dict, exit_info: dict) -> dict:
        """
        Handle case where TP/SL orders failed silently.
        Position is open but no protective orders exist.
        """
        symbol = trade['coin']
        trade_id = trade['id']
        side = trade['side']
        entry_price = trade['entry_price']

        log_event('WARNING', 'exit',
                  f"{symbol}: TP/SL failed silently! Emergency market exit.")

        amt = abs(float(exit_info.get('position_amt', 0)))
        if amt <= 0:
            return None

        # Place emergency market exit
        exit_result = self.order_mgr.exit_market(symbol, side, amt)
        if exit_result:
            exit_price = exit_result.get('avg_price', 0)
        else:
            try:
                exit_price = self.demo_client.get_ticker_price(symbol)
            except Exception:
                exit_price = 0

        position_size = trade.get('position_size', POSITION_SIZE_USDT)
        if side == 'LONG':
            pnl_pct = (exit_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * 100 if entry_price > 0 else 0
        pnl_usdt = position_size * (pnl_pct / 100)

        now_ist = self._now_ist_str()

        trade_close(
            trade_id=trade_id,
            exit_price=exit_price,
            exit_time=now_ist,
            pnl_usdt=pnl_usdt,
            pnl_pct=pnl_pct,
            exit_reason='error',
        )

        RiskState.record_loss()

        event = {
            'type': 'emergency_exit',
            'symbol': symbol,
            'side': side,
            'trade_id': trade_id,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl_usdt': pnl_usdt,
            'pnl_pct': pnl_pct,
            'exit_time': now_ist,
        }

        log_event('WARNING', 'exit',
                  f"{symbol}: EMERGENCY EXIT @ {exit_price:.6f} | PnL=${pnl_usdt:.2f}")
        return event

    def _handle_external_exit(self, trade: dict) -> dict:
        """
        Handle case where position was closed externally (e.g., manual on Binance).
        Tries to find the actual exit price from recent trades on Binance
        for accurate PnL recording rather than using current mark price.
        """
        symbol = trade['coin']
        trade_id = trade['id']
        entry_price = trade['entry_price']
        side = trade['side']

        log_event('INFO', 'exit',
                  f"{symbol}: Position closed externally. Trying to find exit fill...")

        exit_price = entry_price  # Fallback: assume no gain/loss

        # Try to find the actual exit price from recent fills
        try:
            trades = self.demo_client.get_recent_trades(symbol, limit=10)
            if trades:
                # Find a trade that closed our position side
                for t in trades:
                    is_buyer = t.get('isBuyer', False)
                    if side == 'LONG' and not is_buyer:  # LONG exit = SELL (isBuyer=False)
                        exit_price = float(t.get('price', entry_price))
                        break
                    elif side == 'SHORT' and is_buyer:  # SHORT exit = BUY (isBuyer=True)
                        exit_price = float(t.get('price', entry_price))
                        break
        except Exception:
            # If we can't find the exit, fallback to mark price
            try:
                exit_price = self.demo_client.get_ticker_price(symbol)
            except Exception:
                pass

        position_size = trade.get('position_size', POSITION_SIZE_USDT)
        if side == 'LONG':
            pnl_pct = (exit_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * 100 if entry_price > 0 else 0
        pnl_usdt = position_size * (pnl_pct / 100)

        now_ist = self._now_ist_str()

        trade_close(
            trade_id=trade_id,
            exit_price=exit_price,
            exit_time=now_ist,
            pnl_usdt=pnl_usdt,
            pnl_pct=pnl_pct,
            exit_reason='manual',
        )

        return {
            'type': 'external_exit',
            'symbol': symbol,
            'side': side,
            'trade_id': trade_id,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl_usdt': pnl_usdt,
            'pnl_pct': pnl_pct,
            'exit_time': now_ist,
        }

    # ─── Utility ────────────────────────────────────────────

    @staticmethod
    def _is_window_expired(trigger_time_ist: str) -> bool:
        """
        Check if the 4H window has expired since the trigger time.
        """
        try:
            trigger_dt = datetime.strptime(trigger_time_ist, "%Y-%m-%d %H:%M:%S")
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            now_ist = now_utc + timedelta(hours=5.5)

            elapsed_hours = (now_ist - trigger_dt).total_seconds() / 3600
            return elapsed_hours >= WINDOW_BARS
        except Exception as e:
            log_event('WARNING', 'exit',
                      f"_is_window_expired: Bad date format '{trigger_time_ist}': {e}")
            return False

    @staticmethod
    def _now_ist_str() -> str:
        """Get current time as IST string."""
        now_utc = datetime.now(timezone.utc)
        now_ist = now_utc + timedelta(hours=5.5)
        return now_ist.strftime("%Y-%m-%d %H:%M:%S")
