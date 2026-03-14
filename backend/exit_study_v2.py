#!/usr/bin/env python3
"""
EXIT STRATEGY V2 STUDY — Research-Backed Approaches
====================================================
Tests Connors/Alvarez-style exits vs our data-driven approaches.
Universal exit (same for all stocks) — no per-stock optimization.

Candidates:
  A. Fixed21d — our current default
  B. Fixed30d — our backtest winner
  C. RSI70 — Connors/Alvarez: exit when RSI(2) crosses above 70, max 30d
  D. RSI70_21d — Hybrid: exit RSI(2)>70 OR 21 days, whichever first
  E. RSI70_30d — Hybrid: exit RSI(2)>70 OR 30 days, whichever first
  F. SMA5 — Original Connors: exit close > SMA(5), max 30d
  G. SMA5_21d — Hybrid: exit close > SMA(5) OR 21 days, whichever first
  H. Fixed7d — Alvarez-style short hold
  I. Fixed5d — Ultra-short Connors style
  J. RSI50_10d — Alvarez: exit RSI(2)>50 OR 10 days max

Entry: RSI(2) < 10 + Price > SMA(50) + next-day open + 0.30% fee
"""

import sys, os, time
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_cache import DataCache

cache = DataCache()
FEE_PCT = 0.30

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


# ── Exit functions — each returns (hold_days, return_pct) or None ──

def exit_fixed(closes, opens, entry_idx, rsi2_full, days):
    ed = entry_idx + 1
    if ed >= len(opens) or ed + days >= len(closes):
        return None
    ep = opens[ed] if opens[ed] > 0 else closes[entry_idx]
    if ep <= 0: return None
    ret = ((closes[ed + days] - ep) / ep) * 100 - FEE_PCT
    return (days, ret)

def exit_rsi_threshold(closes, opens, entry_idx, rsi2_full, rsi_thresh, max_days):
    ed = entry_idx + 1
    if ed >= len(opens): return None
    ep = opens[ed] if opens[ed] > 0 else closes[entry_idx]
    if ep <= 0: return None
    limit = min(max_days, len(closes) - ed - 1)
    if limit < 1: return None
    for d in range(1, limit + 1):
        if ed + d < len(rsi2_full) and rsi2_full[ed + d] > rsi_thresh:
            ret = ((closes[ed + d] - ep) / ep) * 100 - FEE_PCT
            return (d, ret)
    # Max days hit — exit anyway
    ret = ((closes[ed + limit] - ep) / ep) * 100 - FEE_PCT
    return (limit, ret)

def exit_sma5(closes, opens, entry_idx, rsi2_full, max_days):
    ed = entry_idx + 1
    if ed >= len(opens): return None
    ep = opens[ed] if opens[ed] > 0 else closes[entry_idx]
    if ep <= 0: return None
    limit = min(max_days, len(closes) - ed - 1)
    if limit < 2: return None
    for d in range(2, limit + 1):  # min 2 days hold
        idx = ed + d
        if idx >= 5:
            sma5 = sum(closes[idx-4:idx+1]) / 5
            if closes[idx] > sma5:
                ret = ((closes[idx] - ep) / ep) * 100 - FEE_PCT
                return (d, ret)
    ret = ((closes[ed + limit] - ep) / ep) * 100 - FEE_PCT
    return (limit, ret)


STRATEGIES = {
    "Fixed5d":     lambda c, o, ei, r: exit_fixed(c, o, ei, r, 5),
    "Fixed7d":     lambda c, o, ei, r: exit_fixed(c, o, ei, r, 7),
    "Fixed14d":    lambda c, o, ei, r: exit_fixed(c, o, ei, r, 14),
    "Fixed21d":    lambda c, o, ei, r: exit_fixed(c, o, ei, r, 21),
    "Fixed30d":    lambda c, o, ei, r: exit_fixed(c, o, ei, r, 30),
    "RSI70_30d":   lambda c, o, ei, r: exit_rsi_threshold(c, o, ei, r, 70, 30),
    "RSI70_21d":   lambda c, o, ei, r: exit_rsi_threshold(c, o, ei, r, 70, 21),
    "RSI50_10d":   lambda c, o, ei, r: exit_rsi_threshold(c, o, ei, r, 50, 10),
    "RSI70_10d":   lambda c, o, ei, r: exit_rsi_threshold(c, o, ei, r, 70, 10),
    "SMA5_30d":    lambda c, o, ei, r: exit_sma5(c, o, ei, r, 30),
    "SMA5_21d":    lambda c, o, ei, r: exit_sma5(c, o, ei, r, 21),
}

