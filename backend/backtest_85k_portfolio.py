#!/usr/bin/env python3
"""
Backtest: $85,000 Portfolio Strategy for 1% Monthly Returns

Uses validated entry/exit strategies from model_learning.json
Simulates 12 months of trading with proper position sizing
"""

import json
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
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

@dataclass
class MonthlyResult:
    month: str
    starting_capital: float
    ending_capital: float
    trades: int
    winners: int
    losers: int
    win_rate: float
    gross_pnl: float
    fees: float
    net_pnl: float
    return_pct: float
    hit_target: bool

# Stock configurations with validated strategies
STOCK_CONFIG = {
    "MU": {
        "entry_strategy": "RSI2_EXTREME",  # RSI(2) < 5
        "entry_rsi_threshold": 5,
        "exit_strategy": "PROFIT_5",  # +5% profit target
        "exit_profit_target": 0.05,
        "stop_loss": -0.05,
        "max_hold_days": 10,
        "tier": 1,
        "expected_wr": 100.0
    },
    "QQQ": {
        "entry_strategy": "DOUBLE_RSI",  # RSI(2)<10 + RSI(14)<40
        "entry_rsi_threshold": 10,
        "exit_strategy": "PROFIT_5",
        "exit_profit_target": 0.05,
        "stop_loss": -0.04,
        "max_hold_days": 12,
        "tier": 1,
        "expected_wr": 83.3
    },
    "AMD": {
        "entry_strategy": "PULLBACK",  # Pullback in uptrend
        "entry_rsi_threshold": 15,
        "exit_strategy": "PROFIT_3",
        "exit_profit_target": 0.03,
        "stop_loss": -0.04,
        "max_hold_days": 7,
        "tier": 1,
        "expected_wr": 83.3
    },
    "GOOGL": {
        "entry_strategy": "RSI2_EXTREME",
        "entry_rsi_threshold": 5,
        "exit_strategy": "PROFIT_3",
        "exit_profit_target": 0.03,
        "stop_loss": -0.04,
        "max_hold_days": 7,
        "tier": 1,
        "expected_wr": 82.9
    },
    "SPY": {
        "entry_strategy": "RSI2_EXTREME",
        "entry_rsi_threshold": 5,
        "exit_strategy": "RSI_95",  # RSI(2) > 95
        "exit_rsi_threshold": 95,
        "exit_profit_target": 0.03,
        "stop_loss": -0.03,
        "max_hold_days": 7,
        "tier": 1,
        "expected_wr": 81.1
    },
    "IWM": {
        "entry_strategy": "PULLBACK",
        "entry_rsi_threshold": 15,
        "exit_strategy": "PROFIT_10",
        "exit_profit_target": 0.10,
        "stop_loss": -0.05,
        "max_hold_days": 21,
        "tier": 1,
        "expected_wr": 81.0
    },
    "JPM": {
        "entry_strategy": "DOUBLE_RSI",
        "entry_rsi_threshold": 10,
        "exit_strategy": "SMA5_CROSS",  # Price > SMA(5)
        "exit_profit_target": 0.03,
        "stop_loss": -0.04,
        "max_hold_days": 7,
        "tier": 2,
        "expected_wr": 77.8
    },
    "NVDA": {
        "entry_strategy": "DOUBLE_RSI",
        "entry_rsi_threshold": 10,
        "exit_strategy": "SMA5_CROSS",
        "exit_profit_target": 0.05,
        "stop_loss": -0.04,
        "max_hold_days": 7,
        "tier": 2,
        "expected_wr": 75.0
    },
    "DIS": {
        "entry_strategy": "RSI2_EXTREME",
        "entry_rsi_threshold": 5,
        "exit_strategy": "RSI_80",
        "exit_rsi_threshold": 80,
        "exit_profit_target": 0.03,
        "stop_loss": -0.04,
        "max_hold_days": 5,
        "tier": 2,
        "expected_wr": 75.0
    }
}

# Position sizing based on tier
POSITION_SIZES = {
    1: 12000,  # TIER 1: $12,000 per position
    2: 7000,   # TIER 2: $7,000 per position
}

TRANSACTION_FEE = 1.50  # Per trade
MONTHLY_TARGET = 0.01  # 1%


