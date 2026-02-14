"""
Historical Data Storage and Analysis Module
Stores daily snapshots of stock data for backtesting, seasonality detection, and spike prediction
"""

import sqlite3
import asyncio
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from pathlib import Path


class HistoricalDataManager:
    """
    Manages historical stock data storage and retrieval
    Uses SQLite for efficient time-series queries
    """

    def __init__(self, db_path: str = "data/historical.db"):
        self.db_path = db_path

        # Ensure data directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_database()

    def _init_database(self):
        """Create database tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Stock history table - daily snapshots
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                price REAL NOT NULL,
                change_pct REAL NOT NULL,
                volume INTEGER NOT NULL,
                volume_ratio REAL NOT NULL,
                rsi REAL NOT NULL,
                ema_fast REAL NOT NULL,
                ema_slow REAL NOT NULL,
                signal TEXT NOT NULL,
                signal_strength INTEGER NOT NULL,
                sentiment_score REAL NOT NULL,
                sentiment_label TEXT NOT NULL,
                combined_score INTEGER NOT NULL,
                sector TEXT,
                is_hot INTEGER DEFAULT 0,
                UNIQUE(ticker, date)
            )
        """)

        # Create indexes for fast queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticker ON stock_history(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON stock_history(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticker_date ON stock_history(ticker, date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal ON stock_history(signal)")

        # Signal performance table - track how each signal performed
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                signal_date TEXT NOT NULL,
                signal TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                exit_date TEXT,
                days_held INTEGER,
                return_pct REAL,
                was_correct INTEGER,
                signal_strength INTEGER,
                rsi_at_signal REAL,
                timestamp INTEGER NOT NULL
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_perf_ticker ON signal_performance(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_perf_signal ON signal_performance(signal)")

        conn.commit()
        conn.close()

        print(f"Historical database initialized at {self.db_path}")

    async def store_snapshot(self, stock_data: Dict):
        """Store a daily snapshot of stock data"""
        try:
            await asyncio.to_thread(self._store_snapshot_sync, stock_data)
        except Exception as e:
            print(f"Error storing snapshot for {stock_data.get('ticker')}: {e}")

    def _store_snapshot_sync(self, stock_data: Dict):
        """Synchronous version of store_snapshot"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        today = datetime.now().strftime('%Y-%m-%d')

        cursor.execute("""
            INSERT OR REPLACE INTO stock_history
            (ticker, date, timestamp, price, change_pct, volume, volume_ratio,
             rsi, ema_fast, ema_slow, signal, signal_strength, sentiment_score,
             sentiment_label, combined_score, sector, is_hot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            stock_data['ticker'],
            today,
            int(datetime.now().timestamp()),
            stock_data['price'],
            stock_data['change_pct'],
            stock_data['volume'],
            stock_data['volume_ratio'],
            stock_data['rsi'],
            stock_data.get('ema_fast', 0),
            stock_data.get('ema_slow', 0),
            stock_data['signal'],
            stock_data['signal_strength'],
            stock_data['sentiment_score'],
            stock_data['sentiment_label'],
            stock_data['combined_score'],
            stock_data.get('sector', ''),
            int(stock_data.get('is_hot', False))
        ))

        conn.commit()
        conn.close()

    async def get_stock_history(self, ticker: str, days: int = 365) -> pd.DataFrame:
        """Get historical data for a ticker"""
        try:
            return await asyncio.to_thread(self._get_stock_history_sync, ticker, days)
        except Exception as e:
            print(f"Error getting history for {ticker}: {e}")
            return pd.DataFrame()

    def _get_stock_history_sync(self, ticker: str, days: int) -> pd.DataFrame:
        """Synchronous version of get_stock_history"""
        conn = sqlite3.connect(self.db_path)

        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        query = """
            SELECT * FROM stock_history
            WHERE ticker = ? AND date >= ?
            ORDER BY date ASC
        """

        df = pd.read_sql_query(query, conn, params=(ticker, cutoff_date))
        conn.close()

        return df

    async def get_signal_on_date(self, ticker: str, date: str) -> Optional[Dict]:
        """Get what signal was generated on a specific date (for backtesting)"""
        try:
            return await asyncio.to_thread(self._get_signal_on_date_sync, ticker, date)
        except Exception as e:
            print(f"Error getting signal for {ticker} on {date}: {e}")
            return None

    def _get_signal_on_date_sync(self, ticker: str, date: str) -> Optional[Dict]:
        """Synchronous version of get_signal_on_date"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM stock_history
            WHERE ticker = ? AND date = ?
        """, (ticker, date))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        columns = ['id', 'ticker', 'date', 'timestamp', 'price', 'change_pct', 'volume',
                   'volume_ratio', 'rsi', 'ema_fast', 'ema_slow', 'signal', 'signal_strength',
                   'sentiment_score', 'sentiment_label', 'combined_score', 'sector', 'is_hot']

        return dict(zip(columns, row))

    async def detect_seasonality(self, ticker: str) -> Dict:
        """
        Detect seasonal patterns in stock performance

        Returns:
            Dict with seasonal insights (best months, quarterly patterns, etc.)
        """
        df = await self.get_stock_history(ticker, days=730)  # 2 years

        if df.empty or len(df) < 60:
            return {
                "has_data": False,
                "message": "Insufficient historical data for seasonality analysis"
            }

        df['date'] = pd.to_datetime(df['date'])
        df['month'] = df['date'].dt.month
        df['quarter'] = df['date'].dt.quarter
        df['day_of_week'] = df['date'].dt.dayofweek

        # Analyze monthly performance
        monthly_returns = df.groupby('month')['change_pct'].agg(['mean', 'std', 'count'])
        best_months = monthly_returns.nlargest(3, 'mean')
        worst_months = monthly_returns.nsmallest(3, 'mean')

        # Analyze quarterly patterns
        quarterly_returns = df.groupby('quarter')['change_pct'].agg(['mean', 'std', 'count'])
        best_quarter = quarterly_returns['mean'].idxmax()

        # Analyze day of week patterns
        dow_returns = df.groupby('day_of_week')['change_pct'].mean()

        # Calculate volatility by month
        volatility_by_month = df.groupby('month')['change_pct'].std()
        most_volatile_month = volatility_by_month.idxmax()

        return {
            "has_data": True,
            "ticker": ticker,
            "data_points": len(df),
            "date_range": {
                "start": df['date'].min().strftime('%Y-%m-%d'),
                "end": df['date'].max().strftime('%Y-%m-%d')
            },
            "best_months": [
                {"month": int(idx), "avg_return": float(row['mean']), "count": int(row['count'])}
                for idx, row in best_months.iterrows()
            ],
            "worst_months": [
                {"month": int(idx), "avg_return": float(row['mean']), "count": int(row['count'])}
                for idx, row in worst_months.iterrows()
            ],
            "best_quarter": int(best_quarter),
            "best_quarter_return": float(quarterly_returns.loc[best_quarter, 'mean']),
            "most_volatile_month": int(most_volatile_month),
            "day_of_week_patterns": {
                "monday": float(dow_returns.get(0, 0)),
                "tuesday": float(dow_returns.get(1, 0)),
                "wednesday": float(dow_returns.get(2, 0)),
                "thursday": float(dow_returns.get(3, 0)),
                "friday": float(dow_returns.get(4, 0))
            }
        }

    async def predict_spike(self, ticker: str, current_data: Dict) -> Dict:
        """
        Predict probability of price spike based on historical patterns

        Uses statistical analysis of:
        - RSI patterns before spikes
        - Volume anomalies
        - Sentiment shifts
        - Historical price movements
        """
        df = await self.get_stock_history(ticker, days=180)  # 6 months

        if df.empty or len(df) < 30:
            return {
                "has_prediction": False,
                "message": "Insufficient historical data for spike prediction"
            }

        # Define spike as +5% single day move
        df['is_spike'] = df['change_pct'] > 5.0
        df['price_shift'] = df['price'].shift(-1)  # Next day price
        df['next_day_change'] = ((df['price_shift'] - df['price']) / df['price'] * 100)

        # Calculate features at current state
        current_rsi = current_data['rsi']
        current_volume_ratio = current_data['volume_ratio']
        current_sentiment = current_data['sentiment_score']

        # Historical analysis: what happened after similar conditions?
        similar_conditions = df[
            (df['rsi'].between(current_rsi - 10, current_rsi + 10)) &
            (df['volume_ratio'] > 1.5)  # High volume
        ]

        spike_probability = 0.0
        spike_indicators = []

        # Indicator 1: RSI oversold/overbought extremes
        if current_rsi < 30:
            spike_probability += 0.25
            spike_indicators.append("RSI oversold - potential bounce")
        elif current_rsi > 70:
            spike_probability += 0.15
            spike_indicators.append("RSI overbought - momentum continuation possible")

        # Indicator 2: Volume surge
        if current_volume_ratio > 3.0:
            spike_probability += 0.30
            spike_indicators.append(f"Volume surge ({current_volume_ratio:.1f}x) - strong interest")
        elif current_volume_ratio > 2.0:
            spike_probability += 0.20
            spike_indicators.append(f"Elevated volume ({current_volume_ratio:.1f}x)")

        # Indicator 3: Sentiment shift
        if current_sentiment > 0.3:
            spike_probability += 0.20
            spike_indicators.append("Positive sentiment shift")
        elif current_sentiment < -0.3:
            spike_probability += 0.10
            spike_indicators.append("Negative sentiment - potential reversal")

        # Indicator 4: Historical pattern matching
        if not similar_conditions.empty:
            avg_next_day = similar_conditions['next_day_change'].mean()
            if avg_next_day > 3:
                spike_probability += 0.15
                spike_indicators.append(f"Historical pattern: similar conditions led to {avg_next_day:.1f}% avg move")

        # Cap probability at 95%
        spike_probability = min(spike_probability, 0.95)

        # Calculate expected move
        recent_volatility = df['change_pct'].tail(30).std()
        expected_move = recent_volatility * 1.5 if spike_probability > 0.5 else recent_volatility

        return {
            "has_prediction": True,
            "ticker": ticker,
            "spike_probability": float(spike_probability),
            "confidence": "high" if spike_probability > 0.6 else "medium" if spike_probability > 0.4 else "low",
            "expected_move_pct": float(expected_move),
            "indicators": spike_indicators,
            "historical_data_points": len(df),
            "similar_conditions_found": len(similar_conditions),
            "current_conditions": {
                "rsi": current_rsi,
                "volume_ratio": current_volume_ratio,
                "sentiment_score": current_sentiment
            }
        }

    async def get_signal_performance(self, signal_type: Optional[str] = None, days: int = 30) -> Dict:
        """
        Get performance statistics for signals over time period

        Args:
            signal_type: 'BUY', 'SELL', or None for all
            days: Days to look back

        Returns:
            Dict with win rate, avg return, etc.
        """
        try:
            return await asyncio.to_thread(self._get_signal_performance_sync, signal_type, days)
        except Exception as e:
            print(f"Error getting signal performance: {e}")
            return {}

    def _get_signal_performance_sync(self, signal_type: Optional[str], days: int) -> Dict:
        """Synchronous version of get_signal_performance"""
        conn = sqlite3.connect(self.db_path)

        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        if signal_type:
            query = """
                SELECT * FROM signal_performance
                WHERE signal = ? AND signal_date >= ? AND return_pct IS NOT NULL
            """
            params = (signal_type, cutoff_date)
        else:
            query = """
                SELECT * FROM signal_performance
                WHERE signal_date >= ? AND return_pct IS NOT NULL
            """
            params = (cutoff_date,)

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()

        if df.empty:
            return {
                "total_signals": 0,
                "message": "No completed signals found in this period"
            }

        total_signals = len(df)
        winning_signals = len(df[df['return_pct'] > 0])
        win_rate = winning_signals / total_signals if total_signals > 0 else 0

        avg_return = df['return_pct'].mean()
        median_return = df['return_pct'].median()
        best_return = df['return_pct'].max()
        worst_return = df['return_pct'].min()
        avg_days_held = df['days_held'].mean()

        return {
            "total_signals": total_signals,
            "winning_signals": winning_signals,
            "losing_signals": total_signals - winning_signals,
            "win_rate": float(win_rate),
            "avg_return_pct": float(avg_return),
            "median_return_pct": float(median_return),
            "best_return_pct": float(best_return),
            "worst_return_pct": float(worst_return),
            "avg_days_held": float(avg_days_held),
            "signal_type": signal_type or "ALL"
        }

    async def get_all_tickers_history(self, limit: int = 100) -> List[str]:
        """Get list of tickers with historical data"""
        try:
            return await asyncio.to_thread(self._get_all_tickers_history_sync, limit)
        except Exception as e:
            print(f"Error getting tickers: {e}")
            return []

    def _get_all_tickers_history_sync(self, limit: int) -> List[str]:
        """Synchronous version of get_all_tickers_history"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT ticker FROM stock_history
            ORDER BY ticker ASC
            LIMIT ?
        """, (limit,))

        tickers = [row[0] for row in cursor.fetchall()]
        conn.close()

        return tickers
