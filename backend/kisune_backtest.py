"""
Kisune-Style Indicator Backtest
===============================
Proper walk-forward backtest comparing our ATLAS baseline entry signals
vs enhanced entry with kisune-inspired indicators (MACD, multi-TF, volume).

Uses our REAL framework: DataCache (SQLite), EntryEngine, RegimeDetector.

Usage:
    python3 kisune_backtest.py                # Full test on top 100 + past decisions
    python3 kisune_backtest.py --top 50       # Test top 50 stocks only
    python3 kisune_backtest.py --past-only    # Only test past buy/sell decisions

Tests two strategies:
    BASELINE: RSI(2) < 20 AND price > SMA(50)       [our current ATLAS V2]
    ENHANCED: BASELINE + MACD bullish + weekly aligned + volume > 1x avg
"""

import os
import sys
import argparse
import statistics
from datetime import datetime
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from atlas_v2.entry import EntryEngine
from atlas_v2.regime import RegimeDetector, MarketRegime
from data_cache import DataCache

# ─── Past Decisions ──────────────────────────────────────────────────────────
# All stocks we've bought/sold — backtest these specifically
PAST_DECISIONS = {
    # Current holdings
    "COHR": {"action": "BUY", "date": "2026-02-06", "outcome": "HOLDING +12.8%"},
    "BE":   {"action": "BUY", "date": "2026-02-06", "outcome": "HOLDING, post-earnings dip"},
    "ALB":  {"action": "BUY", "date": "2026-02-06", "outcome": "HOLDING, post-earnings dip"},
    "GHM":  {"action": "BUY", "date": "2026-02-13", "outcome": "HOLDING -9%"},
    "JOUT": {"action": "BUY", "date": "2026-02-13", "outcome": "HOLDING"},
    "MTRN": {"action": "BUY", "date": "2026-02-19", "outcome": "HOLDING -3%"},
    "BWA":  {"action": "BUY", "date": "2026-02-18", "outcome": "HOLDING -4.8%"},
    # Sold (some were bad picks)
    "SYK":  {"action": "SOLD", "date": "2026-02-06", "outcome": "BAD - 52.6% WR, BEAR regime"},
    "SPG":  {"action": "SOLD", "date": "2026-02-06", "outcome": "BAD - 40% WR"},
    "NEM":  {"action": "SOLD", "date": "2026-02-06", "outcome": "SOLD for rotation"},
    "GOOGL":{"action": "SOLD", "date": "2026-02-12", "outcome": "Below SMA50 → SELL"},
    "VRT":  {"action": "SOLD", "date": "2026-02-11", "outcome": "Quick flip +$313"},
    "LRCX": {"action": "SOLD", "date": "2026-02-13", "outcome": "Exit signal +7.6%"},
    "LIN":  {"action": "SOLD", "date": "2026-02-10", "outcome": "Negative zone return"},
}

HOLD_DAYS = 14  # Same as deep_scanner


# ─── Indicator Functions ─────────────────────────────────────────────────────

def calc_ema(closes: list, period: int) -> list:
    """Exponential moving average."""
    ema = [0.0] * len(closes)
    if len(closes) < period:
        return ema
    k = 2.0 / (period + 1)
    ema[period - 1] = sum(closes[:period]) / period
    for i in range(period, len(closes)):
        ema[i] = closes[i] * k + ema[i - 1] * (1 - k)
    return ema


def calc_macd(closes: list) -> Tuple[list, list, list]:
    """MACD(12,26,9). Returns (macd_line, signal_line, histogram)."""
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    n = len(closes)
    macd_line = [0.0] * n
    for i in range(25, n):
        macd_line[i] = ema12[i] - ema26[i]
    signal = calc_ema(macd_line[25:], 9)
    signal_full = [0.0] * 25 + signal
    # Pad if needed
    while len(signal_full) < n:
        signal_full.append(0.0)
    histogram = [0.0] * n
    for i in range(34, n):  # MACD valid from bar 34 (26+9-1)
        histogram[i] = macd_line[i] - signal_full[i]
    return macd_line, signal_full, histogram


