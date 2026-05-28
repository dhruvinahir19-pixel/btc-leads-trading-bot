"""
data_fetcher.py - Scheduled data download with retry logic.
Handles candle fetching, weekly coin scanning, and data caching.
"""
import time
import json
import random
from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.api.binance import get_data_client, BinanceError
from backend.database.db import (
    log_event, save_scan_result, get_latest_scan,
    config_set, config_get,
)
from backend.config import (
    SCAN_MAX_SYMBOLS, SCAN_DURATION_MINUTES,
    TOP_DYNAMIC_COINS, FIXED_COINS,
    POSITION_SIZE_USDT,
)
from backend.state.state_manager import WeeklyScanState


class DataFetcher:
    """
    Handles all scheduled data fetching operations.
    - Downloads 1H candles for BTC and trading coins
    - Performs weekly correlation scan of all 645 pairs
    - Caches data to reduce API calls
    """
    
    def __init__(self):
        self.client = get_data_client()
    
    def fetch_latest_candle(self, symbol: str) -> Optional[dict]:
        """
        Fetch the most recently completed 1H candle for a symbol.
        Used by the main loop to check for BTC triggers.
        """
        try:
            candles = self.client.get_klines(symbol, '1h', limit=2)
            if len(candles) >= 2:
                return candles[-2]  # Most recent completed candle
            return None
        except Exception as e:
            log_event('ERROR', 'data_fetcher', f"Failed to fetch {symbol}: {e}")
            return None
    
    def fetch_recent_candles(self, symbol: str, hours: int = 24) -> list:
        """
        Fetch recent candles for position monitoring.
        Used when in a trade to check TP/SL status.
        """
        try:
            candles = self.client.get_klines(symbol, '1h', limit=hours)
            return candles
        except Exception as e:
            log_event('ERROR', 'data_fetcher',
                      f"Failed to fetch recent {symbol}: {e}")
            return []
    
    # ─── Weekly Coin Scanner ────────────────────────────────
    
    def run_weekly_scan(self) -> dict:
        """
        Scan all 645 Binance Futures pairs to find coins with:
        - Correlation with BTC: 0.50 - 0.85 (sweet spot)
        - Beta > 1.2x
        - Volume > $5M/day
        - Prefer mid-cap coins with real volume
        
        This runs ONCE per week on Sunday.
        Returns the scan results with ranked coin list.
        """
        from datetime import datetime, timezone, timedelta
        
        log_event('INFO', 'scanner', "Starting weekly correlation scan...")
        
        now_utc = datetime.now(timezone.utc)
        ist_now = now_utc + timedelta(hours=5.5)
        this_monday = (ist_now - timedelta(days=ist_now.weekday())).strftime("%Y-%m-%d")
        
        try:
            # Step 1: Get all symbols
            info = self.client.get_exchange_info()
            all_symbols = [
                s for s in info.get('symbols', [])
                if s.get('contractType') == 'PERPETUAL'
                and s.get('quoteAsset') == 'USDT'
                and s.get('status') == 'TRADING'
            ]
            log_event('INFO', 'scanner', f"Found {len(all_symbols)} USDT perpetual pairs")
            
            # Step 2: Get BTC 30-day 1H data
            btc_data = self._get_scan_data('BTCUSDT')
            if not btc_data:
                raise Exception("Failed to fetch BTC reference data")
            
            btc_returns = self._calculate_returns(btc_data)
            
            # Step 3: Scan each symbol for correlation + beta
            results = []
            scanned = 0
            start_time = time.time()
            max_duration = SCAN_DURATION_MINUTES * 60  # Convert to seconds
            
            for sym_info in all_symbols:
                symbol = sym_info['symbol']
                
                # Check time limit
                if time.time() - start_time > max_duration:
                    log_event('WARNING', 'scanner',
                              f"Time limit reached. Scanned {scanned}/{len(all_symbols)}")
                    break
                
                scanned += 1
                
                # Skip BTC itself
                if symbol == 'BTCUSDT':
                    continue
                
                # Rate limit: wait 2-3s between coins to avoid IP ban
                # 30 days of 1H data = 720 candles → 2 paginated calls per coin
                # Each klines call = weight 2 (limit=500), so 4 weight per coin
                # 527 coins × 2.5s avg = ~22 min total, well under 60 min limit
                if scanned > 1:
                    time.sleep(random.uniform(2.0, 3.0))
                
                # Get scan data for this symbol
                alt_data = self._get_scan_data(symbol)
                if not alt_data or len(alt_data) < 100:
                    continue
                
                alt_returns = self._calculate_returns(alt_data)
                
                # Calculate correlation
                corr = self._correlation(btc_returns, alt_returns)
                
                # Calculate beta
                beta = self._beta(btc_returns, alt_returns)
                
                # Calculate average volume
                avg_volume = sum(c['v'] for c in alt_data[-50:]) / 50
                avg_volume_usd = avg_volume * alt_data[-1]['c']  # Volume * price
                
                # Calculate alignment rate (how often alt moves same direction as BTC)
                align_rate = self._alignment_rate(btc_returns, alt_returns)
                
                # Big move alignment (how often alt moves >0.5% when BTC >1%)
                big_align = self._big_move_alignment(btc_returns, alt_returns)
                
                results.append({
                    'symbol': symbol,
                    'correlation': round(corr, 4),
                    'beta': round(beta, 4),
                    'avg_volume_usd': round(avg_volume_usd, 2),
                    'align_rate': round(align_rate, 4),
                    'big_align': round(big_align, 4),
                })
                
                # Progress log every 50 symbols
                if scanned % 50 == 0:
                    elapsed = int(time.time() - start_time)
                    log_event('INFO', 'scanner',
                              f"Scanned {scanned}/{len(all_symbols)} ({elapsed}s)")
            
            # Step 4: Score and rank
            for r in results:
                score = self._calculate_score(r)
                r['score'] = round(score, 4)
            
            # Sort by score descending
            results.sort(key=lambda x: x['score'], reverse=True)
            
            # Step 5: Get top candidates
            liquid_results = [r for r in results if r['avg_volume_usd'] > 5000000]
            sweet_spot = [
                r for r in liquid_results
                if 0.50 <= r['correlation'] <= 0.85
                and r['beta'] >= 1.2
            ]
            
            # Top dynamic coins (exclude fixed coins)
            excluded = set(FIXED_COINS)
            candidates = [r for r in sweet_spot if r['symbol'] not in excluded]
            top_coins = [r['symbol'] for r in candidates[:TOP_DYNAMIC_COINS]]
            
            # Step 6: Save results
            elapsed = int(time.time() - start_time)
            save_scan_result(
                week_start=this_monday,
                scan_time=ist_now.strftime("%Y-%m-%d %H:%M:%S"),
                num_scanned=scanned,
                num_liquid=len(liquid_results),
                results=results[:100],  # Save top 100
                top_coins=top_coins,
            )
            
            # Update trading coins
            WeeklyScanState.set_dynamic_coins(top_coins)
            
            log_event('INFO', 'scanner',
                      f"Scan complete: {len(liquid_results)} liquid, "
                      f"{len(candidates)} sweet-spot candidates, "
                      f"top {len(top_coins)}: {top_coins}")
            
            return {
                'success': True,
                'scanned': scanned,
                'liquid': len(liquid_results),
                'candidates': len(candidates),
                'top_coins': top_coins,
                'elapsed_seconds': elapsed,
            }
        
        except BinanceError as e:
            if getattr(e, 'status_code', None) == 418:
                log_event('WARNING', 'scanner',
                          "Scan aborted: IP banned by Binance. Will retry on next scheduled scan.")
            else:
                log_event('ERROR', 'scanner', f"Scan failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'scanned': 0,
                'liquid': 0,
                'candidates': 0,
                'top_coins': [],
                'elapsed_seconds': 0,
            }
        except Exception as e:
            log_event('ERROR', 'scanner', f"Scan failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'scanned': 0,
                'liquid': 0,
                'candidates': 0,
                'top_coins': [],
                'elapsed_seconds': 0,
            }
    
    def _get_scan_data(self, symbol: str) -> list:
        """Fetch approximately 30 days of 1H data for a symbol.
        
        30 days (720 candles) gives statistically robust correlation/beta
        calculation. Uses get_all_klines_range with limit=500 (API weight 2)
        so 30 days requires 2 paginated calls per coin (4 weight total).
        
        The underlying Binance client has REQUEST_TIMEOUT=15s with 3 retries,
        so a failing coin will timeout in ~45s max and be skipped gracefully.
        
        IMPORTANT: On 418 (IP banned), raises BinanceError immediately.
        Caller should check for this and abort the scan.
        """
        now = int(time.time() * 1000)
        start = now - (30 * 24 * 60 * 60 * 1000)  # 30 days ago
        try:
            candles = self.client.get_all_klines_range(symbol, '1h', start, now)
            return candles
        except BinanceError as e:
            if getattr(e, 'status_code', None) == 418:
                # IP banned — re-raise so the scanner can abort
                raise
            # Log which coin failed (helps debug scanner hangs)
            log_event('WARNING', 'scanner', f"Skipping {symbol}: {e}")
            return []
        except Exception as e:
            log_event('WARNING', 'scanner', f"Skipping {symbol}: {e}")
            return []
    
    def _calculate_returns(self, candles: list) -> list:
        """Calculate percentage returns from candle close prices."""
        returns = []
        for i in range(1, len(candles)):
            ret = (candles[i]['c'] - candles[i-1]['c']) / candles[i-1]['c']
            returns.append(ret)
        return returns
    
    def _correlation(self, x: list, y: list) -> float:
        """Calculate Pearson correlation coefficient between two lists."""
        if len(x) != len(y) or len(x) < 3:
            return 0.0
        
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(a * b for a, b in zip(x, y))
        sum_x2 = sum(a * a for a in x)
        sum_y2 = sum(b * b for b in y)
        
        num = n * sum_xy - sum_x * sum_y
        den = ((n * sum_x2 - sum_x ** 2) * (n * sum_y2 - sum_y ** 2)) ** 0.5
        
        if den == 0:
            return 0.0
        
        corr = num / den
        # Clamp to [-1, 1] to handle floating point errors
        return max(-1.0, min(1.0, corr))
    
    def _beta(self, btc_returns: list, alt_returns: list) -> float:
        """Calculate beta (sensitivity) of altcoin to BTC returns."""
        if len(btc_returns) != len(alt_returns) or len(btc_returns) < 3:
            return 0.0
        
        n = len(btc_returns)
        mean_btc = sum(btc_returns) / n
        mean_alt = sum(alt_returns) / n
        
        cov = sum((a - mean_btc) * (b - mean_alt)
                  for a, b in zip(btc_returns, alt_returns)) / n
        var_btc = sum((a - mean_btc) ** 2 for a in btc_returns) / n
        
        if var_btc == 0:
            return 0.0
        
        return cov / var_btc
    
    def _alignment_rate(self, btc_returns: list, alt_returns: list) -> float:
        """Calculate how often altcoin moves in same direction as BTC."""
        if len(btc_returns) != len(alt_returns) or len(btc_returns) < 3:
            return 0.0
        
        aligned = sum(1 for a, b in zip(btc_returns, alt_returns)
                      if (a > 0 and b > 0) or (a < 0 and b < 0))
        return aligned / len(btc_returns)
    
    def _big_move_alignment(self, btc_returns: list, alt_returns: list) -> float:
        """
        Calculate how often altcoin moves significantly when BTC moves >1%.
        This is the key metric for our strategy.
        """
        pairs = list(zip(btc_returns, alt_returns))
        big_btc_moves = [(b, a) for b, a in pairs if abs(b) >= 0.01]
        
        if not big_btc_moves:
            return 0.0
        
        aligned = sum(1 for b, a in big_btc_moves
                      if (b > 0 and a > 0.005) or (b < 0 and a < -0.005))
        return aligned / len(big_btc_moves)
    
    def _calculate_score(self, r: dict) -> float:
        """
        Calculate a composite score for ranking coins.
        Higher score = better candidate for our strategy.
        
        Factors:
        - Correlation: 0.60-0.80 is ideal (sweet spot)
        - Beta: higher is better (>1.5x is great)
        - Volume: higher is better (liquidity)
        - Big-align: higher is better (follows BTC on big moves)
        """
        corr_score = 0
        c = abs(r['correlation'])
        if 0.60 <= c <= 0.80:
            corr_score = 100  # Perfect
        elif 0.50 <= c <= 0.85:
            corr_score = 80   # Good
        elif 0.40 <= c <= 0.90:
            corr_score = 50   # OK
        else:
            corr_score = 10   # Too low or too high
        
        beta_score = min(100, r['beta'] * 50)  # beta=2.0 -> 100
        vol_score = min(100, r['avg_volume_usd'] / 1000000 * 10)  # $10M -> 100
        align_score = r['big_align'] * 100  # 0.75 -> 75
        
        return corr_score * 0.35 + beta_score * 0.30 + vol_score * 0.15 + align_score * 0.20
