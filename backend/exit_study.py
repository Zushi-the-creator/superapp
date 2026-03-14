#!/usr/bin/env python3
"""
EXIT STRATEGY MEGA-STUDY
========================
Backtests ALL exit strategies on 3,000+ stocks with RSI(2)<10 mean reversion entries.
Answers: Is per-stock walk-forward exit selection better than simple Fixed21d?

Tests:
1. Fixed exits: 3d, 7d, 14d, 21d, 30d
2. Trailing stops: Trail5%, Trail8%
3. RSI exits: RSI>50, RSI>65, RSI>80, RSI>90
4. SMA exits: price < SMA5, price < SMA10
5. Stop+Target: -8% stop / +10% target
6. Walk-forward per-stock selection (current approach)

Entry: RSI(2) < 10 + Price > SMA(50) + next-day open
Fee: 0.30% per trade
"""

import sys, os, time, statistics, json
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_cache import DataCache

cache = DataCache()
FEE_PCT = 0.30

# ── RSI / SMA helpers ──

def calc_rsi(closes, period=2):
    if len(closes) < period + 1:
        return 50
    deltas = [closes[i] - closes[i-1] for i in range(len(closes)-period, len(closes))]
    gains = sum(d for d in deltas if d > 0) / period
    losses = -sum(d for d in deltas if d < 0) / period
    if losses == 0:
        return 100
    return 100 - 100 / (1 + gains / losses)

def calc_sma(closes, period):
    if len(closes) < period:
        return 0
    return sum(closes[-period:]) / period


# ── Exit strategies ──

def apply_exit(strat_name, closes, opens, entry_idx, rsi2_full, sma50_full):
    """Apply exit strategy starting from entry_idx (signal day). Entry at next-day open.
    Returns (exit_day_idx, return_pct) or None if can't complete."""
    entry_day = entry_idx + 1  # next-day open entry
    if entry_day >= len(opens):
        return None
    entry_px = opens[entry_day] if opens[entry_day] > 0 else closes[entry_idx]
    if entry_px <= 0:
        return None

    max_hold = min(60, len(closes) - entry_day - 1)  # safety cap
    if max_hold < 3:
        return None

    # Fixed exits
    if strat_name.startswith("Fixed"):
        days = int(strat_name.replace("Fixed", "").replace("d", ""))
        if entry_day + days >= len(closes):
            return None
        exit_px = closes[entry_day + days]
        ret = ((exit_px - entry_px) / entry_px) * 100 - FEE_PCT
        return (entry_day + days, ret, days)

    # Trailing stop
    if strat_name.startswith("Trail"):
        pct = int(strat_name.replace("Trail", "")) / 100
        peak = entry_px
        for d in range(1, max_hold + 1):
            px = closes[entry_day + d]
            peak = max(peak, px)
            if px <= peak * (1 - pct):
                ret = ((px - entry_px) / entry_px) * 100 - FEE_PCT
                return (entry_day + d, ret, d)
        # Didn't trigger — exit at max_hold
        exit_px = closes[entry_day + max_hold]
        ret = ((exit_px - entry_px) / entry_px) * 100 - FEE_PCT
        return (entry_day + max_hold, ret, max_hold)

    # RSI threshold exits
    if strat_name.startswith("RSI"):
        threshold = int(strat_name.replace("RSI", ""))
        for d in range(1, max_hold + 1):
            idx = entry_day + d
            if idx < len(rsi2_full) and rsi2_full[idx] > threshold:
                exit_px = closes[idx]
                ret = ((exit_px - entry_px) / entry_px) * 100 - FEE_PCT
                return (idx, ret, d)
        # Didn't trigger
        exit_px = closes[entry_day + max_hold]
        ret = ((exit_px - entry_px) / entry_px) * 100 - FEE_PCT
        return (entry_day + max_hold, ret, max_hold)

    # SMA exits (exit when price drops below SMA)
    if strat_name.startswith("SMA"):
        period = int(strat_name.replace("SMA", ""))
        for d in range(1, max_hold + 1):
            idx = entry_day + d
            if idx < len(closes):
                sma = sum(closes[max(0,idx-period+1):idx+1]) / min(period, idx+1)
                if closes[idx] < sma and d >= 2:  # min 2 days hold
                    exit_px = closes[idx]
                    ret = ((exit_px - entry_px) / entry_px) * 100 - FEE_PCT
                    return (idx, ret, d)
        exit_px = closes[entry_day + max_hold]
        ret = ((exit_px - entry_px) / entry_px) * 100 - FEE_PCT
        return (entry_day + max_hold, ret, max_hold)

    # Stop + Target
    if strat_name == "Stop8T10":
        stop = -8.0
        target = 10.0
        for d in range(1, max_hold + 1):
            px = closes[entry_day + d]
            pnl = ((px - entry_px) / entry_px) * 100
            if pnl <= stop or pnl >= target:
                ret = pnl - FEE_PCT
                return (entry_day + d, ret, d)
        exit_px = closes[entry_day + max_hold]
        ret = ((exit_px - entry_px) / entry_px) * 100 - FEE_PCT
        return (entry_day + max_hold, ret, max_hold)

    return None