def fetch_stock_data(ticker: str, days: int = 400) -> List[Dict]:
    """Fetch historical data from Stooq"""
    url = f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d"
    try:
        response = requests.get(url, timeout=10)
        lines = response.text.strip().split('\n')

        if len(lines) < 2:
            return []

        data = []
        for line in lines[1:]:  # Skip header
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
    """Calculate RSI"""
    if len(prices) < period + 1:
        return 50.0

    changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    recent_changes = changes[-period:]

    gains = [c for c in recent_changes if c > 0]
    losses = [-c for c in recent_changes if c < 0]

    avg_gain = sum(gains) / period if gains else 0.001
    avg_loss = sum(losses) / period if losses else 0.001

    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_sma(prices: List[float], period: int) -> float:
    """Calculate Simple Moving Average"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period


def check_entry_signal(ticker: str, data: List[Dict], idx: int) -> bool:
    """Check if entry conditions are met"""
    config = STOCK_CONFIG.get(ticker)
    if not config or idx < 50:
        return False

    closes = [d['close'] for d in data[:idx+1]]
    current_price = closes[-1]

    rsi2 = calculate_rsi(closes, 2)
    rsi14 = calculate_rsi(closes, 14)
    sma50 = calculate_sma(closes, 50)

    strategy = config['entry_strategy']
    threshold = config['entry_rsi_threshold']

    # Must be in uptrend (price > SMA50)
    if current_price < sma50:
        return False

    if strategy == "RSI2_EXTREME":
        return rsi2 < threshold
    elif strategy == "DOUBLE_RSI":
        return rsi2 < threshold and rsi14 < 40
    elif strategy == "PULLBACK":
        # Pullback: RSI low but in uptrend
        return rsi2 < threshold and current_price > sma50 * 0.97

    return False


def check_exit_signal(ticker: str, data: List[Dict], idx: int, entry_price: float,
                      entry_idx: int) -> Tuple[bool, str]:
    """Check if exit conditions are met"""
    config = STOCK_CONFIG.get(ticker)
    if not config:
        return False, ""

    closes = [d['close'] for d in data[:idx+1]]
    current_price = closes[-1]

    # Calculate return
    return_pct = (current_price - entry_price) / entry_price

    # Stop loss check first
    if return_pct <= config['stop_loss']:
        return True, "STOP_LOSS"

    # Max hold days
    days_held = idx - entry_idx
    if days_held >= config['max_hold_days']:
        return True, "MAX_HOLD"

    # Profit target
    if return_pct >= config['exit_profit_target']:
        return True, "PROFIT_TARGET"

    # RSI-based exits
    rsi2 = calculate_rsi(closes, 2)
    exit_strategy = config['exit_strategy']

    if exit_strategy == "RSI_95" and rsi2 > 95:
        return True, "RSI_95"
    elif exit_strategy == "RSI_80" and rsi2 > 80:
        return True, "RSI_80"
    elif exit_strategy == "SMA5_CROSS":
        sma5 = calculate_sma(closes, 5)
        if current_price > sma5 and return_pct > 0.01:
            return True, "SMA5_CROSS"

    return False, ""


def run_backtest(start_capital: float = 85000, months: int = 12) -> Dict:
    """Run full backtest simulation"""
    print("=" * 70)
    print(f"BACKTEST: $85,000 Portfolio Strategy")
    print(f"Period: {months} months")
    print("=" * 70)

    # Fetch all data first
    print("\nFetching historical data...")
    all_data = {}
    for ticker in STOCK_CONFIG.keys():
        data = fetch_stock_data(ticker, 400)
        if data:
            all_data[ticker] = data
            print(f"  {ticker}: {len(data)} days loaded")
        else:
            print(f"  {ticker}: FAILED to load")

    if not all_data:
        return {"error": "No data loaded"}

    # Find common date range
    min_len = min(len(d) for d in all_data.values())
    print(f"\nUsing {min_len} days of common data")

    # Normalize all data to same length
    for ticker in all_data:
        all_data[ticker] = all_data[ticker][-min_len:]

    # Calculate trading days per month (~21)
    days_per_month = 21
    total_days = months * days_per_month

    if min_len < total_days + 50:
        total_days = min_len - 50
        months = total_days // days_per_month
        print(f"Adjusted to {months} months ({total_days} trading days)")

    # Initialize simulation
    capital = start_capital
    cash = start_capital
    positions = {}  # ticker -> Trade
    all_trades = []
    monthly_results = []

    start_idx = 50  # Need history for indicators

    # Track monthly boundaries
    current_month_start_capital = capital
    current_month_trades = []
    month_counter = 0
    days_in_month = 0

    print("\n" + "=" * 70)
    print("RUNNING SIMULATION...")
    print("=" * 70)

    for day_idx in range(start_idx, start_idx + total_days):
        days_in_month += 1

        # Get current date from SPY data
        current_date = all_data['SPY'][day_idx]['date']

        # Check exits first
        tickers_to_close = []
        for ticker, trade in positions.items():
            if ticker not in all_data:
                continue

            entry_idx = None
            for i, d in enumerate(all_data[ticker]):
                if d['date'] == trade.entry_date:
                    entry_idx = i
                    break

            if entry_idx is None:
                continue

            should_exit, exit_reason = check_exit_signal(
                ticker, all_data[ticker], day_idx, trade.entry_price, entry_idx
            )

            if should_exit:
                exit_price = all_data[ticker][day_idx]['close']
                trade.exit_date = current_date
                trade.exit_price = exit_price
                trade.return_pct = (exit_price - trade.entry_price) / trade.entry_price
                trade.return_dollar = trade.position_value * trade.return_pct
                trade.exit_reason = exit_reason
                trade.was_winner = trade.return_pct > 0

                # Return capital + profit/loss
                cash += trade.position_value + trade.return_dollar - TRANSACTION_FEE

                all_trades.append(trade)
                current_month_trades.append(trade)
                tickers_to_close.append(ticker)

        for ticker in tickers_to_close:
            del positions[ticker]

        # Check entries (only if we have cash)
        for ticker, config in STOCK_CONFIG.items():
            if ticker in positions:
                continue  # Already have position

            if ticker not in all_data:
                continue

            position_size = POSITION_SIZES[config['tier']]
            if cash < position_size:
                continue  # Not enough cash

            if check_entry_signal(ticker, all_data[ticker], day_idx):
                entry_price = all_data[ticker][day_idx]['close']
                shares = int(position_size / entry_price)
                actual_position = shares * entry_price

                if actual_position > cash:
                    continue

                trade = Trade(
                    ticker=ticker,
                    entry_date=current_date,
                    entry_price=entry_price,
                    shares=shares,
                    position_value=actual_position
                )

                cash -= (actual_position + TRANSACTION_FEE)
                positions[ticker] = trade

        # End of month processing
        if days_in_month >= days_per_month:
            # Calculate portfolio value
            portfolio_value = cash
            for ticker, trade in positions.items():
                if ticker in all_data:
                    current_price = all_data[ticker][day_idx]['close']
                    portfolio_value += trade.shares * current_price

            # Monthly stats
            winners = [t for t in current_month_trades if t.was_winner]
            losers = [t for t in current_month_trades if not t.was_winner]

            gross_pnl = sum(t.return_dollar for t in current_month_trades)
            fees = len(current_month_trades) * 2 * TRANSACTION_FEE  # Entry + exit
            net_pnl = portfolio_value - current_month_start_capital
            return_pct = net_pnl / current_month_start_capital

            month_result = MonthlyResult(
                month=f"Month {month_counter + 1}",
                starting_capital=current_month_start_capital,
                ending_capital=portfolio_value,
                trades=len(current_month_trades),
                winners=len(winners),
                losers=len(losers),
                win_rate=len(winners) / len(current_month_trades) * 100 if current_month_trades else 0,
                gross_pnl=gross_pnl,
                fees=fees,
                net_pnl=net_pnl,
                return_pct=return_pct,
                hit_target=return_pct >= MONTHLY_TARGET
            )

            monthly_results.append(month_result)

            # Print monthly summary
            status = "✅ HIT" if month_result.hit_target else "❌ MISS"
            print(f"\n{month_result.month}: {return_pct*100:+.2f}% (${net_pnl:+,.0f}) {status}")
            print(f"  Trades: {month_result.trades} | Win Rate: {month_result.win_rate:.1f}%")

            # Reset for next month
            month_counter += 1
            days_in_month = 0
            current_month_start_capital = portfolio_value
            current_month_trades = []
            capital = portfolio_value

    # Close any remaining positions at end
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

    # Final summary
    print("\n" + "=" * 70)
    print("BACKTEST RESULTS SUMMARY")
    print("=" * 70)

    total_return = (final_value - start_capital) / start_capital
    months_hit = sum(1 for m in monthly_results if m.hit_target)

    results = {
        "start_capital": start_capital,
        "final_value": final_value,
        "total_return_pct": total_return * 100,
        "total_return_dollar": final_value - start_capital,
        "months_tested": len(monthly_results),
        "months_hit_target": months_hit,
        "months_hit_pct": months_hit / len(monthly_results) * 100 if monthly_results else 0,
        "total_trades": len(all_trades),
        "total_winners": sum(1 for t in all_trades if t.was_winner),
        "total_losers": sum(1 for t in all_trades if not t.was_winner),
        "overall_win_rate": sum(1 for t in all_trades if t.was_winner) / len(all_trades) * 100 if all_trades else 0,
        "avg_winner": statistics.mean([t.return_pct for t in all_trades if t.was_winner]) * 100 if any(t.was_winner for t in all_trades) else 0,
        "avg_loser": statistics.mean([t.return_pct for t in all_trades if not t.was_winner]) * 100 if any(not t.was_winner for t in all_trades) else 0,
        "monthly_results": monthly_results,
        "all_trades": all_trades
    }

    print(f"\nStarting Capital:    ${start_capital:,.0f}")
    print(f"Final Value:         ${final_value:,.0f}")
    print(f"Total Return:        {total_return*100:+.2f}% (${final_value - start_capital:+,.0f})")
    print(f"\nMonths Tested:       {len(monthly_results)}")
    print(f"Months Hit 1%:       {months_hit} ({results['months_hit_pct']:.0f}%)")
    print(f"\nTotal Trades:        {len(all_trades)}")
    print(f"Winners:             {results['total_winners']}")
    print(f"Losers:              {results['total_losers']}")
    print(f"Win Rate:            {results['overall_win_rate']:.1f}%")
    print(f"\nAvg Winner:          {results['avg_winner']:+.2f}%")
    print(f"Avg Loser:           {results['avg_loser']:+.2f}%")

    # Monthly breakdown
    print("\n" + "-" * 70)
    print("MONTHLY BREAKDOWN")
    print("-" * 70)
    print(f"{'Month':<10} {'Return':>10} {'P&L':>12} {'Trades':>8} {'WR':>8} {'Target':>8}")
    print("-" * 70)

    for m in monthly_results:
        status = "✅" if m.hit_target else "❌"
        print(f"{m.month:<10} {m.return_pct*100:>+9.2f}% ${m.net_pnl:>+10,.0f} {m.trades:>8} {m.win_rate:>7.0f}% {status:>8}")

    print("-" * 70)
    avg_monthly = statistics.mean([m.return_pct for m in monthly_results]) * 100 if monthly_results else 0
    print(f"{'AVERAGE':<10} {avg_monthly:>+9.2f}%")

    # Save results
    save_results(results)

    return results


def save_results(results: Dict):
    """Save backtest results to JSON"""
    output = {
        "backtest_date": datetime.now().isoformat(),
        "strategy": "$85K Portfolio - 1% Monthly Target",
        "start_capital": results["start_capital"],
        "final_value": results["final_value"],
        "total_return_pct": results["total_return_pct"],
        "total_return_dollar": results["total_return_dollar"],
        "months_tested": results["months_tested"],
        "months_hit_target": results["months_hit_target"],
        "months_hit_pct": results["months_hit_pct"],
        "total_trades": results["total_trades"],
        "overall_win_rate": results["overall_win_rate"],
        "avg_winner_pct": results["avg_winner"],
        "avg_loser_pct": results["avg_loser"],
        "monthly_summary": [
            {
                "month": m.month,
                "return_pct": m.return_pct * 100,
                "net_pnl": m.net_pnl,
                "trades": m.trades,
                "win_rate": m.win_rate,
                "hit_target": m.hit_target
            }
            for m in results["monthly_results"]
        ],
        "trade_log": [
            {
                "ticker": t.ticker,
                "entry_date": t.entry_date,
                "entry_price": t.entry_price,
                "exit_date": t.exit_date,
                "exit_price": t.exit_price,
                "return_pct": t.return_pct * 100,
                "return_dollar": t.return_dollar,
                "exit_reason": t.exit_reason,
                "was_winner": t.was_winner
            }
            for t in results["all_trades"]
        ]
    }

    with open("data/backtest_85k_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults saved to data/backtest_85k_results.json")


if __name__ == "__main__":
    results = run_backtest(start_capital=85000, months=12)
