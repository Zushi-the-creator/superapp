#!/usr/bin/env python3
"""
Backtest: Does Daily Position Health Monitoring Improve Returns?
================================================================
Tests whether cutting positions mid-trade when their CURRENT RSI
shows weak forward returns beats holding to exit blindly.

Strategy A (HOLD): Enter RSI(2)<10 + above SMA50. Hold to Fixed14d. No monitoring.
Strategy B (MONITOR): Same entry. Every day check forward WR at current RSI.
         If forward WR < 55% or expected remaining < 2%, cut early. Cash waits for next signal.
Strategy C (MONITOR+ROTATE): Same as B but freed cash immediately deploys into best available signal.

All use top 200 stocks by volume, 2024-2026 data.
"""

import sqlite3
import numpy as np
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')


def compute_rsi(closes, period=2):
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    if len(gains) < period:
        return np.full(len(closes), 50.0)
    avg_gain = np.zeros(len(deltas))
    avg_loss = np.zeros(len(deltas))
    avg_gain[period - 1] = np.mean(gains[:period])
    avg_loss[period - 1] = np.mean(losses[:period])
    for i in range(period, len(deltas)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i]) / period
    rs = np.where(avg_loss > 0, avg_gain / avg_loss, 100)
    rsi = 100 - (100 / (1 + rs))
    result = np.full(len(closes), 50.0)
    result[1:] = rsi
    return result


def compute_sma(closes, period):
    sma = np.full(len(closes), np.nan)
    for i in range(period - 1, len(closes)):
        sma[i] = np.mean(closes[i - period + 1: i + 1])
    return sma


def load_data():
    conn = sqlite3.connect('data/stock_cache.db')
    tickers = conn.execute('''
        SELECT ticker, COUNT(*) as cnt, AVG(volume) as avg_vol
        FROM daily_prices WHERE date >= "2024-01-01"
        GROUP BY ticker
        HAVING cnt >= 200 AND avg_vol > 500000
        ORDER BY avg_vol DESC LIMIT 200
    ''').fetchall()

    print(f"Loading {len(tickers)} stocks...")
    all_data = {}

    for ticker, cnt, avg_vol in tickers:
        rows = conn.execute(
            'SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker = ? AND date >= "2024-01-01" ORDER BY date',
            (ticker,)
        ).fetchall()
        if len(rows) < 100:
            continue

        dates = [r[0] for r in rows]
        closes = np.array([r[4] for r in rows], dtype=float)
        rsi2 = compute_rsi(closes, 2)
        sma50 = compute_sma(closes, 50)

        all_data[ticker] = {
            'dates': dates,
            'closes': closes,
            'rsi2': rsi2,
            'sma50': sma50,
        }

    conn.close()
    print(f"Loaded {len(all_data)} stocks")
    return all_data


def forward_return_at_rsi(closes, rsi2, sma50, current_rsi, days_forward, lookback_idx):
    """
    What's the historical forward return when RSI is near current_rsi?
    Only uses data BEFORE lookback_idx (no lookahead).
    Returns (avg_return, win_rate, sample_count).
    """
    rsi_lo = max(0, current_rsi - 10)
    rsi_hi = min(100, current_rsi + 10)

    returns = []
    for j in range(51, min(lookback_idx, len(closes) - days_forward)):
        if rsi_lo <= rsi2[j] <= rsi_hi:
            fwd = (closes[j + days_forward] - closes[j]) / closes[j] * 100
            returns.append(fwd)

    if len(returns) < 5:
        return 0, 50, len(returns)  # not enough data, return neutral

    avg = np.mean(returns)
    wr = sum(1 for r in returns if r > 0) / len(returns) * 100
    return avg, wr, len(returns)


def get_entry_zone_return(closes, rsi2, sma50, hold_days, lookback_idx):
    """Zone return for RSI 0-10 entries using data before lookback_idx."""
    trades = []
    i = 51
    while i < lookback_idx - hold_days - 1:
        if rsi2[i] < 10 and closes[i] > sma50[i] and not np.isnan(sma50[i]):
            entry_idx = i + 1
            exit_idx = entry_idx + hold_days
            if exit_idx >= lookback_idx:
                break
            ret = (closes[exit_idx] - closes[entry_idx]) / closes[entry_idx] * 100
            trades.append(ret)
            i = exit_idx + 1
        else:
            i += 1

    if len(trades) < 5:
        return 0, 0, len(trades)
    return np.mean(trades), sum(1 for t in trades if t > 0) / len(trades) * 100, len(trades)


