"""
Backtesting Module
Test historical signals and track performance
"""

import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import pandas as pd

from historical import HistoricalDataManager


class BacktestEngine:
    """
    Backtest trading signals against historical data
    """

    def __init__(self, historical_manager: HistoricalDataManager):
        self.historical = historical_manager

    async def backtest_signal(self, ticker: str, date: str) -> Dict:
        """
        Get the signal that was generated on a specific date

        Args:
            ticker: Stock ticker
            date: Date in YYYY-MM-DD format

        Returns:
            Dict with signal data from that date
        """
        signal_data = await self.historical.get_signal_on_date(ticker, date)

        if not signal_data:
            return {
                "error": f"No data found for {ticker} on {date}",
                "ticker": ticker,
                "date": date
            }

        # Get subsequent price movement (next 1, 7, 30 days)
        df = await self.historical.get_stock_history(ticker, days=365)

        if df.empty:
            return signal_data

        # Find the date in dataframe
        df['date'] = pd.to_datetime(df['date'])
        target_date = pd.to_datetime(date)

        df = df[df['date'] >= target_date].sort_values('date')

        if len(df) == 0:
            return signal_data

        # Calculate forward returns
        entry_price = signal_data['price']

        forward_returns = {}

        # 1 day forward
        if len(df) > 1:
            next_day_price = df.iloc[1]['price']
            forward_returns['1_day'] = ((next_day_price - entry_price) / entry_price) * 100

        # 7 days forward
        if len(df) > 7:
            week_price = df.iloc[min(7, len(df)-1)]['price']
            forward_returns['7_day'] = ((week_price - entry_price) / entry_price) * 100

        # 30 days forward
        if len(df) > 30:
            month_price = df.iloc[min(30, len(df)-1)]['price']
            forward_returns['30_day'] = ((month_price - entry_price) / entry_price) * 100

        # Was the signal correct?
        signal_correct = False
        if signal_data['signal'] == 'BUY' and forward_returns.get('7_day', 0) > 0:
            signal_correct = True
        elif signal_data['signal'] == 'SELL' and forward_returns.get('7_day', 0) < 0:
            signal_correct = True

        return {
            **signal_data,
            "forward_returns": forward_returns,
            "signal_correct": signal_correct,
            "accuracy_period": "7_day"
        }

    async def backtest_ticker_range(self, ticker: str, start_date: str, end_date: str) -> Dict:
        """
        Backtest all signals for a ticker over a date range

        Args:
            ticker: Stock ticker
            start_date: Start date YYYY-MM-DD
            end_date: End date YYYY-MM-DD

        Returns:
            Dict with backtest results and statistics
        """
        df = await self.historical.get_stock_history(ticker, days=730)

        if df.empty:
            return {
                "error": f"No historical data for {ticker}",
                "ticker": ticker
            }

        # Filter date range
        df['date'] = pd.to_datetime(df['date'])
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)

        df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)].sort_values('date')

        if len(df) == 0:
            return {
                "error": f"No data in date range {start_date} to {end_date}",
                "ticker": ticker
            }

        # Analyze each signal
        results = []
        buy_signals = []
        sell_signals = []

        for idx in range(len(df) - 7):  # Need at least 7 days forward
            row = df.iloc[idx]
            entry_price = row['price']
            signal = row['signal']

            # Calculate 7-day forward return
            forward_row = df.iloc[idx + 7]
            forward_price = forward_row['price']
            forward_return = ((forward_price - entry_price) / entry_price) * 100

            # Was signal correct?
            correct = False
            if signal == 'BUY' and forward_return > 0:
                correct = True
            elif signal == 'SELL' and forward_return < 0:
                correct = True

            result = {
                "date": row['date'].strftime('%Y-%m-%d'),
                "signal": signal,
                "entry_price": float(entry_price),
                "forward_price": float(forward_price),
                "forward_return": float(forward_return),
                "correct": correct,
                "rsi": float(row['rsi']),
                "signal_strength": int(row['signal_strength'])
            }

            results.append(result)

            if signal == 'BUY':
                buy_signals.append(result)
            elif signal == 'SELL':
                sell_signals.append(result)

        # Calculate statistics
        total_signals = len(results)
        correct_signals = len([r for r in results if r['correct']])
        win_rate = correct_signals / total_signals if total_signals > 0 else 0

        avg_return = sum(r['forward_return'] for r in results) / total_signals if total_signals > 0 else 0

        # Buy signal stats
        buy_win_rate = len([r for r in buy_signals if r['correct']]) / len(buy_signals) if buy_signals else 0
        buy_avg_return = sum(r['forward_return'] for r in buy_signals) / len(buy_signals) if buy_signals else 0

        # Sell signal stats
        sell_win_rate = len([r for r in sell_signals if r['correct']]) / len(sell_signals) if sell_signals else 0
        sell_avg_return = sum(r['forward_return'] for r in sell_signals) / len(sell_signals) if sell_signals else 0

        return {
            "ticker": ticker,
            "start_date": start_date,
            "end_date": end_date,
            "total_signals": total_signals,
            "correct_signals": correct_signals,
            "win_rate": round(win_rate * 100, 2),
            "avg_return_pct": round(avg_return, 2),
            "buy_signals": {
                "count": len(buy_signals),
                "win_rate": round(buy_win_rate * 100, 2),
                "avg_return_pct": round(buy_avg_return, 2)
            },
            "sell_signals": {
                "count": len(sell_signals),
                "win_rate": round(sell_win_rate * 100, 2),
                "avg_return_pct": round(sell_avg_return, 2)
            },
            "results": results[-50:]  # Last 50 signals
        }

    async def get_signal_accuracy_summary(self, days: int = 30) -> Dict:
        """
        Get overall signal accuracy across all tracked stocks

        Args:
            days: Days to look back

        Returns:
            Dict with accuracy statistics
        """
        # Get all tickers with historical data
        tickers = await self.historical.get_all_tickers_history(limit=100)

        if not tickers:
            return {
                "error": "No historical data available",
                "tickers_analyzed": 0
            }

        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')

        all_results = []

        for ticker in tickers[:50]:  # Limit to 50 tickers for performance
            try:
                result = await self.backtest_ticker_range(ticker, cutoff_date, today)
                if 'error' not in result:
                    all_results.append(result)
            except Exception as e:
                print(f"Error backtesting {ticker}: {e}")
                continue

        if not all_results:
            return {
                "error": "No backtest results generated",
                "tickers_analyzed": 0
            }

        # Aggregate statistics
        total_signals = sum(r['total_signals'] for r in all_results)
        correct_signals = sum(r['correct_signals'] for r in all_results)
        overall_win_rate = correct_signals / total_signals if total_signals > 0 else 0

        total_buy = sum(r['buy_signals']['count'] for r in all_results)
        total_sell = sum(r['sell_signals']['count'] for r in all_results)

        # Weighted average returns
        avg_return = sum(r['avg_return_pct'] * r['total_signals'] for r in all_results) / total_signals if total_signals > 0 else 0

        return {
            "period_days": days,
            "tickers_analyzed": len(all_results),
            "total_signals": total_signals,
            "correct_signals": correct_signals,
            "overall_win_rate": round(overall_win_rate * 100, 2),
            "avg_return_pct": round(avg_return, 2),
            "buy_signals_count": total_buy,
            "sell_signals_count": total_sell,
            "best_performers": sorted(
                all_results,
                key=lambda x: x['win_rate'],
                reverse=True
            )[:10],
            "worst_performers": sorted(
                all_results,
                key=lambda x: x['win_rate']
            )[:10]
        }

    async def compare_signal_vs_actual(self, ticker: str, entry_date: str,
                                       entry_price: float) -> Dict:
        """
        Compare what signal was generated vs actual outcome

        Args:
            ticker: Stock ticker
            entry_date: Date position was entered
            entry_price: Price at entry

        Returns:
            Dict comparing signal recommendation vs actual performance
        """
        # Get signal on that date
        signal_data = await self.backtest_signal(ticker, entry_date)

        if 'error' in signal_data:
            return signal_data

        # Get current price
        df = await self.historical.get_stock_history(ticker, days=30)

        if df.empty:
            return {
                "error": "Unable to get current price",
                "ticker": ticker
            }

        current_price = df.iloc[-1]['price']
        current_date = df.iloc[-1]['date']

        # Calculate actual return
        actual_return = ((current_price - entry_price) / entry_price) * 100

        # What did our signal say?
        our_signal = signal_data['signal']
        our_strength = signal_data['signal_strength']
        our_rsi = signal_data['rsi']

        # Verdict
        if our_signal == 'BUY' and actual_return > 5:
            verdict = "✅ CORRECT - Signal was BUY and position is profitable"
        elif our_signal == 'SELL' and actual_return < -5:
            verdict = "✅ CORRECT - Signal was SELL and price declined"
        elif our_signal == 'HOLD':
            verdict = "⚠️ NEUTRAL - Signal was HOLD"
        elif our_signal == 'BUY' and actual_return < -10:
            verdict = "❌ INCORRECT - Signal was BUY but position lost >10%"
        elif our_signal == 'SELL' and actual_return > 10:
            verdict = "❌ INCORRECT - Signal was SELL but price increased >10%"
        else:
            verdict = "⏳ UNCLEAR - Result within normal variance"

        return {
            "ticker": ticker,
            "entry_date": entry_date,
            "entry_price": entry_price,
            "current_price": float(current_price),
            "current_date": current_date,
            "actual_return_pct": round(actual_return, 2),
            "our_signal": our_signal,
            "signal_strength": our_strength,
            "rsi_at_entry": our_rsi,
            "verdict": verdict,
            "forward_returns": signal_data.get('forward_returns', {}),
            "was_correct": signal_data.get('signal_correct', False)
        }