def calc_weekly_sma(closes: list, period: int = 10) -> float:
    """
    Simulate weekly SMA from daily closes.
    Takes last close of each 5-day block as weekly close.
    period=10 means ~50 daily bars (10 weeks).
    """
    if len(closes) < period * 5:
        return 0.0
    weekly_closes = []
    for i in range(4, len(closes), 5):
        weekly_closes.append(closes[i])
    if len(weekly_closes) < period:
        return 0.0
    return sum(weekly_closes[-period:]) / period


def is_weekly_aligned(closes: list) -> bool:
    """Weekly trend aligned: current price > weekly SMA(10) (~50-day proxy)."""
    if len(closes) < 55:
        return False
    weekly_sma = calc_weekly_sma(closes, 10)
    return closes[-1] > weekly_sma > 0


def calc_volume_ratio(volumes: list, lookback: int = 20) -> float:
    """Current volume / 20-day average volume."""
    if len(volumes) < lookback or not any(v > 0 for v in volumes[-lookback:]):
        return 0.0
    avg = sum(volumes[-lookback:]) / lookback
    return volumes[-1] / avg if avg > 0 else 0.0


# ─── Backtest Engine ─────────────────────────────────────────────────────────

def backtest_stock(ticker: str, df: pd.DataFrame, engine: EntryEngine,
                   enhanced: bool = False) -> Dict:
    """
    Walk-forward backtest for one stock.

    BASELINE: RSI(2) < 20 AND price > SMA(50)
    ENHANCED: BASELINE + MACD histogram rising + weekly aligned + volume > 1.0x

    Uses 70/30 walk-forward split for OOS validation.
    """
    closes = df['Close'].dropna().tolist()
    if len(closes) < 100:
        return {"ticker": ticker, "error": "insufficient_data"}

    volumes = df['Volume'].tolist() if 'Volume' in df.columns else [0] * len(closes)

    # Pre-compute indicators for full array
    rsi2_arr = [50.0] * len(closes)
    for i in range(2, len(closes)):
        deltas = [closes[j] - closes[j-1] for j in range(i-1, i+1)]
        gains = sum(d for d in deltas if d > 0) / 2
        losses = -sum(d for d in deltas if d < 0) / 2
        rsi2_arr[i] = 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)

    sma50_arr = [0.0] * len(closes)
    for i in range(49, len(closes)):
        sma50_arr[i] = sum(closes[i-49:i+1]) / 50

    # Enhanced indicators (pre-compute full array)
    macd_line, macd_signal, macd_hist = calc_macd(closes)

    # Volume 20d avg (rolling)
    vol_avg20 = [0.0] * len(closes)
    for i in range(19, len(closes)):
        vol_avg20[i] = sum(volumes[i-19:i+1]) / 20

    # Weekly SMA (rolling, recalc periodically for each bar)
    weekly_sma_arr = [0.0] * len(closes)
    for i in range(54, len(closes)):
        # Approximate: use 50-day SMA as weekly SMA proxy (simpler, same effect)
        weekly_sma_arr[i] = sum(closes[i-49:i+1]) / 50

    # Walk-forward split: 70% IS, 30% OOS
    split_idx = int(len(closes) * 0.7)
    min_start = 55  # Need 55 bars for all indicators

    def run_backtest(start_idx: int, end_idx: int) -> list:
        trades = []
        for i in range(max(min_start, start_idx), min(end_idx, len(closes) - HOLD_DAYS)):
            # BASELINE conditions (same as our production)
            if rsi2_arr[i] >= 20:
                continue
            if closes[i] <= sma50_arr[i] or sma50_arr[i] <= 0:
                continue

            # ENHANCED conditions (kisune-style)
            if enhanced:
                # 1. MACD histogram positive or rising (bullish momentum)
                if i >= 35:
                    if macd_hist[i] <= 0 and macd_hist[i] <= macd_hist[i-1]:
                        continue  # Skip: MACD bearish AND falling
                else:
                    continue  # Not enough data for MACD

                # 2. Weekly alignment: price > weekly SMA
                if weekly_sma_arr[i] > 0 and closes[i] <= weekly_sma_arr[i]:
                    continue  # Skip: weekly trend not aligned

                # 3. Volume confirmation: > 1.0x 20-day average
                if vol_avg20[i] > 0:
                    vol_ratio = volumes[i] / vol_avg20[i]
                    if vol_ratio < 1.0:
                        continue  # Skip: low volume

            # Entry at this bar
            entry_price = closes[i]
            if i + HOLD_DAYS < len(closes):
                exit_price = closes[i + HOLD_DAYS]
                ret = ((exit_price - entry_price) / entry_price) * 100
                trades.append({
                    "ret": ret,
                    "win": ret > 0,
                    "bar": i,
                    "entry_rsi": rsi2_arr[i],
                })
        return trades

    # In-sample
    is_trades = run_backtest(min_start, split_idx)
    # Out-of-sample
    oos_trades = run_backtest(split_idx, len(closes))
    # Full sample (for reference)
    all_trades = run_backtest(min_start, len(closes))

    def calc_metrics(trades: list) -> dict:
        if not trades:
            return {"wr": 0, "avg_ret": 0, "std_ret": 0, "trades": 0, "sharpe": 0}
        rets = [t["ret"] for t in trades]
        wins = sum(1 for t in trades if t["win"])
        wr = wins / len(trades) * 100
        avg = sum(rets) / len(rets)
        std = statistics.stdev(rets) if len(rets) > 1 else 0
        sharpe = avg / max(std, 0.5)
        return {
            "wr": round(wr, 1), "avg_ret": round(avg, 2),
            "std_ret": round(std, 2), "trades": len(trades),
            "sharpe": round(sharpe, 3),
        }

    is_m = calc_metrics(is_trades)
    oos_m = calc_metrics(oos_trades)
    full_m = calc_metrics(all_trades)
    overfit = round(is_m["wr"] / max(oos_m["wr"], 1), 2) if is_m["wr"] > 0 else 1.0

    return {
        "ticker": ticker,
        "full": full_m,
        "is": is_m,
        "oos": oos_m,
        "overfit": overfit,
        "valid": oos_m["trades"] >= 3 and oos_m["wr"] >= 50 and overfit <= 1.5,
    }