def run_backtest(all_data, strategy="HOLD", hold_days=14, max_positions=5,
                 fee_pct=0.15, min_wr=55, min_remaining_ret=2.0):
    """
    Run backtest with specified strategy.
    strategy: "HOLD" | "MONITOR" | "MONITOR_ROTATE"
    """
    # Build unified timeline
    all_dates = set()
    for d in all_data.values():
        all_dates.update(d['dates'])
    all_dates = sorted(all_dates)

    portfolio = []  # {ticker, entry_price, entry_date, capital, days_held, entry_zone_ret}
    trades = []
    capital = 10000
    cash = capital
    daily_equity = []  # for drawdown calc

    for day_idx, date in enumerate(all_dates):
        # -- EXITS (timer-based) --
        new_portfolio = []
        for pos in portfolio:
            ticker = pos['ticker']
            d = all_data[ticker]
            if date not in d['dates']:
                new_portfolio.append(pos)
                continue

            t_idx = d['dates'].index(date)
            pos['days_held'] += 1

            if pos['days_held'] >= hold_days:
                exit_price = d['closes'][t_idx]
                ret = (exit_price - pos['entry_price']) / pos['entry_price'] * 100
                net_ret = ret - fee_pct * 2
                proceeds = pos['capital'] * (1 + net_ret / 100)
                cash += proceeds
                trades.append({
                    'ticker': ticker, 'entry_date': pos['entry_date'],
                    'exit_date': date, 'return': net_ret,
                    'capital': pos['capital'], 'pnl': proceeds - pos['capital'],
                    'type': 'EXIT', 'days_held': pos['days_held'],
                })
            else:
                new_portfolio.append(pos)

        portfolio = new_portfolio

        # -- HEALTH MONITOR (Strategy B & C) --
        if strategy in ("MONITOR", "MONITOR_ROTATE"):
            still_holding = []
            for pos in portfolio:
                ticker = pos['ticker']
                d = all_data[ticker]
                if date not in d['dates']:
                    still_holding.append(pos)
                    continue

                t_idx = d['dates'].index(date)
                current_rsi = d['rsi2'][t_idx]
                days_left = hold_days - pos['days_held']

                if days_left <= 1:
                    still_holding.append(pos)
                    continue

                # Check forward WR at current RSI for remaining days
                fwd_ret, fwd_wr, fwd_n = forward_return_at_rsi(
                    d['closes'], d['rsi2'], d['sma50'],
                    current_rsi, days_left, t_idx
                )

                # CUT if: WR below threshold AND expected return below threshold
                # Only cut if we have enough samples to be confident
                if fwd_n >= 10 and fwd_wr < min_wr and fwd_ret < min_remaining_ret:
                    exit_price = d['closes'][t_idx]
                    ret = (exit_price - pos['entry_price']) / pos['entry_price'] * 100
                    net_ret = ret - fee_pct * 2
                    proceeds = pos['capital'] * (1 + net_ret / 100)
                    cash += proceeds
                    trades.append({
                        'ticker': ticker, 'entry_date': pos['entry_date'],
                        'exit_date': date, 'return': net_ret,
                        'capital': pos['capital'], 'pnl': proceeds - pos['capital'],
                        'type': 'HEALTH_CUT',
                        'days_held': pos['days_held'],
                        'cut_reason': f"WR={fwd_wr:.0f}% ret={fwd_ret:.1f}% ({fwd_n} samples)",
                    })
                else:
                    still_holding.append(pos)

            portfolio = still_holding

        # -- NEW ENTRIES (fill empty slots) --
        if len(portfolio) < max_positions:
            signals = []
            for ticker, d in all_data.items():
                if date not in d['dates']:
                    continue
                if any(p['ticker'] == ticker for p in portfolio):
                    continue

                t_idx = d['dates'].index(date)
                if t_idx < 51 or t_idx >= len(d['closes']) - 1:
                    continue

                rsi = d['rsi2'][t_idx]
                close = d['closes'][t_idx]
                sma = d['sma50'][t_idx]

                if rsi < 10 and close > sma and not np.isnan(sma):
                    zr, zwr, zt = get_entry_zone_return(
                        d['closes'], d['rsi2'], d['sma50'], hold_days, t_idx
                    )
                    if zt >= 5 and zwr >= 55:
                        signals.append({
                            'ticker': ticker, 'zone_return': zr,
                            'zone_wr': zwr,
                            'entry_price': d['closes'][min(t_idx + 1, len(d['closes']) - 1)],
                            'date': date,
                        })

            signals.sort(key=lambda x: x['zone_return'], reverse=True)

            slots = max_positions - len(portfolio)
            for sig in signals[:slots]:
                pos_size = min(cash, capital * 0.20)
                if pos_size < 100:
                    continue
                cash -= pos_size
                portfolio.append({
                    'ticker': sig['ticker'],
                    'entry_price': sig['entry_price'],
                    'entry_date': sig['date'],
                    'capital': pos_size,
                    'days_held': 0,
                    'entry_zone_ret': sig['zone_return'],
                })

        # Track equity
        port_value = cash
        for pos in portfolio:
            ticker = pos['ticker']
            d = all_data[ticker]
            if date in d['dates']:
                t_idx = d['dates'].index(date)
                current = d['closes'][t_idx]
                port_value += pos['capital'] * (1 + (current - pos['entry_price']) / pos['entry_price'])
            else:
                port_value += pos['capital']
        daily_equity.append((date, port_value))

    return trades, daily_equity