STRATEGIES = [
    "Fixed3d", "Fixed7d", "Fixed14d", "Fixed21d", "Fixed30d",
    "Trail5", "Trail8",
    "RSI50", "RSI65", "RSI80", "RSI90",
    "SMA5", "SMA10",
    "Stop8T10",
]


def backtest_stock(ticker, df):
    """Backtest all exit strategies on one stock. Returns dict of strategy -> trades list."""
    df = df.dropna(subset=["Close"])
    if len(df) < 100:
        return None

    closes = df["Close"].tolist()
    opens = df["Open"].tolist() if "Open" in df.columns else closes

    # Pre-compute RSI(2) for full array
    rsi2_full = [50.0] * len(closes)
    for i in range(2, len(closes)):
        deltas = [closes[j] - closes[j-1] for j in range(max(0, i-1), i+1)]
        gains = sum(d for d in deltas if d > 0) / 2
        losses = -sum(d for d in deltas if d < 0) / 2
        rsi2_full[i] = 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)

    sma50_full = [0.0] * len(closes)
    for i in range(49, len(closes)):
        sma50_full[i] = sum(closes[i-49:i+1]) / 50

    # Find all entry signals: RSI(2) < 10 + above SMA50
    entries = []
    for i in range(50, len(closes) - 32):  # -32 for max exit room
        hist = closes[:i+1]
        rsi = calc_rsi(hist, 2)
        sma = calc_sma(hist, 50)
        if rsi < 10 and hist[-1] > sma and hist[-1] >= 5:  # min $5
            entries.append((i, rsi))

    if not entries:
        return None

    # For each strategy, backtest with non-overlapping trades
    results = {}
    for strat in STRATEGIES:
        trades = []
        last_exit = -1
        for (sig_idx, sig_rsi) in entries:
            if sig_idx <= last_exit:
                continue  # skip overlapping
            result = apply_exit(strat, closes, opens, sig_idx, rsi2_full, sma50_full)
            if result:
                exit_idx, ret, hold_days = result
                trades.append({
                    "ret": ret, "win": ret > 0, "hold": hold_days,
                    "rsi": sig_rsi, "entry_px": opens[sig_idx+1] if sig_idx+1 < len(opens) else closes[sig_idx]
                })
                last_exit = exit_idx

        if trades:
            results[strat] = trades

    # Walk-forward per-stock selection (current approach)
    # Pick the strategy with highest OOS EV using 5-fold TimeSeriesSplit
    if results:
        best_strat = None
        best_oos_ev = -999
        n_splits = 5
        fold_size = (len(closes) - 50) // (n_splits + 1)

        if fold_size >= 20:
            for strat in STRATEGIES:
                oos_trades = []
                for fold in range(n_splits):
                    train_end = 50 + (fold + 1) * fold_size
                    test_end = min(train_end + fold_size, len(closes) - 32)
                    if test_end <= train_end:
                        break
                    # OOS entries in this fold
                    last_exit = -1
                    for (sig_idx, sig_rsi) in entries:
                        if sig_idx < train_end or sig_idx >= test_end:
                            continue
                        if sig_idx <= last_exit:
                            continue
                        result = apply_exit(strat, closes, opens, sig_idx, rsi2_full, sma50_full)
                        if result:
                            exit_idx, ret, hold_days = result
                            oos_trades.append({"ret": ret, "win": ret > 0})
                            last_exit = exit_idx

                if len(oos_trades) >= 2:
                    oos_wr = sum(1 for t in oos_trades if t["win"]) / len(oos_trades) * 100
                    oos_avg = sum(t["ret"] for t in oos_trades) / len(oos_trades)
                    oos_ev = oos_avg * oos_wr / 100
                    if oos_ev > best_oos_ev:
                        best_oos_ev = oos_ev
                        best_strat = strat

        if best_strat and best_strat in results:
            results["WalkForward"] = results[best_strat].copy()
            results["WalkForward_picked"] = best_strat
        else:
            # Fallback to Fixed21d
            if "Fixed21d" in results:
                results["WalkForward"] = results["Fixed21d"].copy()
                results["WalkForward_picked"] = "Fixed21d"

    return results


