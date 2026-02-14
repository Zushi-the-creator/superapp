"""
V25.0 Mechanical Exit System

Industry-standard exit strategy used by professional traders:
- NO discretionary SELL signals
- Mechanical rules only: Stop-loss, Trailing stop, Profit targets

Research Backing:
- Trend following funds (AQR, Man Group): Let winners run, cut losers
- Academic: "Time in market beats timing the market"
- Quantitative: SELL signals have negative edge in bull markets

Author: Claude Trading Assistant
Created: 2026-01-21
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from enum import Enum


class ExitType(Enum):
    NONE = "NONE"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    PROFIT_TARGET_50 = "PROFIT_TARGET_50"
    PROFIT_TARGET_100 = "PROFIT_TARGET_100"
    TIME_STOP = "TIME_STOP"


@dataclass
class ExitConfig:
    """Configuration for mechanical exit system"""
    stop_loss_pct: float = 8.0          # Exit if down X% from entry
    trailing_stop_pct: float = 10.0      # Exit if down X% from peak
    trailing_activation_pct: float = 5.0 # Activate trailing after +X%
    profit_target_1_pct: float = 10.0    # First profit target
    profit_target_1_sell_pct: float = 50.0  # Sell X% at first target
    profit_target_2_pct: float = 20.0    # Second profit target (exit rest)
    time_stop_days: int = 14             # Re-evaluate if flat after X days


@dataclass
class Position:
    """Track a position through its lifecycle"""
    ticker: str
    entry_price: float
    entry_date: str
    shares: float
    current_price: float = 0.0
    highest_price: float = 0.0
    days_held: int = 0
    partial_exit_done: bool = False
    exit_price: float = 0.0
    exit_date: str = ""
    exit_type: ExitType = ExitType.NONE
    pnl_pct: float = 0.0


class MechanicalExitSystem:
    """
    V25.0 Mechanical Exit System

    Replaces SELL signals with mechanical rules:
    1. Stop-loss: Protect capital (-8% from entry)
    2. Trailing stop: Lock in gains (-10% from peak after +5%)
    3. Profit targets: Take profits at milestones (+10%, +20%)
    4. Time stop: Re-evaluate stale positions (14 days flat)
    """

    def __init__(self, config: ExitConfig = None):
        self.config = config or ExitConfig()

    def check_exit(self, position: Position) -> Tuple[ExitType, str, float]:
        """
        Check if position should exit based on mechanical rules.

        Returns:
            (exit_type, reason, suggested_exit_pct)
            suggested_exit_pct: 0 = no exit, 50 = partial, 100 = full exit
        """
        if position.current_price <= 0 or position.entry_price <= 0:
            return ExitType.NONE, "Invalid prices", 0

        # Calculate key metrics
        pnl_pct = ((position.current_price - position.entry_price) / position.entry_price) * 100

        # Update highest price for trailing stop
        if position.current_price > position.highest_price:
            position.highest_price = position.current_price

        drawdown_from_peak = ((position.highest_price - position.current_price) / position.highest_price) * 100

        # 1. STOP-LOSS: Protect capital (highest priority)
        if pnl_pct <= -self.config.stop_loss_pct:
            return (
                ExitType.STOP_LOSS,
                f"Stop-loss hit: {pnl_pct:.1f}% loss (limit: -{self.config.stop_loss_pct}%)",
                100  # Full exit
            )

        # 2. TRAILING STOP: Lock in gains (after activation)
        if pnl_pct >= self.config.trailing_activation_pct:
            if drawdown_from_peak >= self.config.trailing_stop_pct:
                return (
                    ExitType.TRAILING_STOP,
                    f"Trailing stop hit: {drawdown_from_peak:.1f}% from peak ${position.highest_price:.2f}",
                    100  # Full exit
                )

        # 3. PROFIT TARGET 1: Partial exit at +10%
        if pnl_pct >= self.config.profit_target_1_pct and not position.partial_exit_done:
            return (
                ExitType.PROFIT_TARGET_50,
                f"Profit target 1 hit: +{pnl_pct:.1f}% gain. Sell {self.config.profit_target_1_sell_pct:.0f}%",
                self.config.profit_target_1_sell_pct  # Partial exit
            )

        # 4. PROFIT TARGET 2: Full exit at +20%
        if pnl_pct >= self.config.profit_target_2_pct:
            return (
                ExitType.PROFIT_TARGET_100,
                f"Profit target 2 hit: +{pnl_pct:.1f}% gain. Exit remaining position",
                100  # Full exit
            )

        # 5. TIME STOP: Re-evaluate stale positions
        if position.days_held >= self.config.time_stop_days:
            if abs(pnl_pct) < 3:  # Flat (within +/-3%)
                return (
                    ExitType.TIME_STOP,
                    f"Time stop: {position.days_held} days held, only {pnl_pct:+.1f}% P&L. Re-evaluate.",
                    0  # Advisory, not automatic exit
                )

        return ExitType.NONE, "Hold - no exit trigger", 0

    def get_exit_levels(self, entry_price: float) -> Dict:
        """Calculate all exit levels for a position"""
        return {
            "entry": entry_price,
            "stop_loss": round(entry_price * (1 - self.config.stop_loss_pct / 100), 2),
            "trailing_activation": round(entry_price * (1 + self.config.trailing_activation_pct / 100), 2),
            "profit_target_1": round(entry_price * (1 + self.config.profit_target_1_pct / 100), 2),
            "profit_target_2": round(entry_price * (1 + self.config.profit_target_2_pct / 100), 2),
            "config": {
                "stop_loss_pct": self.config.stop_loss_pct,
                "trailing_stop_pct": self.config.trailing_stop_pct,
                "profit_target_1_pct": self.config.profit_target_1_pct,
                "profit_target_2_pct": self.config.profit_target_2_pct,
            }
        }


class BacktestEngine:
    """
    Backtest comparing:
    1. V25.0 Mechanical Exits (stop-loss + trailing + targets)
    2. Old SELL signals (RSI overbought, etc.)
    """

    def __init__(self, config: ExitConfig = None):
        self.exit_system = MechanicalExitSystem(config)
        self.config = config or ExitConfig()

    def _calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """Calculate RSI"""
        if len(closes) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, period + 1):
            diff = closes[-i] - closes[-(i+1)]
            gains.append(max(0, diff))
            losses.append(max(0, -diff))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _old_sell_signal(self, closes: List[float]) -> bool:
        """Old approach: SELL on RSI overbought"""
        rsi = self._calculate_rsi(closes, 14)
        rsi2 = self._calculate_rsi(closes, 2)

        # Old rules: RSI(14) > 70 OR RSI(2) > 90
        return rsi > 70 or rsi2 > 90

    def backtest_mechanical_exits(
        self,
        ticker: str,
        history: List[Dict],
        buy_signals: List[Dict],
        hold_days_max: int = 30
    ) -> Dict:
        """
        Backtest mechanical exit system on historical buy signals.

        Args:
            ticker: Stock symbol
            history: List of {date, open, high, low, close, volume}
            buy_signals: List of {date, entry_price} for BUY entries
            hold_days_max: Maximum days to simulate holding

        Returns:
            Backtest results comparing mechanical vs old SELL signals
        """
        results_mechanical = []
        results_old_sell = []

        # Create date->index mapping
        date_to_idx = {h['date']: i for i, h in enumerate(history)}

        for signal in buy_signals:
            entry_date = signal['date']
            if entry_date not in date_to_idx:
                continue

            entry_idx = date_to_idx[entry_date]
            entry_price = signal.get('entry_price', history[entry_idx]['close'])

            # Simulate holding for up to hold_days_max
            if entry_idx + hold_days_max >= len(history):
                continue

            # === MECHANICAL EXIT SIMULATION ===
            position = Position(
                ticker=ticker,
                entry_price=entry_price,
                entry_date=entry_date,
                shares=100,
                highest_price=entry_price
            )

            mechanical_exit_idx = None
            mechanical_exit_type = ExitType.NONE
            mechanical_exit_reason = ""

            for days in range(1, hold_days_max + 1):
                if entry_idx + days >= len(history):
                    break

                day_data = history[entry_idx + days]
                position.current_price = day_data['close']
                position.days_held = days

                # Check intraday low for stop-loss
                intraday_low = day_data.get('low', day_data['close'])
                position_with_low = Position(
                    ticker=ticker,
                    entry_price=entry_price,
                    entry_date=entry_date,
                    shares=100,
                    current_price=intraday_low,
                    highest_price=position.highest_price,
                    days_held=days
                )

                exit_type, reason, exit_pct = self.exit_system.check_exit(position_with_low)

                if exit_type in [ExitType.STOP_LOSS]:
                    mechanical_exit_idx = entry_idx + days
                    mechanical_exit_type = exit_type
                    mechanical_exit_reason = reason
                    position.exit_price = intraday_low
                    break

                # Check close price for other exits
                exit_type, reason, exit_pct = self.exit_system.check_exit(position)

                if exit_type in [ExitType.TRAILING_STOP, ExitType.PROFIT_TARGET_50, ExitType.PROFIT_TARGET_100]:
                    mechanical_exit_idx = entry_idx + days
                    mechanical_exit_type = exit_type
                    mechanical_exit_reason = reason
                    position.exit_price = position.current_price
                    if exit_type == ExitType.PROFIT_TARGET_50:
                        position.partial_exit_done = True
                    break

                # Update highest price
                if position.current_price > position.highest_price:
                    position.highest_price = position.current_price

            # If no exit triggered, use end of period
            if mechanical_exit_idx is None:
                mechanical_exit_idx = min(entry_idx + hold_days_max, len(history) - 1)
                position.exit_price = history[mechanical_exit_idx]['close']
                mechanical_exit_type = ExitType.NONE
                mechanical_exit_reason = f"Held full {hold_days_max} days"

            mech_pnl = ((position.exit_price - entry_price) / entry_price) * 100

            results_mechanical.append({
                'entry_date': entry_date,
                'entry_price': entry_price,
                'exit_price': position.exit_price,
                'exit_type': mechanical_exit_type.value,
                'exit_reason': mechanical_exit_reason,
                'days_held': mechanical_exit_idx - entry_idx,
                'pnl_pct': round(mech_pnl, 2),
                'won': mech_pnl > 0
            })

            # === OLD SELL SIGNAL SIMULATION ===
            old_exit_idx = None
            old_exit_price = entry_price

            for days in range(1, hold_days_max + 1):
                if entry_idx + days >= len(history):
                    break

                # Get closes up to this point for RSI calculation
                closes = [h['close'] for h in history[:entry_idx + days + 1]]

                if self._old_sell_signal(closes):
                    old_exit_idx = entry_idx + days
                    old_exit_price = history[old_exit_idx]['close']
                    break

            # If no SELL signal, hold to end
            if old_exit_idx is None:
                old_exit_idx = min(entry_idx + hold_days_max, len(history) - 1)
                old_exit_price = history[old_exit_idx]['close']

            old_pnl = ((old_exit_price - entry_price) / entry_price) * 100

            results_old_sell.append({
                'entry_date': entry_date,
                'entry_price': entry_price,
                'exit_price': old_exit_price,
                'days_held': old_exit_idx - entry_idx,
                'pnl_pct': round(old_pnl, 2),
                'won': old_pnl > 0
            })

        # Calculate summary statistics
        def calc_stats(results: List[Dict]) -> Dict:
            if not results:
                return {'trades': 0, 'win_rate': 0, 'avg_pnl': 0, 'total_pnl': 0}

            wins = sum(1 for r in results if r['won'])
            total_pnl = sum(r['pnl_pct'] for r in results)

            return {
                'trades': len(results),
                'wins': wins,
                'losses': len(results) - wins,
                'win_rate': round(wins / len(results) * 100, 1),
                'avg_pnl': round(total_pnl / len(results), 2),
                'total_pnl': round(total_pnl, 2),
                'avg_days_held': round(sum(r['days_held'] for r in results) / len(results), 1),
                'max_gain': round(max(r['pnl_pct'] for r in results), 2),
                'max_loss': round(min(r['pnl_pct'] for r in results), 2),
            }

        mech_stats = calc_stats(results_mechanical)
        old_stats = calc_stats(results_old_sell)

        return {
            'ticker': ticker,
            'period': f"{history[0]['date']} to {history[-1]['date']}",
            'mechanical_exits': {
                'stats': mech_stats,
                'trades': results_mechanical
            },
            'old_sell_signals': {
                'stats': old_stats,
                'trades': results_old_sell
            },
            'comparison': {
                'win_rate_improvement': round(mech_stats['win_rate'] - old_stats['win_rate'], 1),
                'avg_pnl_improvement': round(mech_stats['avg_pnl'] - old_stats['avg_pnl'], 2),
                'total_pnl_improvement': round(mech_stats['total_pnl'] - old_stats['total_pnl'], 2),
                'winner': 'MECHANICAL' if mech_stats['total_pnl'] > old_stats['total_pnl'] else 'OLD_SELL'
            },
            'config': {
                'stop_loss_pct': self.config.stop_loss_pct,
                'trailing_stop_pct': self.config.trailing_stop_pct,
                'trailing_activation_pct': self.config.trailing_activation_pct,
                'profit_target_1_pct': self.config.profit_target_1_pct,
                'profit_target_2_pct': self.config.profit_target_2_pct,
            }
        }


def run_full_backtest(tickers: List[str] = None) -> Dict:
    """
    Run complete backtest on portfolio tickers.
    Uses historical data and simulated BUY signals.
    """
    import os

    if tickers is None:
        tickers = ['NVDA', 'MU', 'QQQ']

    # Load historical data
    data_path = os.path.join(os.path.dirname(__file__), 'data', 'historical_backtest.json')

    if not os.path.exists(data_path):
        print(f"Historical data not found at {data_path}")
        return None

    with open(data_path, 'r') as f:
        historical_data = json.load(f)

    engine = BacktestEngine()
    all_results = {}

    for ticker in tickers:
        if ticker not in historical_data:
            print(f"No data for {ticker}")
            continue

        data = historical_data[ticker]

        # Convert to list format if needed
        if isinstance(data, dict) and 'closes' in data:
            # Convert from {closes: [], volumes: [], dates: []} format
            history = []
            closes = data['closes']
            volumes = data.get('volumes', [0] * len(closes))
            dates = data.get('dates', [f"2025-{i//21 + 1:02d}-{i%21 + 1:02d}" for i in range(len(closes))])

            for i in range(len(closes)):
                history.append({
                    'date': dates[i] if i < len(dates) else f"day_{i}",
                    'close': closes[i],
                    'open': closes[i] * 0.999,
                    'high': closes[i] * 1.01,
                    'low': closes[i] * 0.99,
                    'volume': volumes[i] if i < len(volumes) else 1000000
                })
        else:
            history = data

        # Generate BUY signals using RSI oversold (simple for backtest)
        buy_signals = []
        for i in range(30, len(history) - 30):
            closes = [h['close'] for h in history[:i+1]]

            # RSI(2) < 10 = extreme oversold = BUY
            if len(closes) > 14:
                gains, losses = [], []
                for j in range(1, 3):  # RSI(2)
                    diff = closes[-j] - closes[-(j+1)]
                    gains.append(max(0, diff))
                    losses.append(max(0, -diff))
                avg_gain = sum(gains) / 2
                avg_loss = sum(losses) / 2
                if avg_loss > 0:
                    rs = avg_gain / avg_loss
                    rsi2 = 100 - (100 / (1 + rs))

                    if rsi2 < 10:
                        buy_signals.append({
                            'date': history[i]['date'],
                            'entry_price': history[i]['close']
                        })

        # Limit to reasonable number of signals
        buy_signals = buy_signals[:50]

        if buy_signals:
            results = engine.backtest_mechanical_exits(
                ticker=ticker,
                history=history,
                buy_signals=buy_signals,
                hold_days_max=30
            )
            all_results[ticker] = results

            print(f"\n{'='*60}")
            print(f"📊 {ticker} BACKTEST RESULTS")
            print(f"{'='*60}")
            print(f"\nMECHANICAL EXITS (V25.0):")
            print(f"  Win Rate: {results['mechanical_exits']['stats']['win_rate']}%")
            print(f"  Avg P&L: {results['mechanical_exits']['stats']['avg_pnl']}%")
            print(f"  Total P&L: {results['mechanical_exits']['stats']['total_pnl']}%")
            print(f"  Avg Hold: {results['mechanical_exits']['stats']['avg_days_held']} days")

            print(f"\nOLD SELL SIGNALS (RSI Overbought):")
            print(f"  Win Rate: {results['old_sell_signals']['stats']['win_rate']}%")
            print(f"  Avg P&L: {results['old_sell_signals']['stats']['avg_pnl']}%")
            print(f"  Total P&L: {results['old_sell_signals']['stats']['total_pnl']}%")
            print(f"  Avg Hold: {results['old_sell_signals']['stats']['avg_days_held']} days")

            print(f"\n🏆 WINNER: {results['comparison']['winner']}")
            print(f"  Win Rate Improvement: {results['comparison']['win_rate_improvement']:+.1f}%")
            print(f"  Total P&L Improvement: {results['comparison']['total_pnl_improvement']:+.2f}%")

    # Save results
    output_path = os.path.join(os.path.dirname(__file__), 'data', 'v25_backtest_results.json')
    with open(output_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\n✅ Results saved to {output_path}")

    return all_results


if __name__ == "__main__":
    print("V25.0 Mechanical Exit System - Backtest")
    print("=" * 60)
    run_full_backtest(['NVDA', 'MU', 'QQQ'])
