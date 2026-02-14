#!/usr/bin/env python3
"""
CORRECTED Backtest: $85,000 Portfolio - RSI(2) Strategy

Based on QuantifiedStrategies.com research showing 91% win rate:
- Entry: RSI(2) < 15 (more signals than < 5)
- Exit: RSI(2) > 70 OR Price > 5-day SMA
- NO fixed stop loss (mean reversion works without it)
- Position sizing: 20% per position, max 5 positions
"""

import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from dataclasses import dataclass
import statistics

@dataclass
class Trade:
    ticker: str
    entry_date: str
    entry_price: float
    exit_date: str = ""
    exit_price: float = 0.0
    shares: int = 0
    position_value: float = 0.0
    return_pct: float = 0.0
    return_dollar: float = 0.0
    exit_reason: str = ""
    was_winner: bool = False
    days_held: int = 0

# Simplified strategy - same rules for all stocks
# Based on Larry Connors RSI(2) with proven 91% win rate
WATCHLIST = ["SPY", "QQQ", "IWM", "DIA", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "AMD",
             "META", "JPM", "V", "MA", "HD", "MU", "COST", "UNH", "JNJ", "PG"]

STRATEGY = {
    "entry_rsi": 15,        # RSI(2) < 15 = oversold
    "exit_rsi": 70,         # RSI(2) > 70 = overbought
    "max_hold_days": 10,    # Force exit after 10 days
    "position_pct": 0.20,   # 20% per position
    "max_positions": 5,     # Max 5 concurrent positions
    "use_sma_filter": True, # Only buy if price > SMA(200)
    "use_sma_exit": True,   # Exit if price > SMA(5)
}

TRANSACTION_FEE = 1.50


def fetch_stock_data(ticker: str, days: int = 500) -> List[Dict]:
    """Fetch historical data from Stooq"""
    url = f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d"
    try:
        response = requests.get(url, timeout=10)
        lines = response.text.strip().split('\n')

        if len(lines) < 2:
            return []

        data = []
        for line in lines[1:]:
            parts = line.split(',')
            if len(parts) >= 5:
                try:
                    data.append({
                        'date': parts[0],
                        'open': float(parts[1]),
                        'high': float(parts[2]),
                        'low': float(parts[3]),
                        'close': float(parts[4]),
                        'volume': int(float(parts[5])) if len(parts) > 5 else 0
                    })
                except (ValueError, IndexError):
                    continue

        return data[-days:] if len(data) > days else data
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return []