STRAT_ORDER = [
    "Fixed5d", "Fixed7d", "Fixed14d", "Fixed21d", "Fixed30d",
    "RSI50_10d", "RSI70_10d", "RSI70_21d", "RSI70_30d",
    "SMA5_21d", "SMA5_30d",
]


def backtest_stock(ticker, df):
    df = df.dropna(subset=["Close"])
    if len(df) < 100:
        return None
    closes = df["Close"].tolist()
    opens = df["Open"].tolist() if "Open" in df.columns else closes

    # Pre-compute RSI(2)
    rsi2_full = [50.0] * len(closes)
    for i in range(2, len(closes)):
        deltas = [closes[j] - closes[j-1] for j in range(max(0,i-1), i+1)]
        gains = sum(d for d in deltas if d > 0) / 2
        losses = -sum(d for d in deltas if d < 0) / 2
        rsi2_full[i] = 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)

    # Find entries
    entries = []
    for i in range(50, len(closes) - 32):
        hist = closes[:i+1]
        rsi = calc_rsi(hist, 2)
        sma = calc_sma(hist, 50)
        if rsi < 10 and hist[-1] > sma and hist[-1] >= 5:
            entries.append(i)

    if not entries:
        return None

    results = {}
    for name, fn in STRATEGIES.items():
        trades = []
        last_exit = -1
        for sig_idx in entries:
            if sig_idx <= last_exit:
                continue
            result = fn(closes, opens, sig_idx, rsi2_full)
            if result:
                hold_days, ret = result
                trades.append({"ret": ret, "win": ret > 0, "hold": hold_days})
                last_exit = sig_idx + 1 + hold_days
        if trades:
            results[name] = trades

    return results


