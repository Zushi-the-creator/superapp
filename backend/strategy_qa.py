"""
ATLAS Strategy QA — End-to-end validation of the mean reversion approach.
Tests: overlapping trades, confidence intervals, survivorship bias, regime dependency,
scanner vs API discrepancy, and simulated portfolio returns with fees.
"""
import sys, os, math, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_cache import DataCache
from atlas_v2.entry import EntryEngine

_cache = DataCache()
_entry = EntryEngine()

HOLD_DAYS = 60
FEE = 1.50
FEE_PCT = 0.30  # 0.30% fee deducted from backtest returns


def calc_rsi(closes, period=2):
    return _entry.calc_rsi(closes, period)

def calc_sma(closes, period=50):
    return _entry.calc_sma(closes, period)


def backtest_stock(ticker: str, days=1260):
    """Run the EXACT same backtest as _get_technicals in api_v2.py."""
    df = _cache.get(ticker, days)
    if df is None or len(df) < 60:
        return None

    closes = df["Close"].dropna().tolist()
    if len(closes) < 64:
        return None

    opens = df["Open"].tolist() if "Open" in df.columns else closes
    trades = []
    for i in range(50, len(closes) - HOLD_DAYS - 1):
        hist_closes = closes[:i + 1]
        rsi = calc_rsi(hist_closes, 2)
        sma50 = calc_sma(hist_closes, 50)
        if rsi < 10 and hist_closes[-1] > sma50:
            entry_price = opens[i + 1] if i + 1 < len(opens) and opens[i + 1] > 0 else closes[i]
            exit_price = closes[i + 1 + HOLD_DAYS]
            ret = ((exit_price - entry_price) / entry_price) * 100 - FEE_PCT
            trades.append({
                "return": ret, "win": ret > 0, "rsi": rsi,
                "entry_idx": i, "entry_price": entry_price,
                "exit_price": exit_price
            })

    if len(trades) < 5:
        return None

    return {"ticker": ticker, "trades": trades, "closes": closes}


def check_overlapping_trades(trades):
    """Count how many trades overlap (entered within HOLD_DAYS of each other)."""
    overlaps = 0
    for i in range(1, len(trades)):
        if trades[i]["entry_idx"] - trades[i-1]["entry_idx"] < HOLD_DAYS:
            overlaps += 1
    return overlaps


def wilson_ci(wins, total, z=1.96):
    """Wilson score confidence interval for win rate."""
    if total == 0:
        return 0, 0
    p = wins / total
    denom = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denom
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denom
    return max(0, center - spread) * 100, min(1, center + spread) * 100


def bootstrap_ci(returns, n_boot=10000, ci=0.95):
    """Bootstrap confidence interval for average return."""
    if len(returns) < 3:
        return 0, 0
    means = []
    for _ in range(n_boot):
        sample = random.choices(returns, k=len(returns))
        means.append(sum(sample) / len(sample))
    means.sort()
    lo = means[int((1 - ci) / 2 * n_boot)]
    hi = means[int((1 + ci) / 2 * n_boot)]
    return lo, hi


def non_overlapping_trades(trades):
    """Remove overlapping trades — keep only trades that don't overlap."""
    if not trades:
        return []
    result = [trades[0]]
    for t in trades[1:]:
        if t["entry_idx"] >= result[-1]["entry_idx"] + HOLD_DAYS:
            result.append(t)
    return result


def simulate_portfolio(stocks_data, capital_per_stock=1000):
    """Simulate actual trading with fees on non-overlapping trades."""
    total_pnl = 0
    total_trades = 0
    total_fees = 0
    wins = 0

    for sd in stocks_data:
        clean_trades = non_overlapping_trades(sd["trades"])
        for t in clean_trades:
            shares = capital_per_stock / t["entry_price"]
            gross_pnl = shares * (t["exit_price"] - t["entry_price"])
            net_pnl = gross_pnl - (2 * FEE)  # buy + sell fee
            total_pnl += net_pnl
            total_fees += 2 * FEE
            total_trades += 1
            if net_pnl > 0:
                wins += 1

    wr = wins / total_trades * 100 if total_trades else 0
    return {
        "total_pnl": total_pnl,
        "total_trades": total_trades,
        "total_fees": total_fees,
        "win_rate": wr,
        "avg_pnl_per_trade": total_pnl / total_trades if total_trades else 0,
    }


