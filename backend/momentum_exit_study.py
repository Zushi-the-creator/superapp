"""
Momentum Exit Strategy Study
=============================
Tests 12 exit strategies on Minervini 6/6 momentum entries across all cached stocks.
Determines optimal exit for momentum strategy (parallel to exit_study.py for MR).

Entry: Minervini 6/6 trend template + ret_20d > 5% + next-day open + 0.30% fee
Exits: Fixed (14-60d), Trailing (8-15%), SMA breakdown (10/20/50), ATR trailing (2x)
"""

import sqlite3
import os
import time
from datetime import datetime
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stock_cache.db")
FEE_PCT = 0.30  # Round-trip fee


def _sma_arr(closes, period):
    n = len(closes)
    sma = [0.0] * n
    if n < period:
        return sma
    s = sum(closes[:period])
    sma[period - 1] = s / period
    for i in range(period, n):
        s += closes[i] - closes[i - period]
        sma[i] = s / period
    return sma


def _atr_arr(highs, lows, closes, period=14):
    """ATR array for trailing stop calculation."""
    n = len(closes)
    atr = [0.0] * n
    trs = []
    for i in range(1, n):
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
        trs.append(tr)
        if len(trs) >= period:
            atr[i] = sum(trs[-period:]) / period
    return atr


def _apply_exit(closes, opens, highs, lows, sma10, sma20, sma50, atr, entry_idx, entry_price, exit_type, max_bars=80):
    """Apply an exit strategy from entry_idx, return (exit_idx, exit_price)."""
    n = len(closes)
    end = min(entry_idx + max_bars, n - 1)

    if exit_type.startswith("Fixed"):
        days = int(exit_type.replace("Fixed", "").replace("d", ""))
        exit_idx = min(entry_idx + days, n - 1)
        return exit_idx, closes[exit_idx]

    elif exit_type.startswith("Trail"):
        pct = int(exit_type.replace("Trail", "")) / 100.0
        peak = entry_price
        for i in range(entry_idx + 1, end + 1):
            peak = max(peak, highs[i])
            if closes[i] < peak * (1 - pct):
                return i, closes[i]
        return end, closes[end]

    elif exit_type == "SMA10":
        for i in range(entry_idx + 2, end + 1):  # Skip first day
            if sma10[i] > 0 and closes[i] < sma10[i]:
                return i, closes[i]
        return end, closes[end]

    elif exit_type == "SMA20":
        for i in range(entry_idx + 2, end + 1):
            if sma20[i] > 0 and closes[i] < sma20[i]:
                return i, closes[i]
        return end, closes[end]

    elif exit_type == "SMA50Break":
        for i in range(entry_idx + 2, end + 1):
            if sma50[i] > 0 and closes[i] < sma50[i]:
                return i, closes[i]
        return end, closes[end]

    elif exit_type == "ATRTrail2x":
        peak = entry_price
        for i in range(entry_idx + 1, end + 1):
            peak = max(peak, highs[i])
            stop = peak - 2 * atr[i] if atr[i] > 0 else peak * 0.90
            if closes[i] < stop:
                return i, closes[i]
        return end, closes[end]

    return end, closes[end]


EXIT_STRATEGIES = [
    "Fixed14d", "Fixed21d", "Fixed30d", "Fixed45d", "Fixed60d",
    "Trail8", "Trail10", "Trail15",
    "SMA10", "SMA20", "SMA50Break",
    "ATRTrail2x",
]

# ret_20d zones
ZONES = [(5, 10), (10, 20), (20, 30), (30, 999)]
ZONE_LABELS = ["5-10%", "10-20%", "20-30%", "30%+"]


