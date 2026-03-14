#!/usr/bin/env python3
"""
Backtest: Hold-to-Exit vs Daily Rotation
=========================================
Tests on 200+ top stocks whether rotating mid-trade into stronger signals
beats holding positions to their backtested exit.

Strategy A (HOLD): Enter on RSI(2)<10 + above SMA50. Hold to Fixed14d exit. No mid-trade changes.
Strategy B (ROTATE): Same entry. But each day, check if a BETTER signal exists (higher zone_return).
         If yes, sell current position and buy the better one. Reset hold timer.

Both strategies:
- Max 5 positions at 20% each
- Entry: next-day open after RSI(2)<10 signal
- Fee: 0.30% per trade (round-trip $3 on $1K)
- Universe: top 200 stocks by volume from our DB
"""

import sqlite3
import numpy as np
import pandas as pd
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

def compute_rsi(closes, period=2):
    """Compute RSI for a series of closes."""
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    if len(gains) < period:
        return np.full(len(closes), 50.0)

    avg_gain = np.zeros(len(deltas))
    avg_loss = np.zeros(len(deltas))

    avg_gain[period-1] = np.mean(gains[:period])
    avg_loss[period-1] = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain[i] = (avg_gain[i-1] * (period-1) + gains[i]) / period
        avg_loss[i] = (avg_loss[i-1] * (period-1) + losses[i]) / period

    rs = np.where(avg_loss > 0, avg_gain / avg_loss, 100)
    rsi = 100 - (100 / (1 + rs))

    result = np.full(len(closes), 50.0)
    result[1:] = rsi
    return result

def compute_sma(closes, period):
    """Simple moving average."""
    if len(closes) < period:
        return np.full(len(closes), np.nan)
    sma = np.full(len(closes), np.nan)
    for i in range(period - 1, len(closes)):
        sma[i] = np.mean(closes[i - period + 1:i + 1])
    return sma

def load_data(min_bars=252):
    """Load top 200 stocks by avg volume."""
    conn = sqlite3.connect('data/stock_cache.db')

    # Get top 200 by average volume with enough data
    tickers = conn.execute('''
        SELECT ticker, COUNT(*) as cnt, AVG(volume) as avg_vol
        FROM daily_prices
        WHERE date >= "2024-01-01"
        GROUP BY ticker
        HAVING cnt >= ? AND avg_vol > 500000
        ORDER BY avg_vol DESC
        LIMIT 200
    ''', (min_bars,)).fetchall()

    print(f"Loading {len(tickers)} stocks...")

    all_data = {}
    for ticker, cnt, avg_vol in tickers:
        rows = conn.execute(
            'SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker = ? AND date >= "2024-01-01" ORDER BY date',
            (ticker,)
        ).fetchall()

        if len(rows) < 60:
            continue

        dates = [r[0] for r in rows]
        opens = np.array([r[1] for r in rows], dtype=float)
        closes = np.array([r[4] for r in rows], dtype=float)
        volumes = np.array([r[5] for r in rows], dtype=float)

        rsi2 = compute_rsi(closes, 2)
        sma50 = compute_sma(closes, 50)

        all_data[ticker] = {
            'dates': dates,
            'opens': opens,
            'closes': closes,
            'volumes': volumes,
            'rsi2': rsi2,
            'sma50': sma50,
        }

    conn.close()
    print(f"Loaded {len(all_data)} stocks with sufficient data")
    return all_data

def get_zone_return(closes, rsi2, sma50, hold_days=14):
    """Calculate zone return for RSI 0-10 entries (our strategy zone)."""
    trades = []
    i = 51  # start after SMA50 is valid
    while i < len(closes) - hold_days - 1:
        if rsi2[i] < 10 and closes[i] > sma50[i]:
            # Entry next day at open
            entry_idx = i + 1
            exit_idx = min(entry_idx + hold_days, len(closes) - 1)
            entry_price = closes[entry_idx]  # use close as proxy for open
            exit_price = closes[exit_idx]
            ret = (exit_price - entry_price) / entry_price * 100
            trades.append(ret)
            i = exit_idx + 1  # skip ahead
        else:
            i += 1

    if len(trades) < 5:
        return 0, 0, len(trades)

    avg_ret = np.mean(trades)
    wr = sum(1 for t in trades if t > 0) / len(trades) * 100
    return avg_ret, wr, len(trades)