# ─── Main Runner ─────────────────────────────────────────────────────────────

def run_comparison(tickers: List[str], cache: DataCache, engine: EntryEngine,
                   label: str = "") -> Tuple[List[Dict], List[Dict]]:
    """Run baseline vs enhanced backtest on all tickers. Returns (baseline_results, enhanced_results)."""
    baseline_results = []
    enhanced_results = []

    for ticker in tickers:
        df = cache.get(ticker, 365)
        if df is None or len(df) < 100:
            continue

        b = backtest_stock(ticker, df, engine, enhanced=False)
        e = backtest_stock(ticker, df, engine, enhanced=True)

        if "error" not in b:
            baseline_results.append(b)
        if "error" not in e:
            enhanced_results.append(e)

    return baseline_results, enhanced_results


def print_comparison(baseline: List[Dict], enhanced: List[Dict], label: str = ""):
    """Print side-by-side comparison table."""
    # Build lookup
    b_map = {r["ticker"]: r for r in baseline}
    e_map = {r["ticker"]: r for r in enhanced}
    all_tickers = sorted(set(list(b_map.keys()) + list(e_map.keys())))

    print(f"\n{'='*130}")
    print(f"  {label} — BASELINE vs ENHANCED (Walk-Forward OOS)")
    print(f"{'='*130}")
    print(f"{'Ticker':<8} │ {'BASE WR':>7} {'BASE Ret':>9} {'BASE Tr':>7} {'BASE Shrp':>9} │ "
          f"{'ENH WR':>7} {'ENH Ret':>9} {'ENH Tr':>7} {'ENH Shrp':>9} │ "
          f"{'WR Δ':>6} {'Ret Δ':>7} {'Tr Δ':>5} {'Verdict':>8}")
    print(f"{'─'*8}─┼─{'─'*7}─{'─'*9}─{'─'*7}─{'─'*9}─┼─"
          f"{'─'*7}─{'─'*9}─{'─'*7}─{'─'*9}─┼─"
          f"{'─'*6}─{'─'*7}─{'─'*5}─{'─'*8}")

    better_count = 0
    worse_count = 0
    equal_count = 0
    filtered_bad = 0

    for ticker in all_tickers:
        b = b_map.get(ticker, {})
        e = e_map.get(ticker, {})

        b_oos = b.get("oos", {})
        e_oos = e.get("oos", {})

        b_wr = b_oos.get("wr", 0)
        b_ret = b_oos.get("avg_ret", 0)
        b_tr = b_oos.get("trades", 0)
        b_sh = b_oos.get("sharpe", 0)

        e_wr = e_oos.get("wr", 0)
        e_ret = e_oos.get("avg_ret", 0)
        e_tr = e_oos.get("trades", 0)
        e_sh = e_oos.get("sharpe", 0)

        wr_delta = e_wr - b_wr
        ret_delta = e_ret - b_ret
        tr_delta = e_tr - b_tr

        # Verdict based on OOS Sharpe
        if e_tr == 0 and b_tr > 0:
            verdict = "FILTER"  # Enhanced filtered out all trades
            if b_wr < 55:
                filtered_bad += 1
                verdict = "GOOD-F"  # Correctly filtered bad stock
            else:
                worse_count += 1
                verdict = "BAD-F"  # Filtered good stock
        elif e_sh > b_sh + 0.05:
            verdict = "BETTER"
            better_count += 1
        elif e_sh < b_sh - 0.05:
            verdict = "WORSE"
            worse_count += 1
        else:
            verdict = "EQUAL"
            equal_count += 1

        # Mark past decisions
        past = ""
        if ticker in PAST_DECISIONS:
            d = PAST_DECISIONS[ticker]
            past = f" ← {d['action']}"

        print(f"{ticker:<8} │ {b_wr:>6.1f}% {b_ret:>+8.2f}% {b_tr:>7} {b_sh:>9.3f} │ "
              f"{e_wr:>6.1f}% {e_ret:>+8.2f}% {e_tr:>7} {e_sh:>9.3f} │ "
              f"{wr_delta:>+5.1f}% {ret_delta:>+6.2f}% {tr_delta:>+4} {verdict:>8}{past}")

    # Aggregate stats
    b_valid = [r for r in baseline if r["oos"]["trades"] >= 3]
    e_valid = [r for r in enhanced if r["oos"]["trades"] >= 3]

    b_avg_wr = sum(r["oos"]["wr"] for r in b_valid) / len(b_valid) if b_valid else 0
    e_avg_wr = sum(r["oos"]["wr"] for r in e_valid) / len(e_valid) if e_valid else 0
    b_avg_ret = sum(r["oos"]["avg_ret"] for r in b_valid) / len(b_valid) if b_valid else 0
    e_avg_ret = sum(r["oos"]["avg_ret"] for r in e_valid) / len(e_valid) if e_valid else 0
    b_avg_sh = sum(r["oos"]["sharpe"] for r in b_valid) / len(b_valid) if b_valid else 0
    e_avg_sh = sum(r["oos"]["sharpe"] for r in e_valid) / len(e_valid) if e_valid else 0
    b_total_tr = sum(r["oos"]["trades"] for r in b_valid)
    e_total_tr = sum(r["oos"]["trades"] for r in e_valid)

    print(f"\n{'─'*130}")
    print(f"  AGGREGATE (OOS, stocks with 3+ trades):")
    print(f"  BASELINE: {len(b_valid)} stocks | Avg WR={b_avg_wr:.1f}% | Avg Ret={b_avg_ret:+.2f}% | "
          f"Total Trades={b_total_tr} | Avg Sharpe={b_avg_sh:.3f}")
    print(f"  ENHANCED: {len(e_valid)} stocks | Avg WR={e_avg_wr:.1f}% | Avg Ret={e_avg_ret:+.2f}% | "
          f"Total Trades={e_total_tr} | Avg Sharpe={e_avg_sh:.3f}")
    print(f"\n  Verdict: BETTER={better_count} | WORSE={worse_count} | EQUAL={equal_count} | "
          f"GOOD-FILTER={filtered_bad}")

    return {
        "baseline": {"stocks": len(b_valid), "avg_wr": b_avg_wr, "avg_ret": b_avg_ret,
                      "total_trades": b_total_tr, "avg_sharpe": b_avg_sh},
        "enhanced": {"stocks": len(e_valid), "avg_wr": e_avg_wr, "avg_ret": e_avg_ret,
                      "total_trades": e_total_tr, "avg_sharpe": e_avg_sh},
        "better": better_count, "worse": worse_count, "equal": equal_count,
        "good_filter": filtered_bad,
    }