def run_study():
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT ticker, COUNT(*) as cnt FROM daily_prices GROUP BY ticker HAVING cnt >= 300")
    tickers = [r[0] for r in c.fetchall()]
    print(f"[MomentumExitStudy] {len(tickers)} stocks with 300+ bars")

    # Results: {exit_type: [returns]}
    results = {ex: [] for ex in EXIT_STRATEGIES}
    zone_results = {ex: {zl: [] for zl in ZONE_LABELS} for ex in EXIT_STRATEGIES}
    total_entries = 0
    stocks_with_entries = 0

    for ti, ticker in enumerate(tickers):
        c.execute("SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker=? ORDER BY date", (ticker,))
        rows = c.fetchall()
        if len(rows) < 300:
            continue

        closes = [r[4] for r in rows]
        opens = [r[1] for r in rows]
        highs = [r[2] for r in rows]
        lows = [r[3] for r in rows]
        volumes = [r[5] for r in rows]
        n = len(closes)

        sma50 = _sma_arr(closes, 50)
        sma150 = _sma_arr(closes, 150)
        sma200 = _sma_arr(closes, 200)
        sma10 = _sma_arr(closes, 10)
        sma20 = _sma_arr(closes, 20)
        atr = _atr_arr(highs, lows, closes, 14)

        # Find all momentum entries
        entries_for_stock = 0
        last_exit = -1

        for i in range(252, n - 62):  # Need 252 bars lookback + 62 bars forward
            if i <= last_exit:
                continue

            # Minervini 6/6 trend template
            if sma50[i] <= 0 or sma150[i] <= 0 or sma200[i] <= 0:
                continue
            if not (closes[i] > sma50[i] and closes[i] > sma150[i] and closes[i] > sma200[i]):
                continue
            if not (sma50[i] > sma150[i] > sma200[i]):
                continue

            # 52w high/low
            high_52w = max(highs[max(0, i-252):i+1])
            low_52w = min(lows[max(0, i-252):i+1])
            if high_52w <= 0 or low_52w <= 0:
                continue
            pct_from_high = ((closes[i] / high_52w) - 1) * 100
            pct_from_low = ((closes[i] / low_52w) - 1) * 100
            if pct_from_high < -25 or pct_from_low < 30:
                continue

            # ret_20d > 5%
            if i < 20:
                continue
            ret_20d = ((closes[i] / closes[i - 20]) - 1) * 100
            if ret_20d < 5:
                continue

            # Entry at next-day open
            if i + 1 >= n:
                continue
            entry_price = opens[i + 1]
            if entry_price <= 0:
                entry_price = closes[i]
            if entry_price < 10:  # Min price filter
                continue

            # Determine zone
            zone_label = ZONE_LABELS[-1]
            for (zlo, zhi), zl in zip(ZONES, ZONE_LABELS):
                if zlo <= ret_20d < zhi:
                    zone_label = zl
                    break

            # Test all exits
            max_exit_idx = i + 1
            for ex in EXIT_STRATEGIES:
                exit_idx, exit_price = _apply_exit(
                    closes, opens, highs, lows, sma10, sma20, sma50, atr,
                    i + 1, entry_price, ex
                )
                ret = ((exit_price - entry_price) / entry_price) * 100 - FEE_PCT
                results[ex].append(ret)
                zone_results[ex][zone_label].append(ret)
                max_exit_idx = max(max_exit_idx, exit_idx)

            last_exit = max_exit_idx
            entries_for_stock += 1
            total_entries += 1

        if entries_for_stock > 0:
            stocks_with_entries += 1

        if (ti + 1) % 500 == 0:
            elapsed = time.time() - t0
            print(f"  [{ti+1}/{len(tickers)}] {total_entries} entries from {stocks_with_entries} stocks ({elapsed:.1f}s)")

    conn.close()
    elapsed = time.time() - t0

    # Print results
    print(f"\n{'='*80}")
    print(f"MOMENTUM EXIT STUDY — {total_entries} entries from {stocks_with_entries} stocks ({elapsed:.1f}s)")
    print(f"{'='*80}\n")

    print(f"{'Exit':<15} {'Trades':>7} {'WR':>7} {'Avg Ret':>9} {'Med Ret':>9} {'PF':>7} {'Avg Days':>9}")
    print("-" * 70)

    for ex in EXIT_STRATEGIES:
        trades = results[ex]
        if not trades:
            continue
        wins = sum(1 for r in trades if r > 0)
        wr = wins / len(trades) * 100
        avg = sum(trades) / len(trades)
        sorted_trades = sorted(trades)
        med = sorted_trades[len(sorted_trades) // 2]
        gain = sum(r for r in trades if r > 0) or 0.01
        loss = abs(sum(r for r in trades if r <= 0)) or 0.01
        pf = gain / loss
        print(f"{ex:<15} {len(trades):>7} {wr:>6.1f}% {avg:>+8.2f}% {med:>+8.2f}% {pf:>6.2f}")

    # Zone breakdown for top 3 exits
    print(f"\n{'='*80}")
    print("ZONE BREAKDOWN (by ret_20d at entry)")
    print(f"{'='*80}\n")

    # Find top 3 by avg return
    ranked = sorted(EXIT_STRATEGIES, key=lambda ex: sum(results[ex]) / max(len(results[ex]), 1), reverse=True)

    for ex in ranked[:4]:
        print(f"\n  {ex}:")
        print(f"  {'Zone':<10} {'Trades':>7} {'WR':>7} {'Avg Ret':>9}")
        print(f"  {'-'*40}")
        for zl in ZONE_LABELS:
            zt = zone_results[ex][zl]
            if not zt:
                continue
            zw = sum(1 for r in zt if r > 0) / len(zt) * 100
            za = sum(zt) / len(zt)
            print(f"  {zl:<10} {len(zt):>7} {zw:>6.1f}% {za:>+8.2f}%")

    # Summary recommendation
    print(f"\n{'='*80}")
    print("RECOMMENDATION")
    print(f"{'='*80}")
    best = ranked[0]
    best_trades = results[best]
    best_wr = sum(1 for r in best_trades if r > 0) / len(best_trades) * 100
    best_avg = sum(best_trades) / len(best_trades)
    print(f"\n  Best exit: {best} — WR {best_wr:.1f}%, Avg Return {best_avg:+.2f}%")
    print(f"  Runner-up: {ranked[1]}")
    print(f"  Total trades analyzed: {total_entries}")


if __name__ == "__main__":
    run_study()
