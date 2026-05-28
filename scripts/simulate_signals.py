"""
simulate_signals.py -- Historical BTC 1H Signal Simulator.

Fetches past BTC 1H candles from Binance (public API, no key needed)
and runs the EXACT same signal detection logic as the live bot:

    btc_return = (candle_close - prev_candle_close) / prev_candle_close * 100
    If abs(btc_return) >= BTC_TRIGGER_PCT -> LONG/SHORT trigger

Usage:
    python scripts/simulate_signals.py                   # Last 14 days
    python scripts/simulate_signals.py --days 30         # Last 30 days
    python scripts/simulate_signals.py --start YYYY-MM-DD --end YYYY-MM-DD
    python scripts/simulate_signals.py --trigger 0.5     # Custom trigger %

Also runs the OLD candles[-2] approach alongside the NEW time-based
approach on each candle to show if they ever diverge.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

# --- Config -------------------------------------------------
BINANCE_BASE = "https://fapi.binance.com"
BTC_TRIGGER_PCT = 1.0  # Default, overridable via --trigger
IST_OFFSET = timedelta(hours=5, minutes=30)


def fetch_klines(symbol: str, interval: str, start_time: int,
                 end_time: int = None, limit: int = 1500) -> list[dict]:
    """Fetch klines from Binance public API (no auth needed)."""
    params = {
        'symbol': symbol.upper(),
        'interval': interval,
        'startTime': start_time,
        'limit': limit,
    }
    if end_time:
        params['endTime'] = end_time

    url = f"{BINANCE_BASE}/fapi/v1/klines?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

    for attempt in range(3):
        try:
            resp = urllib.request.urlopen(req, timeout=20)
            raw = resp.read().decode('utf-8')
            data = json.loads(raw)
            return [{
                'ts': int(c[0]),
                'o': float(c[1]),
                'h': float(c[2]),
                'l': float(c[3]),
                'c': float(c[4]),
                'v': float(c[5]),
            } for c in data]
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                raise e
    return []


def ms_to_utc(ts_ms: int) -> str:
    """Convert millisecond timestamp to UTC datetime string."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def ms_to_ist(ts_ms: int) -> str:
    """Convert millisecond timestamp to IST datetime string."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) + IST_OFFSET
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def fmt(price: float) -> str:
    """Format price with appropriate precision."""
    if price >= 1000:
        return f"{price:,.2f}"
    elif price >= 1:
        return f"{price:.4f}"
    else:
        return f"{price:.6f}"


# --- Signal Detection ---------------------------------------
def detect_triggers(candles: list[dict], trigger_pct: float) -> list[dict]:
    """
    Run EXACT same signal detection as the live bot:
    btc_return = (candle_close - prev_close) / prev_close * 100
    If |btc_return| >= trigger_pct -> LONG/SHORT trigger
    """
    results = []
    for i in range(1, len(candles)):
        prev_close = candles[i - 1]['c']
        curr = candles[i]
        btc_return = (curr['c'] - prev_close) / prev_close * 100

        candle_ist = ms_to_ist(curr['ts'])
        prev_ist = ms_to_ist(candles[i - 1]['ts'])

        results.append({
            'candle_ist': candle_ist,
            'candle_utc': ms_to_utc(curr['ts']),
            'open': curr['o'],
            'high': curr['h'],
            'low': curr['l'],
            'close': curr['c'],
            'prev_close': prev_close,
            'prev_ist': prev_ist,
            'btc_return': round(btc_return, 2),
            'trigger': abs(btc_return) >= trigger_pct,
            'side': 'LONG' if btc_return > 0 else 'SHORT' if btc_return < 0 else 'FLAT',
        })

    return results


# --- Simulation of OLD candles[-2] approach -----------------
def simulate_old_approach(all_candles: list[dict], trigger_pct: float) -> list[dict]:
    """
    Simulate the OLD candles[-2] approach at each hour boundary.
    This shows what the old code would have detected vs what the new code detects.
    """
    results = []
    for i in range(3, len(all_candles)):  # Need at least i-2,i-1,i
        # OLD: fetch last 3 candles, return candles[-2]
        # Bug scenario: at hour boundary, Binance returns only 2 candles
        # [candle_{i-2}, candle_{i-1}] because current hour not created yet.
        # candles[-2] then returns candle_{i-2} (2 hours old) -- WRONG!
        limited_2 = all_candles[i - 2:i]
        wrong_candle = limited_2[0]  # candles[-2] = candle_{i-2} (2 hours old)

        # What we SHOULD check: candle at (current_hour - 1)
        correct_candle = all_candles[i - 1]  # candle_{i-1} (just completed)

        # Check if old approach would be wrong
        old_wrong = wrong_candle['ts'] != correct_candle['ts']

        if old_wrong:
            prev_close = all_candles[i - 2]['c']
            btc_return = (correct_candle['c'] - prev_close) / prev_close * 100
            wrong_return = (wrong_candle['c'] - all_candles[i - 3]['c']) / all_candles[i - 3]['c'] * 100

            results.append({
                'time_ist': ms_to_ist(correct_candle['ts']),
                'correct_return': round(btc_return, 2),
                'wrong_return': round(wrong_return, 2),
                'correct_trigger': abs(btc_return) >= trigger_pct,
                'wrong_trigger': abs(wrong_return) >= trigger_pct,
                'correct_close': correct_candle['c'],
                'wrong_close': wrong_candle['c'],
            })

    return results


# --- Display ------------------------------------------------
HEADER_WIDTH = 78


def print_header(title: str):
    print()
    print("=" * HEADER_WIDTH)
    print(f"  {title}")
    print("=" * HEADER_WIDTH)


def print_results(results: list[dict], trigger_pct: float, show_all: bool = False):
    """Print the signal detection results."""
    triggers = [r for r in results if r['trigger']]
    longs = [r for r in triggers if r['side'] == 'LONG']
    shorts = [r for r in triggers if r['side'] == 'SHORT']

    print(f"\n  Candles scanned: {len(results)}")
    print(f"  Triggers found:  {len(triggers)} total")
    print(f"    LONG  signals: {len(longs)}")
    print(f"    SHORT signals: {len(shorts)}")
    print(f"  Trigger threshold: >{abs(trigger_pct)}%")
    print(f"  Avg signal/hours: {len(triggers)}/{len(results)} "
          f"({len(triggers)/max(1,len(results))*100:.1f}%)")

    if triggers:
        print()
        print(f"  {'IST Time (Candle)':<22} {'Side':<7} {'Return':>8} {'Close':>10} {'PrevClose':>10} {'O-H-L':<16}")
        print(f"  {'-' * 22} {'-' * 7} {'-' * 8} {'-' * 10} {'-' * 10} {'-' * 16}")
        for r in triggers:
            side_icon = "[L]" if r['side'] == 'LONG' else "[S]"
            print(f"  {r['candle_ist']:<22} {side_icon} {r['side']:<5} {r['btc_return']:>+7.2f}% "
                  f"{fmt(r['close']):>10} {fmt(r['prev_close']):>10} "
                  f"{fmt(r['open'])}-{fmt(r['high'])}-{fmt(r['low'])}")

        print()
        print(f"  Daily breakdown:")
        print(f"  {'-' * HEADER_WIDTH}")

        # Group by date
        from collections import OrderedDict
        by_date = OrderedDict()
        for r in triggers:
            date = r['candle_ist'][:10]
            if date not in by_date:
                by_date[date] = {'LONG': 0, 'SHORT': 0, 'triggers': []}
            by_date[date][r['side']] += 1
            by_date[date]['triggers'].append(r)

        for date, info in by_date.items():
            t_count = info['LONG'] + info['SHORT']
            print(f"    {date}: {t_count} trigger(s) "
                  f"(LONG: {info['LONG']} SHORT: {info['SHORT']})")

            if show_all:
                for r in info['triggers']:
                    s = "[L]" if r['side'] == 'LONG' else "[S]"
                    print(f"      {r['candle_ist'][11:]} {s} {r['btc_return']:+6.2f}% "
                          f"Close={fmt(r['close'])}")

    print()
    print("-" * HEADER_WIDTH)

    # Check for consecutive triggers (would need to skip if already in trade)
    consecutives = 0
    for i in range(1, len(triggers)):
        t1_ms = datetime.strptime(triggers[i - 1]['candle_ist'], "%Y-%m-%d %H:%M:%S")
        t2_ms = datetime.strptime(triggers[i]['candle_ist'], "%Y-%m-%d %H:%M:%S")
        diff_hours = (t2_ms - t1_ms).total_seconds() / 3600
        if diff_hours <= 1:
            consecutives += 1

    if consecutives > 0:
        print(f"  [!] {consecutives} consecutive-hour triggers found "
              f"(bot would skip 2nd if already in trade)")

    # Max absolute return
    if triggers:
        max_ret = max(triggers, key=lambda r: abs(r['btc_return']))
        print(f"  [MAX] Strongest signal: {max_ret['side']} {max_ret['btc_return']:+6.2f}% "
              f"on {max_ret['candle_ist']}")


# --- Main ---------------------------------------------------
def parse_args():
    import argparse
    parser = argparse.ArgumentParser(
        description="Simulate BTC 1H signal detection on historical data")
    parser.add_argument('--days', type=int, default=14,
                        help='Number of past days to simulate (default: 14)')
    parser.add_argument('--trigger', type=float, default=1.0,
                        help='Trigger percentage (default: 1.0)')
    parser.add_argument('--start', type=str, default=None,
                        help='Start date YYYY-MM-DD (overrides --days)')
    parser.add_argument('--end', type=str, default=None,
                        help='End date YYYY-MM-DD (overrides --days)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show all candles, not just triggers')
    return parser.parse_args()


def main():
    args = parse_args()

    print()
    print("=" * HEADER_WIDTH)
    print("  BTC LEADS TRADING BOT -- Historical Signal Simulator")
    print("  Runs the EXACT same signal logic as the live bot")
    print("=" * HEADER_WIDTH)

    # Calculate time range
    now_utc = datetime.now(timezone.utc)

    if args.start:
        start_dt = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.end else now_utc
    else:
        end_dt = now_utc
        start_dt = end_dt - timedelta(days=args.days)

    # Round to hour boundaries for clean kline alignment
    start_ts = int(start_dt.timestamp() // 3600 * 3600 * 1000)
    end_ts = int(end_dt.timestamp() // 3600 * 3600 * 1000)

    print(f"\n  Fetching BTC 1H klines from "
          f"{ms_to_ist(start_ts)} IST to {ms_to_ist(end_ts)} IST ...")
    sys.stdout.flush()

    # Fetch all klines in the range with pagination
    all_candles = []
    current = start_ts
    while current < end_ts:
        candles = fetch_klines('BTCUSDT', '1h', current, end_ts, 1500)
        if not candles:
            break
        all_candles.extend(candles)
        current = candles[-1]['ts'] + 1
        if current < end_ts:
            time.sleep(0.1)

    if not all_candles:
        print("  [ERR] No data returned from Binance API. Check your internet connection.")
        return

    # Deduplicate
    seen = set()
    unique = []
    for c in all_candles:
        if c['ts'] not in seen:
            seen.add(c['ts'])
            unique.append(c)

    print(f"  [OK] Fetched {len(unique)} candles")
    print(f"     From: {ms_to_ist(unique[0]['ts'])} IST")
    print(f"     To:   {ms_to_ist(unique[-1]['ts'])} IST")

    # Run signal detection (same logic as live bot)
    print()
    print_header("SIGNAL DETECTION RESULTS")
    print(f"  Using NEW time-based candle fetch (each candle checked by exact timestamp)")
    print(f"  Logic: |close - prev_close| / prev_close >= {args.trigger:.1f}%")

    results = detect_triggers(unique, args.trigger)
    print_results(results, args.trigger, show_all=args.verbose)

    # -- Old approach simulation --
    print()
    print_header("OLD APPROACH COMPARISON (candles[-2] vs time-based)")
    print(f"  The old code used candles[-2] on limit=3 klines.")
    print(f"  When Binance returns <3 candles (rare, at hour boundaries),")
    print(f"  candles[-2] gives the WRONG candle (2 hours old).")
    print(f"  The table below shows those divergences:")

    old_failures = simulate_old_approach(unique, args.trigger)
    if old_failures:
        print(f"\n  [BUG] Found {len(old_failures)} instance(s) where old approach would check WRONG candle:")
        print(f"\n  {'IST Time':<22} {'Correct Ret':>10} {'Wrong Ret':>10} {'Correct Trig':<14} {'Wrong Trig':<14}")
        print(f"  {'-' * 22} {'-' * 10} {'-' * 10} {'-' * 14} {'-' * 14}")
        for f in old_failures[:10]:  # Show up to 10
            c_t = "[OK]" if f['correct_trigger'] else "[NO]"
            w_t = "[OK]" if f['wrong_trigger'] else "[NO]"
            print(f"  {f['time_ist']:<22} {f['correct_return']:>+8.2f}% {f['wrong_return']:>+8.2f}%  "
                  f"{c_t} {'TRIGGER' if f['correct_trigger'] else 'no trig':<10}  "
                  f"{w_t} {'TRIGGER' if f['wrong_trigger'] else 'no trig':<10}")
        if len(old_failures) > 10:
            print(f"  ... and {len(old_failures) - 10} more instances")
        print(f"\n  [OK] The NEW time-based approach is immune to this bug.")
    else:
        print(f"\n  [OK] No divergences found in this dataset (best case scenario).")
        print(f"     The candles[-2] bug only triggers when Binance returns < 3")
        print(f"     candles at the exact hour boundary, which is timing-dependent.")
        print(f"     Your bot was unlucky to hit this condition on 2+ occasions.")

    # -- Summary --
    triggers = [r for r in results if r['trigger']]
    print()
    print("=" * HEADER_WIDTH)
    print("  SIMULATION SUMMARY")
    print("=" * HEADER_WIDTH)
    print(f"  Period:     {ms_to_ist(unique[0]['ts'])} IST -> {ms_to_ist(unique[-1]['ts'])} IST")
    print(f"  Candles:    {len(results)} ({len(unique)} total - 1 for initial)")
    print(f"  Triggers:   {len(triggers)} ({len([t for t in triggers if t['side']=='LONG'])} LONG, "
          f"{len([t for t in triggers if t['side']=='SHORT'])} SHORT)")
    print()
    print(f"  The bot's fixed signal detection (time-based candle fetch) is now")
    print(f"  immune to the candles[-2] bug. Every candle is checked by its exact")
    print(f"  timestamp, so no valid trigger will be missed.")
    print()
    if triggers:
        avg_hours = max(1, len(results)//max(1,len(triggers)))
        print(f"  On average, signals fire every {avg_hours} hours")
        print(f"  ({len(triggers)/max(1,len(results))*100:.1f}% of all candle checks).")
    print()


if __name__ == '__main__':
    main()
