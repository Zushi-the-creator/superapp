#!/usr/bin/env python3
"""
Backtest V3: RSI Entry Timing + HOLD Strategy

Key Insight: RSI(2) works for ENTRY timing, but we should HOLD longer
in bull markets instead of exiting at overbought levels.

Strategy:
- Entry: RSI(2) < 20 (buy the dip)
- Exit: TRAILING STOP only (-7%) OR monthly rebalance
- Stay invested most of the time
- Compound winners, cut losers
"""

import json
import requests
from datetime import datetime
from typing import Dict, List
from dataclasses import dataclass
import statistics

@dataclass
class Position:
    ticker: str
    entry_date: str
    entry_price: float
    shares: int
    highest_price: float  # For trailing stop
    cost_basis: float

CORE_HOLDINGS = ["SPY", "QQQ"]  # Always hold these
ROTATION_POOL = ["NVDA", "AMD", "GOOGL", "AMZN", "META", "MSFT", "AAPL", "JPM", "V", "HD", "MU"]

STRATEGY = {
    "core_allocation": 0.50,      # 50% always in SPY/QQQ
    "rotation_allocation": 0.40,  # 40% in best RSI signals
    "cash_reserve": 0.10,         # 10% cash for opportunities
    "trailing_stop": 0.07,        # 7% trailing stop
    "rsi_entry": 25,              # RSI(2) < 25 for rotation entries
    "max_rotation_positions": 3,
}


def fetch_data(ticker: str, days: int = 500) -> List[Dict]:
    url = f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d"
    try:
        response = requests.get(url, timeout=10)
        lines = response.text.strip().split('\n')
        data = []
        for line in lines[1:]:
            parts = line.split(',')
            if len(parts) >= 5:
                try:
                    data.append({
                        'date': parts[0],
                        'close': float(parts[4])
                    })
                except:
                    continue
        return data[-days:] if len(data) > days else data
    except:
        return []


def calc_rsi(prices: List[float], period: int = 2) -> float:
    if len(prices) < period + 1:
        return 50
    changes = [prices[i] - prices[i-1] for i in range(1, len(prices))][-period:]
    gains = sum(c for c in changes if c > 0)
    losses = sum(-c for c in changes if c < 0)
    if losses == 0:
        return 100
    rs = (gains/period) / (losses/period)
    return 100 - (100 / (1 + rs))


def calc_sma(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1]
    return sum(prices[-period:]) / period