def print_results(title, agg, strat_order):
    print(f"\n{'='*100}")
    print(title)
    print(f"{'='*100}")
    print(f"{'Strategy':<14} {'Trades':>7} {'Stocks':>7} {'WR%':>7} {'AvgRet':>8} {'Median':>8} "
          f"{'PF':>7} {'AvgHold':>8} {'Turn/Yr':>8} {'Annual':>8} {'RiskAdj':>8} {'Big10+':>7} {'Loss5+':>7}")
    print("-" * 115)

    for strat in strat_order:
        if strat not in agg or not agg[strat]["trades"]:
            continue
        trades = agg[strat]["trades"]
        n = len(trades)
        wins = sum(1 for t in trades if t["win"])
        wr = wins / n * 100
        avg = sum(t["ret"] for t in trades) / n
        rets_sorted = sorted(t["ret"] for t in trades)
        med = rets_sorted[n // 2]
        avg_hold = sum(t["hold"] for t in trades) / n
        gp = sum(t["ret"] for t in trades if t["ret"] > 0)
        gl = abs(sum(t["ret"] for t in trades if t["ret"] <= 0))
        pf = gp / gl if gl > 0 else 999
        turns = 252 / avg_hold if avg_hold > 0 else 0
        annual = avg * turns
        risk_adj = annual * wr / 100
        big = sum(1 for t in trades if t["ret"] >= 10)
        loss = sum(1 for t in trades if t["ret"] <= -5)

        print(f"{strat:<14} {n:>7} {agg[strat]['stocks']:>7} {wr:>6.1f}% {avg:>7.2f}% {med:>7.2f}% "
              f"{pf:>6.2f} {avg_hold:>7.1f}d {turns:>7.1f} {annual:>7.1f}% {risk_adj:>7.1f}% {big:>7} {loss:>7}")


def main():
    print("=" * 100)
    print("EXIT STRATEGY V2 — Research-Backed Approaches")
    print("Entry: RSI(2)<10 + Above SMA50 + Next-day open + 0.30% fee")
    print("Universal exit (same for all stocks) — no per-stock optimization")
    print("=" * 100)

    tickers = cache.get_cached_tickers()
    holdings = {"LIND", "MAMA", "HXL", "DBD", "MKSI", "LRCX", "PDS", "WDC", "MTRN"}

    agg_all = defaultdict(lambda: {"trades": [], "stocks": 0})
    agg_hold = defaultdict(lambda: {"trades": [], "stocks": 0})

    # Also track per-stock: which strategy wins for each stock?
    per_stock_winners = defaultdict(int)
    stocks_tested = 0
    t0 = time.time()

    for idx, ticker in enumerate(tickers):
        df = cache.get(ticker, 365)
        if df is None:
            continue
        results = backtest_stock(ticker, df)
        if not results:
            continue

        stocks_tested += 1
        is_holding = ticker in holdings

        for strat, trades in results.items():
            agg_all[strat]["trades"].extend(trades)
            agg_all[strat]["stocks"] += 1
            if is_holding:
                agg_hold[strat]["trades"].extend(trades)
                agg_hold[strat]["stocks"] += 1

        # Which strategy wins for this stock?
        best_strat = max(results.keys(),
                        key=lambda s: sum(t["ret"] for t in results[s])/len(results[s]) if results[s] else -999)
        per_stock_winners[best_strat] += 1

        if (idx + 1) % 500 == 0:
            print(f"  [{idx+1}/{len(tickers)}] {stocks_tested} stocks | {time.time()-t0:.0f}s")

    elapsed = time.time() - t0
    print(f"\nDone: {stocks_tested} stocks in {elapsed:.0f}s")

    print_results(f"ALL {stocks_tested} STOCKS — Universal Strategy Comparison", agg_all, STRAT_ORDER)
    print_results(f"OUR 9 HOLDINGS ONLY", agg_hold, STRAT_ORDER)

    # Per-stock winner distribution
    print(f"\n{'='*100}")
    print("PER-STOCK: Which universal strategy has highest avg return most often?")
    print(f"{'='*100}")
    total = sum(per_stock_winners.values())
    for strat, count in sorted(per_stock_winners.items(), key=lambda x: -x[1]):
        print(f"  {strat:<14} {count:>5} stocks ({count/total*100:.1f}%)")

    # ── Risk analysis: worst trades, max drawdown ──
    print(f"\n{'='*100}")
    print("RISK ANALYSIS — Tail Risk Comparison")
    print(f"{'='*100}")
    print(f"{'Strategy':<14} {'Worst':>8} {'5th%':>8} {'25th%':>8} {'75th%':>8} {'95th%':>8} {'Best':>8} {'MaxConsLoss':>12}")
    print("-" * 90)

    for strat in STRAT_ORDER:
        if strat not in agg_all or not agg_all[strat]["trades"]:
            continue
        rets = sorted(t["ret"] for t in agg_all[strat]["trades"])
        n = len(rets)
        # Max consecutive losses
        max_cons = 0
        curr_cons = 0
        for t in agg_all[strat]["trades"]:
            if not t["win"]:
                curr_cons += 1
                max_cons = max(max_cons, curr_cons)
            else:
                curr_cons = 0

        print(f"{strat:<14} {rets[0]:>7.1f}% {rets[n//20]:>7.1f}% {rets[n//4]:>7.1f}% "
              f"{rets[3*n//4]:>7.1f}% {rets[19*n//20]:>7.1f}% {rets[-1]:>7.1f}% {max_cons:>12}")

    # ── Final recommendation ──
    print(f"\n{'='*100}")
    print("SCORING: Weighted Score = 40% AvgRet + 30% WR + 20% PF + 10% Annual")
    print(f"{'='*100}")

    scores = {}
    for strat in STRAT_ORDER:
        if strat not in agg_all or not agg_all[strat]["trades"]:
            continue
        trades = agg_all[strat]["trades"]
        n = len(trades)
        avg = sum(t["ret"] for t in trades) / n
        wr = sum(1 for t in trades if t["win"]) / n * 100
        gp = sum(t["ret"] for t in trades if t["ret"] > 0)
        gl = abs(sum(t["ret"] for t in trades if t["ret"] <= 0))
        pf = gp / gl if gl > 0 else 10
        avg_hold = sum(t["hold"] for t in trades) / n
        annual = avg * (252 / avg_hold) if avg_hold > 0 else 0

        # Normalize to 0-100 scale
        score = (avg / 5 * 40) + (wr / 65 * 30) + (min(pf, 3) / 3 * 20) + (annual / 40 * 10)
        scores[strat] = score
        print(f"  {strat:<14} Score: {score:>6.1f}  (Ret:{avg:>+6.2f}% WR:{wr:>5.1f}% PF:{pf:>5.2f} Ann:{annual:>+6.1f}%)")

    winner = max(scores, key=scores.get)
    print(f"\n  >>> WINNER: {winner} (score {scores[winner]:.1f})")

    # Also show what Connors would recommend
    connors_strat = "RSI70_10d"  # Alvarez: RSI>70 exit, 10d max
    our_strat = "Fixed21d"
    print(f"\n  Connors/Alvarez pick: {connors_strat} (score {scores.get(connors_strat, 0):.1f})")
    print(f"  Our current default: {our_strat} (score {scores.get(our_strat, 0):.1f})")
    print(f"  Data winner: {winner} (score {scores[winner]:.1f})")


if __name__ == "__main__":
    main()