def backtest_hold(all_data, max_positions=5, hold_days=14, fee_pct=0.15):
    """
    Strategy A: HOLD to exit.
    Enter on RSI(2)<10 + above SMA50. Hold for exactly hold_days trading days. No rotation.
    """
    # Build a unified timeline
    all_dates = set()
    for d in all_data.values():
        all_dates.update(d['dates'])
    all_dates = sorted(all_dates)

    # Build daily signal matrix
    portfolio = []  # list of {ticker, entry_idx, entry_price, entry_date}
    trades = []
    capital = 10000
    cash = capital

    for day_idx, date in enumerate(all_dates):
        # Check exits
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
                # Exit
                exit_price = d['closes'][t_idx]
                ret = (exit_price - pos['entry_price']) / pos['entry_price'] * 100
                net_ret = ret - fee_pct * 2  # entry + exit fee
                proceeds = pos['capital'] * (1 + net_ret / 100)
                cash += proceeds
                trades.append({
                    'ticker': ticker,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'return': net_ret,
                    'capital': pos['capital'],
                    'pnl': proceeds - pos['capital'],
                })
            else:
                new_portfolio.append(pos)

        portfolio = new_portfolio

        # Check for new entries (only if we have open slots)
        if len(portfolio) < max_positions:
            # Find all signals today, rank by zone return (pre-computed)
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
                    # Calculate zone return using data BEFORE this point (no lookahead)
                    zr, zwr, zt = get_zone_return(
                        d['closes'][:t_idx], d['rsi2'][:t_idx], d['sma50'][:t_idx], hold_days
                    )
                    if zt >= 5 and zwr >= 55:
                        signals.append({
                            'ticker': ticker,
                            'zone_return': zr,
                            'zone_wr': zwr,
                            'entry_price': d['closes'][min(t_idx + 1, len(d['closes'])-1)],  # next day
                            'date': date,
                        })

            # Rank by zone_return, take top
            signals.sort(key=lambda x: x['zone_return'], reverse=True)

            slots = max_positions - len(portfolio)
            for sig in signals[:slots]:
                pos_size = min(cash, capital * 0.20)  # 20% per position
                if pos_size < 100:
                    continue
                cash -= pos_size
                portfolio.append({
                    'ticker': sig['ticker'],
                    'entry_price': sig['entry_price'],
                    'entry_date': sig['date'],
                    'capital': pos_size,
                    'days_held': 0,
                    'zone_return': sig['zone_return'],
                })

    return trades

def backtest_rotate(all_data, max_positions=5, hold_days=14, fee_pct=0.15, min_improvement=3.0):
    """
    Strategy B: ROTATE mid-trade.
    Same entry as HOLD. But each day, check if a better signal exists.
    If new signal's zone_return > current position's zone_return + min_improvement, rotate.
    """
    all_dates = set()
    for d in all_data.values():
        all_dates.update(d['dates'])
    all_dates = sorted(all_dates)

    portfolio = []
    trades = []
    capital = 10000
    cash = capital

    for day_idx, date in enumerate(all_dates):
        # Check exits (same as hold)
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
                    'ticker': ticker,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'return': net_ret,
                    'capital': pos['capital'],
                    'pnl': proceeds - pos['capital'],
                    'type': 'EXIT',
                })
            else:
                new_portfolio.append(pos)

        portfolio = new_portfolio

        # ROTATION CHECK: Find all available signals
        available_signals = []
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
                zr, zwr, zt = get_zone_return(
                    d['closes'][:t_idx], d['rsi2'][:t_idx], d['sma50'][:t_idx], hold_days
                )
                if zt >= 5 and zwr >= 55:
                    available_signals.append({
                        'ticker': ticker,
                        'zone_return': zr,
                        'zone_wr': zwr,
                        'entry_price': d['closes'][min(t_idx + 1, len(d['closes'])-1)],
                        'date': date,
                    })

        available_signals.sort(key=lambda x: x['zone_return'], reverse=True)

        # Check if any current position should be rotated
        if available_signals:
            best_available = available_signals[0]['zone_return']

            # Find weakest position
            for pos in sorted(portfolio, key=lambda p: p['zone_return']):
                if best_available > pos['zone_return'] + min_improvement:
                    # ROTATE: sell this position, buy the better one
                    ticker = pos['ticker']
                    d = all_data[ticker]
                    if date in d['dates']:
                        t_idx = d['dates'].index(date)
                        exit_price = d['closes'][t_idx]
                        ret = (exit_price - pos['entry_price']) / pos['entry_price'] * 100
                        net_ret = ret - fee_pct * 2  # fee for selling
                        proceeds = pos['capital'] * (1 + net_ret / 100)

                        trades.append({
                            'ticker': ticker,
                            'entry_date': pos['entry_date'],
                            'exit_date': date,
                            'return': net_ret,
                            'capital': pos['capital'],
                            'pnl': proceeds - pos['capital'],
                            'type': 'ROTATION',
                        })

                        # Buy the better signal
                        sig = available_signals[0]
                        available_signals.pop(0)

                        portfolio.remove(pos)
                        cash += proceeds

                        pos_size = min(cash, capital * 0.20)
                        if pos_size >= 100:
                            cash -= pos_size
                            portfolio.append({
                                'ticker': sig['ticker'],
                                'entry_price': sig['entry_price'],
                                'entry_date': sig['date'],
                                'capital': pos_size,
                                'days_held': 0,
                                'zone_return': sig['zone_return'],
                            })
                        break  # only one rotation per day

        # Fill empty slots with new entries
        if len(portfolio) < max_positions:
            slots = max_positions - len(portfolio)
            for sig in available_signals[:slots]:
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
                    'zone_return': sig['zone_return'],
                })

    return trades