def main():
    print("=" * 80)
    print("EXIT STRATEGY MEGA-STUDY")
    print("RSI(2)<10 + Above SMA50 + Next-day open entry + 0.30% fee")
    print("=" * 80)

    tickers = cache.get_cached_tickers()
    print(f"\nTesting {len(tickers)} stocks...")

    # Our current holdings
    holdings = ["LIND", "MAMA", "HXL", "DBD", "MKSI", "LRCX", "PDS", "WDC", "MTRN"]

    # Aggregate results
    agg = defaultdict(lambda: {"trades": [], "stocks": 0})
    holdings_agg = defaultdict(lambda: {"trades": [], "stocks": 0})
    wf_picks = defaultdict(int)  # What does walk-forward pick most often?

    stocks_with_trades = 0
    t0 = time.time()

    for idx, ticker in enumerate(tickers):
        df = cache.get(ticker, 365)
        if df is None:
            continue

        results = backtest_stock(ticker, df)
        if not results:
            continue

        stocks_with_trades += 1
        is_holding = ticker in holdings

        for strat, trades in results.items():
            if strat == "WalkForward_picked":
                wf_picks[trades] += 1  # trades is actually the strategy name here
                continue
            agg[strat]["trades"].extend(trades)
            agg[strat]["stocks"] += 1
            if is_holding:
                holdings_agg[strat]["trades"].extend(trades)
                holdings_agg[strat]["stocks"] += 1

        if (idx + 1) % 500 == 0:
            elapsed = time.time() - t0
            print(f"  [{idx+1}/{len(tickers)}] {stocks_with_trades} stocks with trades | {elapsed:.0f}s")

    elapsed = time.time() - t0
    print(f"\nDone: {stocks_with_trades} stocks with RSI<10 signals in {elapsed:.0f}s")

    # ── Print results ──

    print("\n" + "=" * 80)
    print(f"RESULTS: ALL {stocks_with_trades} STOCKS ({sum(len(agg[s]['trades']) for s in STRATEGIES if s in agg)} total trades)")
    print("=" * 80)
    print(f"{'Strategy':<15} {'Trades':>7} {'Stocks':>7} {'WR%':>7} {'AvgRet':>8} {'Median':>8} {'PF':>7} {'AvgHold':>8} {'Big10%+':>8} {'Losses':>8}")
    print("-" * 100)

    strat_order = STRATEGIES + ["WalkForward"]
    for strat in strat_order:
        if strat not in agg:
            continue
        trades = agg[strat]["trades"]
        n = len(trades)
        if n == 0:
            continue
        wins = sum(1 for t in trades if t["win"])
        wr = wins / n * 100
        avg = sum(t["ret"] for t in trades) / n
        med = sorted(t["ret"] for t in trades)[n // 2]
        avg_hold = sum(t["hold"] for t in trades) / n
        gross_profit = sum(t["ret"] for t in trades if t["ret"] > 0)
        gross_loss = abs(sum(t["ret"] for t in trades if t["ret"] <= 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else 999
        big_wins = sum(1 for t in trades if t["ret"] >= 10)
        big_losses = sum(1 for t in trades if t["ret"] <= -5)
        label = f"  ★ {strat}" if strat == "WalkForward" else strat

        print(f"{label:<15} {n:>7} {agg[strat]['stocks']:>7} {wr:>6.1f}% {avg:>7.2f}% {med:>7.2f}% {pf:>6.2f} {avg_hold:>7.1f}d {big_wins:>7} {big_losses:>7}")

    # ── Holdings breakdown ──

    print("\n" + "=" * 80)
    print(f"RESULTS: OUR 9 HOLDINGS ONLY")
    print("=" * 80)
    print(f"{'Strategy':<15} {'Trades':>7} {'Stocks':>7} {'WR%':>7} {'AvgRet':>8} {'PF':>7} {'AvgHold':>8}")
    print("-" * 70)

    for strat in strat_order:
        if strat not in holdings_agg:
            continue
        trades = holdings_agg[strat]["trades"]
        n = len(trades)
        if n == 0:
            continue
        wins = sum(1 for t in trades if t["win"])
        wr = wins / n * 100
        avg = sum(t["ret"] for t in trades) / n
        avg_hold = sum(t["hold"] for t in trades) / n
        gross_profit = sum(t["ret"] for t in trades if t["ret"] > 0)
        gross_loss = abs(sum(t["ret"] for t in trades if t["ret"] <= 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else 999

        print(f"{strat:<15} {n:>7} {holdings_agg[strat]['stocks']:>7} {wr:>6.1f}% {avg:>7.2f}% {pf:>6.2f} {avg_hold:>7.1f}d")

    # ── Walk-forward pick distribution ──

    print("\n" + "=" * 80)
    print("WALK-FORWARD STRATEGY SELECTION DISTRIBUTION")
    print("(What does per-stock selection pick most often?)")
    print("=" * 80)
    for strat, count in sorted(wf_picks.items(), key=lambda x: -x[1]):
        pct = count / sum(wf_picks.values()) * 100
        print(f"  {strat:<15} {count:>5} stocks ({pct:.1f}%)")

    # ── Capital efficiency (annualized) ──

    print("\n" + "=" * 80)
    print("CAPITAL EFFICIENCY (Annualized Return)")
    print("(Shorter holds = more trades/year = potentially higher annualized return)")
    print("=" * 80)
    print(f"{'Strategy':<15} {'AvgRet':>8} {'AvgHold':>8} {'Turns/Yr':>9} {'Annual%':>9} {'Risk-Adj':>9}")
    print("-" * 70)

    for strat in strat_order:
        if strat not in agg:
            continue
        trades = agg[strat]["trades"]
        n = len(trades)
        if n == 0:
            continue
        avg = sum(t["ret"] for t in trades) / n
        avg_hold = sum(t["hold"] for t in trades) / n
        if avg_hold <= 0:
            continue
        turns_yr = 252 / avg_hold
        annual = avg * turns_yr
        # Risk-adjusted: annual × WR/100
        wr = sum(1 for t in trades if t["win"]) / n * 100
        risk_adj = annual * wr / 100

        print(f"{strat:<15} {avg:>7.2f}% {avg_hold:>7.1f}d {turns_yr:>8.1f} {annual:>8.1f}% {risk_adj:>8.1f}%")

    # ── Statistical comparison: Fixed21d vs WalkForward ──

    if "Fixed21d" in agg and "WalkForward" in agg:
        print("\n" + "=" * 80)
        print("HEAD-TO-HEAD: Fixed21d vs WalkForward (per-stock selection)")
        print("=" * 80)

        f21 = agg["Fixed21d"]["trades"]
        wf = agg["WalkForward"]["trades"]

        f21_avg = sum(t["ret"] for t in f21) / len(f21)
        wf_avg = sum(t["ret"] for t in wf) / len(wf)
        f21_wr = sum(1 for t in f21 if t["win"]) / len(f21) * 100
        wf_wr = sum(1 for t in wf if t["win"]) / len(wf) * 100
        f21_med = sorted(t["ret"] for t in f21)[len(f21)//2]
        wf_med = sorted(t["ret"] for t in wf)[len(wf)//2]

        # Percentile analysis
        f21_rets = sorted(t["ret"] for t in f21)
        wf_rets = sorted(t["ret"] for t in wf)

        print(f"  {'Metric':<20} {'Fixed21d':>12} {'WalkForward':>12} {'Diff':>10}")
        print(f"  {'-'*54}")
        print(f"  {'Trades':<20} {len(f21):>12} {len(wf):>12}")
        print(f"  {'Win Rate':<20} {f21_wr:>11.1f}% {wf_wr:>11.1f}% {wf_wr-f21_wr:>+9.1f}%")
        print(f"  {'Avg Return':<20} {f21_avg:>11.2f}% {wf_avg:>11.2f}% {wf_avg-f21_avg:>+9.2f}%")
        print(f"  {'Median Return':<20} {f21_med:>11.2f}% {wf_med:>11.2f}% {wf_med-f21_med:>+9.2f}%")
        print(f"  {'10th pctile':<20} {f21_rets[len(f21_rets)//10]:>11.2f}% {wf_rets[len(wf_rets)//10]:>11.2f}%")
        print(f"  {'90th pctile':<20} {f21_rets[9*len(f21_rets)//10]:>11.2f}% {wf_rets[9*len(wf_rets)//10]:>11.2f}%")

    # ── Conclusion ──

    print("\n" + "=" * 80)
    print("CONCLUSION")
    print("=" * 80)

    # Find best by avg return
    best_ret = max(STRATEGIES, key=lambda s: sum(t["ret"] for t in agg[s]["trades"])/len(agg[s]["trades"]) if s in agg and agg[s]["trades"] else -999)
    best_ret_val = sum(t["ret"] for t in agg[best_ret]["trades"])/len(agg[best_ret]["trades"])

    # Find best by PF
    def pf(s):
        if s not in agg or not agg[s]["trades"]:
            return 0
        gp = sum(t["ret"] for t in agg[s]["trades"] if t["ret"] > 0)
        gl = abs(sum(t["ret"] for t in agg[s]["trades"] if t["ret"] <= 0))
        return gp / gl if gl > 0 else 999
    best_pf = max(STRATEGIES, key=pf)

    # Find best by annualized
    def annual(s):
        if s not in agg or not agg[s]["trades"]:
            return 0
        trades = agg[s]["trades"]
        avg = sum(t["ret"] for t in trades) / len(trades)
        avg_hold = sum(t["hold"] for t in trades) / len(trades)
        return avg * (252 / avg_hold) if avg_hold > 0 else 0
    best_annual = max(STRATEGIES, key=annual)

    wf_ret = sum(t["ret"] for t in agg["WalkForward"]["trades"])/len(agg["WalkForward"]["trades"]) if "WalkForward" in agg else 0
    f21_ret = sum(t["ret"] for t in agg["Fixed21d"]["trades"])/len(agg["Fixed21d"]["trades"]) if "Fixed21d" in agg else 0

    print(f"  Best avg return: {best_ret} ({best_ret_val:+.2f}%)")
    print(f"  Best profit factor: {best_pf} (PF {pf(best_pf):.2f})")
    print(f"  Best annualized: {best_annual} ({annual(best_annual):+.1f}%/yr)")
    print(f"  Fixed21d: {f21_ret:+.2f}% avg")
    print(f"  WalkForward: {wf_ret:+.2f}% avg")
    print(f"  Difference: {wf_ret - f21_ret:+.2f}% ({'WF wins' if wf_ret > f21_ret else 'Fixed21d wins'})")


if __name__ == "__main__":
    main()