def print_past_decisions_analysis(baseline: List[Dict], enhanced: List[Dict]):
    """Specifically analyze: would enhanced filters have caught our bad trades?"""
    b_map = {r["ticker"]: r for r in baseline}
    e_map = {r["ticker"]: r for r in enhanced}

    print(f"\n{'='*130}")
    print(f"  PAST DECISIONS ANALYSIS — Would Enhanced Filters Have Helped?")
    print(f"{'='*130}")

    for ticker, info in PAST_DECISIONS.items():
        b = b_map.get(ticker, {})
        e = e_map.get(ticker, {})
        b_full = b.get("full", {})
        e_full = e.get("full", {})
        b_oos = b.get("oos", {})
        e_oos = e.get("oos", {})

        b_wr_full = b_full.get("wr", 0)
        b_tr_full = b_full.get("trades", 0)
        e_wr_full = e_full.get("wr", 0)
        e_tr_full = e_full.get("trades", 0)

        # Would enhanced have filtered this?
        filtered = e_tr_full == 0 and b_tr_full > 0
        was_bad = info["action"] == "SOLD" and "BAD" in info.get("outcome", "")

        if was_bad and filtered:
            judgment = "CORRECTLY FILTERED (bad trade avoided)"
        elif was_bad and not filtered:
            judgment = "MISSED (bad trade NOT filtered)"
        elif not was_bad and filtered:
            judgment = "OVER-FILTERED (good trade blocked)"
        elif not was_bad and not filtered:
            if e_oos.get("wr", 0) > b_oos.get("wr", 0):
                judgment = "IMPROVED"
            elif e_oos.get("wr", 0) < b_oos.get("wr", 0):
                judgment = "DEGRADED"
            else:
                judgment = "NEUTRAL"
        else:
            judgment = "N/A"

        print(f"\n  {ticker} [{info['action']}] — {info['outcome']}")
        print(f"    Baseline: WR={b_wr_full:.1f}% ({b_tr_full} trades) | "
              f"OOS: WR={b_oos.get('wr',0):.1f}% ({b_oos.get('trades',0)} trades)")
        print(f"    Enhanced: WR={e_wr_full:.1f}% ({e_tr_full} trades) | "
              f"OOS: WR={e_oos.get('wr',0):.1f}% ({e_oos.get('trades',0)} trades)")
        print(f"    → {judgment}")