def print_results(label, trades, daily_equity):
    if not trades:
        print(f"\n{label}: No trades")
        return

    returns = [t['return'] for t in trades]
    pnls = [t['pnl'] for t in trades]
    wins = sum(1 for r in returns if r > 0)

    health_cuts = [t for t in trades if t.get('type') == 'HEALTH_CUT']
    normal_exits = [t for t in trades if t.get('type') == 'EXIT']

    total_pnl = sum(pnls)
    avg_ret = np.mean(returns)
    med_ret = np.median(returns)
    wr = wins / len(returns) * 100
    neg_returns = [r for r in returns if r < 0]
    pf = abs(sum(r for r in returns if r > 0) / sum(neg_returns)) if neg_returns else float('inf')

    # Max drawdown from equity curve
    equities = [e[1] for e in daily_equity]
    peak = equities[0]
    max_dd = 0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd

    final_equity = equities[-1] if equities else 10000
    total_return = (final_equity - 10000) / 10000 * 100

    print(f"\n{'=' * 65}")
    print(f"  {label}")
    print(f"{'=' * 65}")
    print(f"  Total Trades: {len(trades)} | Wins: {wins} | Losses: {len(trades) - wins}")
    print(f"  Normal Exits: {len(normal_exits)} | Health Cuts: {len(health_cuts)}")
    print(f"  Win Rate: {wr:.1f}%")
    print(f"  Avg Return/Trade: {avg_ret:+.2f}% | Median: {med_ret:+.2f}%")
    print(f"  Total P&L: ${total_pnl:+,.0f}")
    print(f"  Final Equity: ${final_equity:,.0f} | Total Return: {total_return:+.1f}%")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Max Drawdown: {max_dd:.1f}%")
    print(f"  Best: {max(returns):+.1f}% | Worst: {min(returns):+.1f}%")

    if health_cuts:
        cut_returns = [t['return'] for t in health_cuts]
        print(f"\n  HEALTH CUTS ANALYSIS:")
        print(f"    Cuts made: {len(health_cuts)}")
        print(f"    Avg return at cut: {np.mean(cut_returns):+.2f}%")
        print(f"    Avg days held at cut: {np.mean([t['days_held'] for t in health_cuts]):.1f}")

        # What WOULD have happened if we held?
        print(f"    Cut reasons:")
        for t in health_cuts[:10]:
            print(f"      {t['ticker']} day {t['days_held']}: {t['return']:+.1f}% | {t.get('cut_reason', '')}")

    # Monthly breakdown
    monthly = defaultdict(lambda: {'pnl': 0, 'trades': 0, 'cuts': 0})
    for t in trades:
        month = t['exit_date'][:7]
        monthly[month]['pnl'] += t['pnl']
        monthly[month]['trades'] += 1
        if t.get('type') == 'HEALTH_CUT':
            monthly[month]['cuts'] += 1

    print(f"\n  Monthly P&L:")
    running = 0
    for m in sorted(monthly.keys()):
        d = monthly[m]
        running += d['pnl']
        cuts_str = f" ({d['cuts']} cuts)" if d['cuts'] > 0 else ""
        print(f"    {m}: ${d['pnl']:+,.0f} ({d['trades']} trades{cuts_str}) | Running: ${running:+,.0f}")