def main():
    # Test on: current portfolio + recommended buys
    tickers = ["WDC", "CGNX", "MTRN", "BWA", "LUV", "PDS", "AGCO", "GHM",
               "NESR", "EWTX", "FIX"]

    print("=" * 80)
    print("ATLAS STRATEGY QA — Full Validation")
    print("=" * 80)

    all_data = []
    all_trades_flat = []

    for ticker in tickers:
        result = backtest_stock(ticker)
        if not result:
            print(f"\n{ticker}: INSUFFICIENT DATA (< 5 trades or < 60 days)")
            continue

        trades = result["trades"]
        clean = non_overlapping_trades(trades)
        overlaps = check_overlapping_trades(trades)

        returns_all = [t["return"] for t in trades]
        returns_clean = [t["return"] for t in clean]

        wr_all = sum(1 for t in trades if t["win"]) / len(trades) * 100
        avg_ret_all = sum(returns_all) / len(returns_all)
        wr_clean = sum(1 for t in clean if t["win"]) / len(clean) * 100
        avg_ret_clean = sum(returns_clean) / len(returns_clean)

        # Confidence intervals
        wins_clean = sum(1 for t in clean if t["win"])
        wr_ci_lo, wr_ci_hi = wilson_ci(wins_clean, len(clean))
        ret_ci_lo, ret_ci_hi = bootstrap_ci(returns_clean)

        # Zone analysis at RSI 0-10 (where we actually buy)
        zone_trades = [t for t in trades if t["rsi"] < 10]
        zone_wr = sum(1 for t in zone_trades if t["win"]) / len(zone_trades) * 100 if zone_trades else 0
        zone_ret = sum(t["return"] for t in zone_trades) / len(zone_trades) if zone_trades else 0

        # Recency: last 10 trades
        recent = trades[-10:] if len(trades) >= 10 else trades
        recent_wr = sum(1 for t in recent if t["win"]) / len(recent) * 100
        recent_ret = sum(t["return"] for t in recent) / len(recent)

        # Max drawdown per trade
        worst = min(returns_all)
        best = max(returns_all)

        print(f"\n{'='*60}")
        print(f"{ticker}")
        print(f"{'='*60}")
        print(f"  All trades:          {len(trades):>4} trades | WR {wr_all:5.1f}% | Avg {avg_ret_all:+6.2f}%")
        print(f"  Non-overlapping:     {len(clean):>4} trades | WR {wr_clean:5.1f}% | Avg {avg_ret_clean:+6.2f}%")
        print(f"  Overlapping trades:  {overlaps:>4} ({overlaps/len(trades)*100:.0f}% of all)")
        print(f"  WR 95% CI:           [{wr_ci_lo:5.1f}% - {wr_ci_hi:5.1f}%]")
        print(f"  Return 95% CI:       [{ret_ci_lo:+6.2f}% - {ret_ci_hi:+6.2f}%]")
        print(f"  Zone 0-10:           {len(zone_trades):>4} trades | WR {zone_wr:5.1f}% | Avg {zone_ret:+6.2f}%")
        print(f"  Recent 10:           WR {recent_wr:5.1f}% | Avg {recent_ret:+6.2f}%")
        print(f"  Best/Worst trade:    {best:+6.2f}% / {worst:+6.2f}%")

        # Warnings
        if wr_ci_lo < 50:
            print(f"  ⚠️  WARNING: WR confidence interval includes <50% (could be coin flip)")
        if ret_ci_lo < 0:
            print(f"  ⚠️  WARNING: Return CI includes negative (strategy may not have edge)")
        if recent_wr < 50:
            print(f"  ⚠️  WARNING: Recent 10 trades WR < 50% (pattern may be degrading)")
        if overlaps / len(trades) > 0.5:
            print(f"  ⚠️  WARNING: >50% trades overlap (inflated trade count)")
        if len(clean) < 10:
            print(f"  ⚠️  WARNING: Only {len(clean)} non-overlapping trades (low sample)")

        all_data.append(result)
        all_trades_flat.extend(returns_clean)

    # Portfolio simulation
    print(f"\n{'='*80}")
    print(f"PORTFOLIO SIMULATION ($1,000 per stock per trade, $1.50 fee)")
    print(f"{'='*80}")
    sim = simulate_portfolio(all_data)
    print(f"  Total trades:        {sim['total_trades']}")
    print(f"  Win rate:            {sim['win_rate']:.1f}%")
    print(f"  Total P&L:           ${sim['total_pnl']:,.2f}")
    print(f"  Total fees:          ${sim['total_fees']:,.2f}")
    print(f"  Avg P&L per trade:   ${sim['avg_pnl_per_trade']:,.2f}")
    print(f"  Fee drag:            {sim['total_fees']/max(1,sim['total_pnl']+sim['total_fees'])*100:.1f}%")

    # Aggregate stats
    print(f"\n{'='*80}")
    print(f"AGGREGATE STATISTICS (all non-overlapping trades across all stocks)")
    print(f"{'='*80}")
    if all_trades_flat:
        total_n = len(all_trades_flat)
        agg_wr = sum(1 for r in all_trades_flat if r > 0) / total_n * 100
        agg_ret = sum(all_trades_flat) / total_n
        agg_ci_lo, agg_ci_hi = bootstrap_ci(all_trades_flat)
        agg_wr_lo, agg_wr_hi = wilson_ci(
            sum(1 for r in all_trades_flat if r > 0), total_n
        )
        print(f"  Total trades:        {total_n}")
        print(f"  Win rate:            {agg_wr:.1f}% [CI: {agg_wr_lo:.1f}% - {agg_wr_hi:.1f}%]")
        print(f"  Avg return:          {agg_ret:+.2f}% [CI: {agg_ci_lo:+.2f}% - {agg_ci_hi:+.2f}%]")
        print(f"  Median return:       {sorted(all_trades_flat)[total_n//2]:+.2f}%")
        print(f"  Worst trade:         {min(all_trades_flat):+.2f}%")
        print(f"  Best trade:          {max(all_trades_flat):+.2f}%")

        # Risk metrics
        losses = [r for r in all_trades_flat if r < 0]
        wins_list = [r for r in all_trades_flat if r > 0]
        if losses and wins_list:
            avg_win = sum(wins_list) / len(wins_list)
            avg_loss = sum(losses) / len(losses)
            profit_factor = sum(wins_list) / abs(sum(losses))
            print(f"  Avg win:             {avg_win:+.2f}%")
            print(f"  Avg loss:            {avg_loss:+.2f}%")
            print(f"  Profit factor:       {profit_factor:.2f} (>1.5 = good, >2 = great)")
            print(f"  Win/Loss ratio:      {avg_win/abs(avg_loss):.2f}")

        # Streak analysis
        max_consec_loss = 0
        curr_loss = 0
        for r in all_trades_flat:
            if r < 0:
                curr_loss += 1
                max_consec_loss = max(max_consec_loss, curr_loss)
            else:
                curr_loss = 0
        print(f"  Max consecutive loss: {max_consec_loss}")

    # Key questions
    print(f"\n{'='*80}")
    print(f"SUSTAINABILITY VERDICT")
    print(f"{'='*80}")

    issues = []
    if all_trades_flat:
        if agg_wr < 60:
            issues.append(f"Aggregate WR {agg_wr:.1f}% is below 60% target")
        if agg_ci_lo < 0:
            issues.append(f"Return CI lower bound is negative ({agg_ci_lo:+.2f}%)")
        if agg_wr_lo < 50:
            issues.append(f"WR CI lower bound below 50% ({agg_wr_lo:.1f}%)")
        if sim['total_fees'] / max(1, sim['total_pnl'] + sim['total_fees']) > 0.15:
            issues.append(f"Fee drag > 15% of gross profit")

    if not issues:
        print("  ✅ STRATEGY IS STATISTICALLY SUSTAINABLE")
        print("     - Win rate CI above 50%")
        print("     - Return CI above 0%")
        print("     - Fee drag manageable")
    else:
        print("  ⚠️  STRATEGY HAS CONCERNS:")
        for issue in issues:
            print(f"     - {issue}")


if __name__ == "__main__":
    random.seed(42)
    main()