def main():
    print("=" * 70)
    print("ROTATION vs HOLD-TO-EXIT BACKTEST")
    print("Universe: Top 200 stocks by volume | Period: 2024-2026")
    print("Entry: RSI(2)<10 + above SMA50 | Exit: Fixed 14 trading days")
    print("Max 5 positions @ 20% each | Fee: 0.30% round-trip")
    print("=" * 70)
    print()

    all_data = load_data()

    print("\n--- Running HOLD strategy ---")
    hold_trades = backtest_hold(all_data)

    print("--- Running ROTATE strategy (3% improvement threshold) ---")
    rotate_trades_3 = backtest_rotate(all_data, min_improvement=3.0)

    print("--- Running ROTATE strategy (5% improvement threshold) ---")
    rotate_trades_5 = backtest_rotate(all_data, min_improvement=5.0)

    print("--- Running ROTATE strategy (0% threshold - any improvement) ---")
    rotate_trades_0 = backtest_rotate(all_data, min_improvement=0.0)

    for label, t_list in [
        ("HOLD (no rotation)", hold_trades),
        ("ROTATE (any improvement)", rotate_trades_0),
        ("ROTATE (3% better)", rotate_trades_3),
        ("ROTATE (5% better)", rotate_trades_5),
    ]:
        if not t_list:
            print(f"\n{label}: No trades")
            continue

        returns = [t['return'] for t in t_list]
        pnls = [t['pnl'] for t in t_list]
        wins = sum(1 for r in returns if r > 0)

        rotations = sum(1 for t in t_list if t.get('type') == 'ROTATION') if 'type' in t_list[0] else 0

        total_pnl = sum(pnls)
        avg_ret = np.mean(returns)
        med_ret = np.median(returns)
        wr = wins / len(returns) * 100
        pf = abs(sum(r for r in returns if r > 0) / sum(r for r in returns if r < 0)) if any(r < 0 for r in returns) else float('inf')
        max_dd = min(returns)
        best = max(returns)

        # Calculate total return on capital
        total_capital_deployed = sum(t['capital'] for t in t_list)

        print(f"\n{'=' * 60}")
        print(f"  {label}")
        print(f"{'=' * 60}")
        print(f"  Trades: {len(t_list)} | Wins: {wins} | Losses: {len(t_list)-wins}")
        if rotations:
            print(f"  Rotations: {rotations} | Normal exits: {len(t_list)-rotations}")
        print(f"  Win Rate: {wr:.1f}%")
        print(f"  Avg Return: {avg_ret:+.2f}% | Median: {med_ret:+.2f}%")
        print(f"  Total P&L: ${total_pnl:+,.0f}")
        print(f"  Profit Factor: {pf:.2f}")
        print(f"  Best Trade: {best:+.1f}% | Worst: {max_dd:+.1f}%")

        # Monthly breakdown
        monthly = defaultdict(list)
        for t in t_list:
            month = t['exit_date'][:7]
            monthly[month].append(t['pnl'])

        print(f"\n  Monthly P&L:")
        total_running = 0
        for m in sorted(monthly.keys()):
            m_pnl = sum(monthly[m])
            total_running += m_pnl
            print(f"    {m}: ${m_pnl:+,.0f} ({len(monthly[m])} trades) | Running: ${total_running:+,.0f}")


if __name__ == "__main__":
    main()