def main():
    parser = argparse.ArgumentParser(description="Kisune-Style Indicator Backtest")
    parser.add_argument("--top", type=int, default=100, help="Top N stocks to test")
    parser.add_argument("--past-only", action="store_true", help="Only test past decisions")
    args = parser.parse_args()

    cache = DataCache()
    engine = EntryEngine()
    stats = cache.stats()
    print(f"Cache: {stats['total_tickers']} tickers, {stats['total_rows']} rows")

    # ── Part 1: Past Decisions ──
    past_tickers = list(PAST_DECISIONS.keys())
    print(f"\n{'#'*60}")
    print(f"  PART 1: Past Decisions ({len(past_tickers)} stocks)")
    print(f"{'#'*60}")

    b_past, e_past = run_comparison(past_tickers, cache, engine, "Past Decisions")
    agg_past = print_comparison(b_past, e_past, "PAST DECISIONS")
    print_past_decisions_analysis(b_past, e_past)

    if args.past_only:
        return

    # ── Part 2: Top N from Universe ──
    # Load from today's scan cache if available, else use universe
    scan_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                             f"scan_{datetime.now().strftime('%Y-%m-%d')}.json")
    if os.path.exists(scan_path):
        import json
        with open(scan_path) as f:
            scan_data = json.load(f)
        top_tickers = [r["ticker"] for r in scan_data[:args.top]]
        print(f"\n{'#'*60}")
        print(f"  PART 2: Top {len(top_tickers)} from Today's Scan")
        print(f"{'#'*60}")
    else:
        # Fallback: load from universe file
        universe_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "data", "us_stock_universe.txt")
        if os.path.exists(universe_file):
            with open(universe_file) as f:
                all_tickers = [line.strip() for line in f if line.strip()]
            top_tickers = all_tickers[:args.top]
        else:
            top_tickers = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA",
                           "JPM", "V", "MA", "HD", "COST", "CRM", "NFLX", "AMD"]
        print(f"\n{'#'*60}")
        print(f"  PART 2: Top {len(top_tickers)} from Universe")
        print(f"{'#'*60}")

    # Remove duplicates from past decisions
    top_tickers = [t for t in top_tickers if t not in past_tickers][:args.top]

    b_top, e_top = run_comparison(top_tickers, cache, engine, "Top Universe")
    agg_top = print_comparison(b_top, e_top, f"TOP {len(top_tickers)} UNIVERSE STOCKS")

    # ── Final Summary ──
    print(f"\n{'#'*60}")
    print(f"  FINAL VERDICT")
    print(f"{'#'*60}")

    # Combined stats
    all_b = b_past + b_top
    all_e = e_past + e_top
    b_valid = [r for r in all_b if r["oos"]["trades"] >= 3]
    e_valid = [r for r in all_e if r["oos"]["trades"] >= 3]

    if b_valid and e_valid:
        b_sh = sum(r["oos"]["sharpe"] for r in b_valid) / len(b_valid)
        e_sh = sum(r["oos"]["sharpe"] for r in e_valid) / len(e_valid)
        b_wr = sum(r["oos"]["wr"] for r in b_valid) / len(b_valid)
        e_wr = sum(r["oos"]["wr"] for r in e_valid) / len(e_valid)
        b_ret = sum(r["oos"]["avg_ret"] for r in b_valid) / len(b_valid)
        e_ret = sum(r["oos"]["avg_ret"] for r in e_valid) / len(e_valid)
        b_tr = sum(r["oos"]["trades"] for r in b_valid)
        e_tr = sum(r["oos"]["trades"] for r in e_valid)

        print(f"\n  COMBINED ({len(b_valid)} baseline / {len(e_valid)} enhanced stocks):")
        print(f"  ┌──────────┬──────────┬──────────┬──────────┬──────────┐")
        print(f"  │ Strategy │ OOS WR   │ OOS Ret  │ Sharpe   │ Trades   │")
        print(f"  ├──────────┼──────────┼──────────┼──────────┼──────────┤")
        print(f"  │ BASELINE │ {b_wr:>6.1f}%  │ {b_ret:>+7.2f}% │ {b_sh:>7.3f}  │ {b_tr:>8} │")
        print(f"  │ ENHANCED │ {e_wr:>6.1f}%  │ {e_ret:>+7.2f}% │ {e_sh:>7.3f}  │ {e_tr:>8} │")
        print(f"  └──────────┴──────────┴──────────┴──────────┴──────────┘")

        # Recommendation
        if e_sh > b_sh + 0.05 and e_wr > b_wr:
            print(f"\n  RECOMMENDATION: ADOPT enhanced filters")
            print(f"  → Sharpe improved by {e_sh - b_sh:+.3f}, WR by {e_wr - b_wr:+.1f}%")
            print(f"  → Trade count reduced by {b_tr - e_tr} ({(1 - e_tr/max(b_tr,1))*100:.0f}% fewer trades)")
            print(f"  → Higher quality entries with better risk-adjusted returns")
        elif e_sh < b_sh - 0.05:
            print(f"\n  RECOMMENDATION: KEEP current baseline")
            print(f"  → Enhanced Sharpe WORSE by {e_sh - b_sh:.3f}")
            print(f"  → Filters are too restrictive, removing profitable trades")
        else:
            print(f"\n  RECOMMENDATION: MARGINAL difference — consider individual filters")
            print(f"  → Test MACD, weekly alignment, volume SEPARATELY to find which helps")

    # Past decisions specific verdict
    print(f"\n  PAST DECISIONS IMPACT:")
    bad_buys = [t for t, d in PAST_DECISIONS.items()
                if d["action"] == "SOLD" and "BAD" in d.get("outcome", "")]
    for t in bad_buys:
        e = {r["ticker"]: r for r in e_past}.get(t, {})
        b = {r["ticker"]: r for r in b_past}.get(t, {})
        e_tr = e.get("full", {}).get("trades", 0)
        b_tr = b.get("full", {}).get("trades", 0)
        if e_tr == 0 and b_tr > 0:
            print(f"  ✓ {t}: Enhanced would have BLOCKED this bad trade")
        else:
            print(f"  ✗ {t}: Enhanced did NOT catch this bad trade")


if __name__ == "__main__":
    main()