def run_backtest(capital: float = 85000, months: int = 12):
    print("="*70)
    print("BACKTEST V3: RSI Entry + HOLD Strategy")
    print("="*70)
    print(f"\nPhilosophy: Use RSI for ENTRY TIMING, then HOLD in bull market")
    print(f"Core: 50% SPY/QQQ (always hold)")
    print(f"Rotation: 40% in best RSI dips (NVDA, AMD, etc)")
    print(f"Cash: 10% reserve")
    print(f"Exit: 7% trailing stop only")

    # Fetch all data
    print(f"\nFetching data...")
    all_data = {}
    all_tickers = CORE_HOLDINGS + ROTATION_POOL
    for t in all_tickers:
        d = fetch_data(t, 500)
        if d and len(d) > 250:
            all_data[t] = d
            print(f"  {t}: {len(d)} days")

    min_len = min(len(d) for d in all_data.values())
    for t in all_data:
        all_data[t] = all_data[t][-min_len:]

    print(f"\nUsing {min_len} days of data")

    # Initialize
    cash = capital
    positions = {}
    trades_log = []
    monthly_results = []

    days_per_month = 21
    total_days = min(months * days_per_month, min_len - 250)
    start_idx = 250

    # Initial allocation - buy core holdings on day 1
    print(f"\n{'='*70}")
    print("SIMULATION")
    print("="*70)

    month_num = 0
    days_in_month = 0
    month_start_value = capital

    for day_idx in range(start_idx, start_idx + total_days):
        days_in_month += 1
        current_date = all_data['SPY'][day_idx]['date']

        # Calculate portfolio value
        portfolio_value = cash
        for ticker, pos in positions.items():
            if ticker in all_data:
                current_price = all_data[ticker][day_idx]['close']
                portfolio_value += pos.shares * current_price

        # === DAY 1: Initial Setup ===
        if day_idx == start_idx:
            # Buy core holdings (50% in SPY/QQQ)
            core_per_ticker = (capital * STRATEGY['core_allocation']) / len(CORE_HOLDINGS)
            for ticker in CORE_HOLDINGS:
                price = all_data[ticker][day_idx]['close']
                shares = int(core_per_ticker / price)
                cost = shares * price
                if cash >= cost:
                    positions[ticker] = Position(
                        ticker=ticker,
                        entry_date=current_date,
                        entry_price=price,
                        shares=shares,
                        highest_price=price,
                        cost_basis=cost
                    )
                    cash -= cost
                    print(f"  Initial: Bought {shares} {ticker} @ ${price:.2f}")

        # === CHECK TRAILING STOPS ===
        to_sell = []
        for ticker, pos in positions.items():
            if ticker in CORE_HOLDINGS:
                continue  # Never sell core

            current_price = all_data[ticker][day_idx]['close']

            # Update highest price
            if current_price > pos.highest_price:
                pos.highest_price = current_price

            # Check trailing stop
            drawdown = (pos.highest_price - current_price) / pos.highest_price
            if drawdown >= STRATEGY['trailing_stop']:
                to_sell.append(ticker)
                ret = (current_price - pos.entry_price) / pos.entry_price
                trades_log.append({
                    'ticker': ticker,
                    'entry': pos.entry_price,
                    'exit': current_price,
                    'return': ret * 100,
                    'reason': 'TRAILING_STOP'
                })
                cash += pos.shares * current_price
                print(f"  {current_date}: STOP {ticker} @ ${current_price:.2f} ({ret*100:+.1f}%)")

        for t in to_sell:
            del positions[t]

        # === CHECK RSI FOR NEW ENTRIES ===
        rotation_count = sum(1 for t in positions if t not in CORE_HOLDINGS)
        if rotation_count < STRATEGY['max_rotation_positions']:
            available_cash = cash - (portfolio_value * STRATEGY['cash_reserve'])

            if available_cash > 1000:
                # Find oversold rotation stocks
                candidates = []
                for ticker in ROTATION_POOL:
                    if ticker in positions or ticker not in all_data:
                        continue

                    closes = [d['close'] for d in all_data[ticker][:day_idx+1]]
                    rsi = calc_rsi(closes, 2)
                    sma200 = calc_sma(closes, 200)
                    price = closes[-1]

                    # Entry: RSI < 25 AND price > SMA200
                    if rsi < STRATEGY['rsi_entry'] and price > sma200:
                        candidates.append((ticker, rsi, price))

                # Buy most oversold
                candidates.sort(key=lambda x: x[1])
                for ticker, rsi, price in candidates[:1]:  # One at a time
                    position_size = min(available_cash, portfolio_value * 0.15)
                    shares = int(position_size / price)
                    if shares > 0 and cash >= shares * price:
                        positions[ticker] = Position(
                            ticker=ticker,
                            entry_date=current_date,
                            entry_price=price,
                            shares=shares,
                            highest_price=price,
                            cost_basis=shares * price
                        )
                        cash -= shares * price
                        print(f"  {current_date}: BUY {shares} {ticker} @ ${price:.2f} (RSI={rsi:.0f})")

        # === MONTHLY SUMMARY ===
        if days_in_month >= days_per_month:
            portfolio_value = cash
            for ticker, pos in positions.items():
                portfolio_value += pos.shares * all_data[ticker][day_idx]['close']

            ret = (portfolio_value - month_start_value) / month_start_value
            hit = ret >= 0.01
            status = "✅" if hit else "❌"

            monthly_results.append({
                'month': f'Month {month_num+1}',
                'return': ret * 100,
                'pnl': portfolio_value - month_start_value,
                'hit': hit
            })

            print(f"\n  Month {month_num+1}: {ret*100:+.2f}% (${portfolio_value - month_start_value:+,.0f}) {status}")

            month_num += 1
            days_in_month = 0
            month_start_value = portfolio_value

    # Final value
    final_value = cash
    for ticker, pos in positions.items():
        final_value += pos.shares * all_data[ticker][start_idx + total_days - 1]['close']

    # Summary
    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)

    total_return = (final_value - capital) / capital
    months_hit = sum(1 for m in monthly_results if m['hit'])

    print(f"\nStarting:     ${capital:,.0f}")
    print(f"Final:        ${final_value:,.0f}")
    print(f"Return:       {total_return*100:+.2f}%")

    print(f"\nMonths:       {len(monthly_results)}")
    print(f"Hit 1%+:      {months_hit} ({months_hit/len(monthly_results)*100:.0f}%)")

    print("\n" + "-"*50)
    for m in monthly_results:
        s = "✅" if m['hit'] else "❌"
        print(f"{m['month']}: {m['return']:+.2f}% {s}")
    print("-"*50)
    avg = statistics.mean([m['return'] for m in monthly_results])
    print(f"Average: {avg:+.2f}%")

    # Compare to SPY
    spy_start = all_data['SPY'][start_idx]['close']
    spy_end = all_data['SPY'][start_idx + total_days - 1]['close']
    spy_return = (spy_end - spy_start) / spy_start

    print(f"\n{'='*50}")
    print("COMPARISON")
    print("="*50)
    print(f"Our Strategy: {total_return*100:+.2f}%")
    print(f"SPY B&H:      {spy_return*100:+.2f}%")
    print(f"Difference:   {(total_return - spy_return)*100:+.2f}%")

    # Save
    with open("data/backtest_85k_v3.json", "w") as f:
        json.dump({
            "strategy": "RSI Entry + Hold",
            "total_return": total_return * 100,
            "spy_return": spy_return * 100,
            "months_hit": months_hit,
            "monthly": monthly_results
        }, f, indent=2)


if __name__ == "__main__":
    run_backtest(85000, 12)
