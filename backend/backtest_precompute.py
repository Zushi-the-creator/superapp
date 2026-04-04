"""
Backtest Precompute Engine
==========================
Pre-computes backtest statistics (WR, avg return, trade count) for ALL stocks
in stock_cache.db and stores them in a `backtest_cache` table.

This makes the daily scan instant (<5s) — the evaluator just looks up
pre-computed WR/return instead of running a full backtest per stock.

MR backtest:  RSI(2) < 10, ATR >= 3%, price >= $10, 45d hold,
              next-day open entry, 0.30% fee, non-overlapping trades.
Momentum:     Minervini 6/6, ret_20d > 5%, 60d hold, same fee rules.

Usage:
    python3 backtest_precompute.py              # Full compute (~60s for 3000 stocks)
    python3 backtest_precompute.py --stats       # Show cache stats
"""

import sqlite3
import os
import time
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stock_cache.db")

# Bayesian WR prior: 53.5% universe base rate, weight of 10 pseudo-observations
_UNIVERSE_WR = 53.5
_PRIOR_WEIGHT = 10

# Hold periods
MR_HOLD_DAYS = 60
MOM_HOLD_DAYS = 90

# Fee per trade (round-trip)
FEE_PCT = 0.30


def _ensure_table(conn):
    """Create backtest_cache table if it doesn't exist."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS backtest_cache (
            ticker TEXT PRIMARY KEY,
            mr_wr REAL,
            mr_avg_return REAL,
            mr_trades INTEGER,
            mr_score REAL,
            mom_wr REAL,
            mom_avg_return REAL,
            mom_trades INTEGER,
            mom_score REAL,
            last_computed TEXT
        )
    ''')
    conn.commit()


def _bayesian_wr(wins, total):
    """Bayesian win rate with universe prior."""
    pw = _UNIVERSE_WR / 100 * _PRIOR_WEIGHT
    return (wins + pw) / (total + _PRIOR_WEIGHT) * 100


def _rsi2_arr(closes, n):
    """Compute RSI(2) array in O(n)."""
    rsi = [50.0] * n
    for i in range(2, n):
        c1 = closes[i] - closes[i - 1]
        c2 = closes[i - 1] - closes[i - 2]
        ag = (max(0, c1) + max(0, c2)) / 2
        al = (max(0, -c1) + max(0, -c2)) / 2
        if al > 0:
            rsi[i] = 100.0 - 100.0 / (1 + ag / al)
        elif ag > 0:
            rsi[i] = 100.0
        else:
            rsi[i] = 50.0
    return rsi


def _sma_arr(closes, period, n):
    """Compute SMA array in O(n)."""
    sma = [0.0] * n
    if n < period:
        return sma
    run = sum(closes[:period])
    sma[period - 1] = run / period
    for i in range(period, n):
        run += closes[i] - closes[i - period]
        sma[i] = run / period
    return sma


def _backtest_mr(closes, opens, highs, lows, n):
    """Mean reversion backtest: RSI(2)<10, ATR>=3%, price>=$10, 45d hold.
    Returns (trades, wins, total_return)."""
    if n < 100:  # Need enough bars
        return 0, 0, 0.0

    rsi2 = _rsi2_arr(closes, n)
    trades = 0
    wins = 0
    total_ret = 0.0
    last_exit = -1

    for i in range(14, n - MR_HOLD_DAYS - 2):
        if i <= last_exit:
            continue
        if rsi2[i] >= 10:
            continue
        if closes[i] < 10:
            continue

        # ATR(14) % check
        atr_sum = 0.0
        atr_count = 0
        for j in range(max(1, i - 13), i + 1):
            tr = max(
                highs[j] - lows[j],
                abs(highs[j] - closes[j - 1]),
                abs(lows[j] - closes[j - 1])
            )
            atr_sum += tr
            atr_count += 1
        if atr_count == 0 or closes[i] <= 0:
            continue
        atr_pct = (atr_sum / atr_count) / closes[i] * 100
        if atr_pct < 3:
            continue

        # Entry at next-day open
        ep = opens[i + 1] if opens[i + 1] > 0 else closes[i]
        if ep < 10:
            continue

        # Exit at close after hold period
        exit_idx = min(i + 1 + MR_HOLD_DAYS, n - 1)
        ret = ((closes[exit_idx] - ep) / ep) * 100 - FEE_PCT

        trades += 1
        total_ret += ret
        if ret > 0:
            wins += 1
        last_exit = exit_idx

    return trades, wins, total_ret


def _backtest_momentum(closes, opens, highs, lows, n):
    """Momentum backtest: Minervini 6/6, ret_20d>5%, 60d hold.
    Returns (trades, wins, total_return)."""
    if n < 320:  # Need 252 lookback + 60 forward + buffer
        return 0, 0, 0.0

    sma50 = _sma_arr(closes, 50, n)
    sma150 = _sma_arr(closes, 150, n)
    sma200 = _sma_arr(closes, 200, n)

    trades = 0
    wins = 0
    total_ret = 0.0
    last_exit = -1

    for i in range(252, n - MOM_HOLD_DAYS - 2):
        if i <= last_exit:
            continue

        # Minervini 6/6 rules
        if sma50[i] <= 0 or sma150[i] <= 0 or sma200[i] <= 0:
            continue
        if not (closes[i] > sma50[i] and closes[i] > sma150[i] and closes[i] > sma200[i]):
            continue
        if not (sma50[i] > sma150[i] > sma200[i]):
            continue

        high_52w = max(highs[max(0, i - 252):i + 1])
        low_52w = min(lows[max(0, i - 252):i + 1])
        if high_52w <= 0 or low_52w <= 0:
            continue
        if ((closes[i] / high_52w) - 1) * 100 < -25:
            continue
        if ((closes[i] / low_52w) - 1) * 100 < 30:
            continue

        # ret_20d > 5%
        if i < 20:
            continue
        ret_20d = ((closes[i] / closes[i - 20]) - 1) * 100
        if ret_20d < 5:
            continue

        # Entry at next-day open
        ep = opens[i + 1] if opens[i + 1] > 0 else closes[i]
        if ep < 10:
            continue

        # Fixed 60d exit
        exit_idx = min(i + 1 + MOM_HOLD_DAYS, n - 1)
        ret = ((closes[exit_idx] - ep) / ep) * 100 - FEE_PCT

        trades += 1
        total_ret += ret
        if ret > 0:
            wins += 1
        last_exit = exit_idx

    return trades, wins, total_ret


def precompute_all(db_path=DB_PATH, force=False):
    """Run full backtest on ALL stocks in stock_cache.db, store results in backtest_cache.

    Args:
        db_path: Path to stock_cache.db
        force: If True, recompute all. If False, skip stocks computed today.

    Returns:
        dict with stats: total, computed, skipped, mr_positive, mom_positive, elapsed
    """
    t0 = time.time()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _ensure_table(conn)

    today = datetime.now().strftime('%Y-%m-%d')

    # Get all tickers with enough data
    cursor = conn.execute(
        "SELECT ticker, COUNT(*) as cnt FROM daily_prices GROUP BY ticker HAVING cnt >= 80"
    )
    all_tickers = {r[0]: r[1] for r in cursor.fetchall()}

    # Check which need recomputing
    if not force:
        already = set()
        rows = conn.execute(
            "SELECT ticker FROM backtest_cache WHERE last_computed = ?", (today,)
        ).fetchall()
        already = {r[0] for r in rows}
    else:
        already = set()

    to_compute = [t for t in all_tickers if t not in already]
    skipped = len(all_tickers) - len(to_compute)

    if not to_compute:
        elapsed = time.time() - t0
        print(f"[Precompute] All {len(all_tickers)} stocks already computed today. ({elapsed:.1f}s)")
        return {
            "total": len(all_tickers), "computed": 0, "skipped": skipped,
            "mr_positive": 0, "mom_positive": 0, "elapsed": round(elapsed, 1)
        }

    print(f"[Precompute] Computing backtests for {len(to_compute)} stocks "
          f"(skipping {skipped} already done today)...")

    # Batch process: load data and compute
    results = []
    mr_positive = 0
    mom_positive = 0
    processed = 0

    for ticker in to_compute:
        # Load price data
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM daily_prices "
            "WHERE ticker=? ORDER BY date", (ticker,)
        ).fetchall()

        if len(rows) < 80:
            continue

        opens = [r[1] for r in rows]
        highs = [r[2] for r in rows]
        lows = [r[3] for r in rows]
        closes = [r[4] for r in rows]
        n = len(closes)

        # Mean Reversion backtest
        mr_trades, mr_wins, mr_total_ret = _backtest_mr(closes, opens, highs, lows, n)
        if mr_trades >= 1:
            mr_wr = _bayesian_wr(mr_wins, mr_trades)
            mr_avg = mr_total_ret / mr_trades
            mr_score = mr_wr * mr_avg / 100
        else:
            mr_wr = 0.0
            mr_avg = 0.0
            mr_score = 0.0

        # Momentum backtest
        mom_trades, mom_wins, mom_total_ret = _backtest_momentum(closes, opens, highs, lows, n)
        if mom_trades >= 1:
            mom_wr = _bayesian_wr(mom_wins, mom_trades)
            mom_avg = mom_total_ret / mom_trades
            mom_score = mom_wr * mom_avg / 100
        else:
            mom_wr = 0.0
            mom_avg = 0.0
            mom_score = 0.0

        if mr_score > 0:
            mr_positive += 1
        if mom_score > 0:
            mom_positive += 1

        results.append((
            ticker,
            round(mr_wr, 2), round(mr_avg, 2), mr_trades, round(mr_score, 2),
            round(mom_wr, 2), round(mom_avg, 2), mom_trades, round(mom_score, 2),
            today
        ))

        processed += 1

        # Batch commit every 100 stocks (saves partial progress + releases GIL)
        if processed % 100 == 0:
            conn.executemany(
                "INSERT OR REPLACE INTO backtest_cache "
                "(ticker, mr_wr, mr_avg_return, mr_trades, mr_score, "
                " mom_wr, mom_avg_return, mom_trades, mom_score, last_computed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                results[-100:]
            )
            conn.commit()
            # Brief sleep to yield CPU to other threads (HTTP handlers)
            time.sleep(0.01)

        if processed % 500 == 0:
            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0
            print(f"  [{processed}/{len(to_compute)}] {elapsed:.1f}s ({rate:.0f} stocks/s)")

    # Final commit for remaining
    remainder = processed % 100
    if remainder > 0 and results:
        conn.executemany(
            "INSERT OR REPLACE INTO backtest_cache "
            "(ticker, mr_wr, mr_avg_return, mr_trades, mr_score, "
            " mom_wr, mom_avg_return, mom_trades, mom_score, last_computed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            results[-remainder:]
        )
        conn.commit()

    conn.close()

    elapsed = time.time() - t0
    print(f"[Precompute] {processed} stocks computed in {elapsed:.1f}s")
    print(f"  MR positive score: {mr_positive} | Momentum positive: {mom_positive}")

    return {
        "total": len(all_tickers),
        "computed": processed,
        "skipped": skipped,
        "mr_positive": mr_positive,
        "mom_positive": mom_positive,
        "elapsed": round(elapsed, 1),
    }


def get_stats(db_path=DB_PATH):
    """Return stats about the backtest cache."""
    conn = sqlite3.connect(db_path)
    _ensure_table(conn)

    total = conn.execute("SELECT COUNT(*) FROM backtest_cache").fetchone()[0]
    today = datetime.now().strftime('%Y-%m-%d')
    fresh = conn.execute(
        "SELECT COUNT(*) FROM backtest_cache WHERE last_computed = ?", (today,)
    ).fetchone()[0]
    mr_pos = conn.execute(
        "SELECT COUNT(*) FROM backtest_cache WHERE mr_score > 0"
    ).fetchone()[0]
    mom_pos = conn.execute(
        "SELECT COUNT(*) FROM backtest_cache WHERE mom_score > 0"
    ).fetchone()[0]

    conn.close()
    return {
        "total": total, "fresh_today": fresh, "stale": total - fresh,
        "mr_positive": mr_pos, "mom_positive": mom_pos,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Backtest Precompute Engine")
    parser.add_argument("--stats", action="store_true", help="Show cache stats")
    parser.add_argument("--force", action="store_true", help="Force recompute all")
    args = parser.parse_args()

    if args.stats:
        s = get_stats()
        print(f"Backtest Cache: {s['total']} stocks | Fresh today: {s['fresh_today']} | "
              f"Stale: {s['stale']} | MR+: {s['mr_positive']} | Mom+: {s['mom_positive']}")
    else:
        result = precompute_all(force=args.force)
        print(f"\nSummary: {result['computed']} stocks computed in {result['elapsed']}s, "
              f"{result['mr_positive']} with positive MR score, "
              f"{result['mom_positive']} with positive momentum score")