def backtest_hold_vs_cut_comparison(all_data, hold_days=14):
    """
    For every trade that MONITOR strategy cut early,
    simulate what would have happened if it was held to exit.
    """
    print(f"\n{'=' * 65}")
    print(f"  COUNTERFACTUAL: What if health-cut trades were held?")
    print(f"{'=' * 65}")

    # Run monitor strategy to get the cuts
    trades, _ = run_backtest(all_data, strategy="MONITOR", hold_days=hold_days)
    health_cuts = [t for t in trades if t.get('type') == 'HEALTH_CUT']

    if not health_cuts:
        print("  No health cuts were made")
        return

    saved = 0
    hurt = 0
    saved_pnl = 0
    hurt_pnl = 0

    for cut in health_cuts:
        ticker = cut['ticker']
        d = all_data.get(ticker)
        if not d:
            continue

        entry_date = cut['entry_date']
        if entry_date not in d['dates']:
            continue

        entry_idx = d['dates'].index(entry_date) + 1  # next-day entry
        exit_idx = entry_idx + hold_days

        if exit_idx >= len(d['closes']):
            continue

        # What would the full hold return have been?
        entry_p = d['closes'][min(entry_idx, len(d['closes']) - 1)]
        exit_p = d['closes'][min(exit_idx, len(d['closes']) - 1)]
        full_hold_ret = (exit_p - entry_p) / entry_p * 100 - 0.30  # with fees

        cut_ret = cut['return']
        diff = cut_ret - full_hold_ret  # positive = cutting was better

        if diff > 0:
            saved += 1
            saved_pnl += abs(diff) * cut['capital'] / 100
        else:
            hurt += 1
            hurt_pnl += abs(diff) * cut['capital'] / 100

        print(f"  {ticker} (day {cut['days_held']}): Cut at {cut_ret:+.1f}% | Hold would be {full_hold_ret:+.1f}% | {'SAVED' if diff > 0 else 'HURT'} ${abs(diff) * cut['capital'] / 100:.0f}")

    print(f"\n  Summary:")
    print(f"    Cuts that SAVED money: {saved} (${saved_pnl:+,.0f})")
    print(f"    Cuts that HURT: {hurt} (${hurt_pnl:+,.0f})")
    print(f"    Net impact: ${saved_pnl - hurt_pnl:+,.0f}")


def main():
    print("=" * 65)
    print("DAILY HEALTH MONITORING BACKTEST")
    print("Universe: Top 200 stocks | Period: 2024-2026")
    print("Entry: RSI(2)<10 + above SMA50 | Base exit: Fixed 14d")
    print("Monitor: Cut if forward WR < 55% AND expected < 2%")
    print("         at current RSI (10+ historical samples required)")
    print("=" * 65)

    all_data = load_data()

    # Test with 14-day hold
    print("\n\n--- FIXED 14-DAY HOLD PERIOD ---")

    print("\nRunning HOLD (no monitoring)...")
    hold_trades, hold_eq = run_backtest(all_data, strategy="HOLD", hold_days=14)
    print_results("A) HOLD TO EXIT (no monitoring)", hold_trades, hold_eq)

    print("\nRunning MONITOR (cut weak, cash waits)...")
    mon_trades, mon_eq = run_backtest(all_data, strategy="MONITOR", hold_days=14)
    print_results("B) MONITOR (cut weak → cash)", mon_trades, mon_eq)

    print("\nRunning MONITOR+ROTATE (cut weak, buy next signal)...")
    rot_trades, rot_eq = run_backtest(all_data, strategy="MONITOR_ROTATE", hold_days=14)
    print_results("C) MONITOR+ROTATE (cut weak → buy better)", rot_trades, rot_eq)

    # Test different thresholds
    print("\n\n--- SENSITIVITY: DIFFERENT CUT THRESHOLDS ---")
    for min_wr, min_ret in [(50, 1.0), (55, 2.0), (55, 3.0), (60, 3.0), (45, 1.0)]:
        trades, eq = run_backtest(all_data, strategy="MONITOR", hold_days=14,
                                   min_wr=min_wr, min_remaining_ret=min_ret)
        cuts = sum(1 for t in trades if t.get('type') == 'HEALTH_CUT')
        returns = [t['return'] for t in trades]
        total_pnl = sum(t['pnl'] for t in trades)
        wr = sum(1 for r in returns if r > 0) / len(returns) * 100 if returns else 0
        final = eq[-1][1] if eq else 10000
        print(f"  Cut WR<{min_wr}% & ret<{min_ret}%: {len(trades)} trades ({cuts} cuts) | WR={wr:.0f}% | P&L=${total_pnl:+,.0f} | Final=${final:,.0f}")

    # Counterfactual analysis
    backtest_hold_vs_cut_comparison(all_data, hold_days=14)

    # Also test 21-day hold
    print("\n\n--- FIXED 21-DAY HOLD PERIOD ---")

    hold_trades21, hold_eq21 = run_backtest(all_data, strategy="HOLD", hold_days=21)
    print_results("A) HOLD 21d (no monitoring)", hold_trades21, hold_eq21)

    mon_trades21, mon_eq21 = run_backtest(all_data, strategy="MONITOR", hold_days=21)
    print_results("B) MONITOR 21d (cut weak → cash)", mon_trades21, mon_eq21)

    rot_trades21, rot_eq21 = run_backtest(all_data, strategy="MONITOR_ROTATE", hold_days=21)
    print_results("C) MONITOR+ROTATE 21d (cut weak → buy better)", rot_trades21, rot_eq21)


if __name__ == "__main__":
    main()