def calculate_rsi(prices: List[float], period: int = 2) -> float:
    """Calculate RSI - Wilder's method"""
    if len(prices) < period + 1:
        return 50.0

    changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    recent_changes = changes[-period:]

    gains = [c if c > 0 else 0 for c in recent_changes]
    losses = [-c if c < 0 else 0 for c in recent_changes]

    avg_gain = sum(gains) / period if gains else 0.001
    avg_loss = sum(losses) / period if losses else 0.001

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_sma(prices: List[float], period: int) -> float:
    """Calculate Simple Moving Average"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period


def run_corrected_backtest(start_capital: float = 85000, months: int = 12) -> Dict:
    """Run corrected backtest with proven RSI(2) strategy"""

    print("=" * 70)
    print("CORRECTED BACKTEST: RSI(2) Strategy (91% Expected Win Rate)")
    print("=" * 70)
    print(f"\nStrategy Rules:")
    print(f"  Entry: RSI(2) < {STRATEGY['entry_rsi']}")
    print(f"  Exit: RSI(2) > {STRATEGY['exit_rsi']} OR Price > SMA(5)")
    print(f"  Max Hold: {STRATEGY['max_hold_days']} days")
    print(f"  Position Size: {STRATEGY['position_pct']*100}% each")
    print(f"  Max Positions: {STRATEGY['max_positions']}")

    # Fetch data
    print(f"\nFetching data for {len(WATCHLIST)} stocks...")
    all_data = {}
    for ticker in WATCHLIST:
        data = fetch_stock_data(ticker, 500)
        if data and len(data) > 250:
            all_data[ticker] = data
            print(f"  {ticker}: {len(data)} days")

    if len(all_data) < 5:
        print("ERROR: Not enough data loaded")
        return {}

    # Find common date range
    min_len = min(len(d) for d in all_data.values())
    for ticker in all_data:
        all_data[ticker] = all_data[ticker][-min_len:]

    print(f"\nUsing {min_len} days of common data")

    # Simulation
    capital = start_capital
    cash = start_capital
    positions = {}  # ticker -> Trade
    all_trades = []

    days_per_month = 21
    total_days = min(months * days_per_month, min_len - 250)

    start_idx = 250  # Need 200+ days for SMA

    monthly_results = []
    month_start_capital = capital
    month_trades = []
    days_in_month = 0
    month_num = 0

    print(f"\n{'='*70}")
    print("RUNNING SIMULATION...")
    print("="*70)

    for day_idx in range(start_idx, start_idx + total_days):
        days_in_month += 1
        current_date = all_data['SPY'][day_idx]['date']

        # === CHECK EXITS ===
        to_close = []
        for ticker, trade in positions.items():
            if ticker not in all_data:
                continue

            closes = [d['close'] for d in all_data[ticker][:day_idx+1]]
            current_price = closes[-1]
            rsi2 = calculate_rsi(closes, 2)
            sma5 = calculate_sma(closes, 5)

            # Days held
            entry_idx = next((i for i, d in enumerate(all_data[ticker])
                            if d['date'] == trade.entry_date), day_idx)
            days_held = day_idx - entry_idx

            # Exit conditions
            exit_signal = False
            exit_reason = ""

            if rsi2 > STRATEGY['exit_rsi']:
                exit_signal = True
                exit_reason = f"RSI({rsi2:.0f})>70"
            elif STRATEGY['use_sma_exit'] and current_price > sma5:
                exit_signal = True
                exit_reason = "Price>SMA5"
            elif days_held >= STRATEGY['max_hold_days']:
                exit_signal = True
                exit_reason = "MAX_HOLD"

            if exit_signal:
                trade.exit_date = current_date
                trade.exit_price = current_price
                trade.return_pct = (current_price - trade.entry_price) / trade.entry_price
                trade.return_dollar = trade.position_value * trade.return_pct
                trade.exit_reason = exit_reason
                trade.was_winner = trade.return_pct > 0
                trade.days_held = days_held

                cash += trade.position_value + trade.return_dollar - TRANSACTION_FEE
                all_trades.append(trade)
                month_trades.append(trade)
                to_close.append(ticker)

        for ticker in to_close:
            del positions[ticker]

        # === CHECK ENTRIES ===
        if len(positions) < STRATEGY['max_positions']:
            # Calculate position size based on current capital
            portfolio_value = cash + sum(
                t.shares * all_data[t.ticker][day_idx]['close']
                for t in positions.values() if t.ticker in all_data
            )
            position_size = portfolio_value * STRATEGY['position_pct']

            # Find stocks with entry signals
            candidates = []
            for ticker in all_data:
                if ticker in positions:
                    continue

                closes = [d['close'] for d in all_data[ticker][:day_idx+1]]
                current_price = closes[-1]
                rsi2 = calculate_rsi(closes, 2)
                sma200 = calculate_sma(closes, 200)

                # Entry: RSI < 15 AND price > SMA200 (uptrend filter)
                if rsi2 < STRATEGY['entry_rsi']:
                    if not STRATEGY['use_sma_filter'] or current_price > sma200:
                        candidates.append((ticker, rsi2, current_price))

            # Sort by lowest RSI (most oversold first)
            candidates.sort(key=lambda x: x[1])

            # Enter positions
            for ticker, rsi2, price in candidates:
                if len(positions) >= STRATEGY['max_positions']:
                    break
                if cash < position_size:
                    break

                shares = int(position_size / price)
                actual_value = shares * price

                if actual_value > cash:
                    continue

                trade = Trade(
                    ticker=ticker,
                    entry_date=current_date,
                    entry_price=price,
                    shares=shares,
                    position_value=actual_value
                )

                cash -= (actual_value + TRANSACTION_FEE)
                positions[ticker] = trade

        # === MONTHLY SUMMARY ===
        if days_in_month >= days_per_month:
            portfolio_value = cash + sum(
                t.shares * all_data[t.ticker][day_idx]['close']
                for t in positions.values() if t.ticker in all_data
            )

            net_pnl = portfolio_value - month_start_capital
            return_pct = net_pnl / month_start_capital

            winners = [t for t in month_trades if t.was_winner]
            win_rate = len(winners) / len(month_trades) * 100 if month_trades else 0

            hit_target = return_pct >= 0.01
            status = "✅ HIT" if hit_target else "❌ MISS"

            print(f"\nMonth {month_num+1}: {return_pct*100:+.2f}% (${net_pnl:+,.0f}) {status}")
            print(f"  Trades: {len(month_trades)} | Winners: {len(winners)} | Win Rate: {win_rate:.0f}%")

            monthly_results.append({
                "month": f"Month {month_num+1}",
                "return_pct": return_pct * 100,
                "net_pnl": net_pnl,
                "trades": len(month_trades),
                "winners": len(winners),
                "win_rate": win_rate,
                "hit_target": hit_target
            })

            # Reset for next month
            month_num += 1
            days_in_month = 0
            month_start_capital = portfolio_value
            month_trades = []
            capital = portfolio_value

    # Close remaining positions
    final_value = cash
    for ticker, trade in positions.items():
        if ticker in all_data:
            final_price = all_data[ticker][start_idx + total_days - 1]['close']
            trade.exit_price = final_price
            trade.return_pct = (final_price - trade.entry_price) / trade.entry_price
            trade.return_dollar = trade.position_value * trade.return_pct
            trade.was_winner = trade.return_pct > 0
            final_value += trade.shares * final_price
            all_trades.append(trade)

    # === FINAL SUMMARY ===
    print("\n" + "="*70)
    print("CORRECTED BACKTEST RESULTS")
    print("="*70)

    total_return = (final_value - start_capital) / start_capital
    winners = [t for t in all_trades if t.was_winner]
    losers = [t for t in all_trades if not t.was_winner]

    months_hit = sum(1 for m in monthly_results if m['hit_target'])

    print(f"\nStarting Capital:     ${start_capital:,.0f}")
    print(f"Final Value:          ${final_value:,.0f}")
    print(f"Total Return:         {total_return*100:+.2f}% (${final_value - start_capital:+,.0f})")
    print(f"Annualized:           {total_return*100:.1f}%")

    print(f"\nMonths Tested:        {len(monthly_results)}")
    print(f"Months Hit 1%+:       {months_hit} ({months_hit/len(monthly_results)*100:.0f}%)")

    print(f"\nTotal Trades:         {len(all_trades)}")
    print(f"Winners:              {len(winners)} ({len(winners)/len(all_trades)*100:.1f}%)")
    print(f"Losers:               {len(losers)} ({len(losers)/len(all_trades)*100:.1f}%)")

    if winners:
        print(f"\nAvg Winner:           +{statistics.mean([t.return_pct for t in winners])*100:.2f}%")
    if losers:
        print(f"Avg Loser:            {statistics.mean([t.return_pct for t in losers])*100:.2f}%")

    avg_days = statistics.mean([t.days_held for t in all_trades if t.days_held > 0])
    print(f"Avg Days Held:        {avg_days:.1f}")

    # Monthly breakdown
    print("\n" + "-"*70)
    print("MONTHLY BREAKDOWN")
    print("-"*70)
    print(f"{'Month':<10} {'Return':>10} {'P&L':>12} {'Trades':>8} {'WR':>8} {'Target':>8}")
    print("-"*70)

    for m in monthly_results:
        status = "✅" if m['hit_target'] else "❌"
        print(f"{m['month']:<10} {m['return_pct']:>+9.2f}% ${m['net_pnl']:>+10,.0f} {m['trades']:>8} {m['win_rate']:>7.0f}% {status:>8}")

    print("-"*70)
    avg_monthly = statistics.mean([m['return_pct'] for m in monthly_results])
    print(f"{'AVERAGE':<10} {avg_monthly:>+9.2f}%")
    print(f"{'TARGET':<10} {'+1.00%':>10}")

    # Save results
    results = {
        "backtest_date": datetime.now().isoformat(),
        "strategy": "RSI(2) Corrected - Based on 91% Win Rate Research",
        "start_capital": start_capital,
        "final_value": final_value,
        "total_return_pct": total_return * 100,
        "annualized_return": total_return * 100,
        "months_tested": len(monthly_results),
        "months_hit_target": months_hit,
        "months_hit_pct": months_hit / len(monthly_results) * 100,
        "total_trades": len(all_trades),
        "win_rate": len(winners) / len(all_trades) * 100,
        "avg_winner": statistics.mean([t.return_pct for t in winners]) * 100 if winners else 0,
        "avg_loser": statistics.mean([t.return_pct for t in losers]) * 100 if losers else 0,
        "avg_days_held": avg_days,
        "monthly_results": monthly_results
    }

    with open("data/backtest_85k_corrected.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to data/backtest_85k_corrected.json")

    return results


if __name__ == "__main__":
    run_corrected_backtest(85000, 12)
