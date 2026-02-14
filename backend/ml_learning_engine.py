#!/usr/bin/env python3
"""
ML Learning Engine - Continuous Model Improvement

Based on research:
- Ensemble RL with dynamic policy weighting (arxiv 2507.18680)
- Hybrid approach combining domain knowledge + adaptive learning (42% adoption in 2025)
- Thompson Sampling for exploration/exploitation balance
- Regime detection for market adaptation

Key Features:
1. Performance tracking with exponential decay (recent performance weighted more)
2. Bayesian-inspired parameter optimization
3. Ensemble model weighting based on rolling performance
4. Market regime detection and adaptation
5. Persistent learning state (SQLite)
"""

import sqlite3
import json
import math
import random
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class ModelPerformance:
    """Track a single model's performance metrics"""
    model_name: str
    total_signals: int
    correct_signals: int
    win_rate: float
    avg_return: float
    last_updated: str
    decay_weight: float  # Exponentially decayed weight


@dataclass
class SignalOutcome:
    """Record of a signal and its outcome"""
    ticker: str
    model_name: str
    signal: str
    entry_price: float
    entry_date: str
    exit_price: Optional[float]
    exit_date: Optional[str]
    return_pct: Optional[float]
    was_correct: Optional[bool]


@dataclass
class ModelParameters:
    """Tunable parameters for each model"""
    model_name: str
    rsi_oversold: float  # RSI threshold for buy
    rsi_overbought: float  # RSI threshold for sell
    trend_filter_period: int  # SMA period for trend
    volume_threshold: float  # Volume spike multiplier
    confluence_required: int  # Minimum factors needed
    updated_at: str


class MLLearningEngine:
    """
    Machine Learning Engine for Continuous Model Improvement

    Uses:
    1. Thompson Sampling for parameter exploration
    2. Exponential decay for recent performance weighting
    3. Ensemble weighting based on rolling win rate
    4. Market regime detection
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = Path(__file__).parent / "data" / "ml_learning.db"
        self.db_path = str(db_path)
        Path(db_path).parent.mkdir(exist_ok=True)
        self._init_database()

        # Decay factor for exponential weighting (0.95 = 5% decay per period)
        self.decay_factor = 0.95

        # Thompson Sampling parameters
        self.exploration_rate = 0.1

        # Default parameter ranges for optimization
        self.param_ranges = {
            "rsi_oversold": (3, 30),
            "rsi_overbought": (70, 97),
            "trend_filter_period": (50, 200),
            "volume_threshold": (1.1, 2.0),
            "confluence_required": (2, 5)
        }

    def _init_database(self):
        """Initialize SQLite database for learning state"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Model performance tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS model_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name TEXT NOT NULL,
                ticker TEXT,
                win_rate REAL,
                total_signals INTEGER,
                correct_signals INTEGER,
                avg_return REAL,
                period_start TEXT,
                period_end TEXT,
                decay_weight REAL DEFAULT 1.0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Signal outcomes for learning
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signal_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                model_name TEXT NOT NULL,
                signal TEXT NOT NULL,
                entry_price REAL,
                entry_date TEXT,
                exit_price REAL,
                exit_date TEXT,
                return_pct REAL,
                was_correct INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Model parameters (optimized over time)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS model_parameters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name TEXT NOT NULL,
                ticker TEXT,
                param_name TEXT NOT NULL,
                param_value REAL NOT NULL,
                performance_score REAL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(model_name, ticker, param_name)
            )
        ''')

        # Market regime history
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_regimes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                regime TEXT NOT NULL,
                vix_level REAL,
                spy_trend TEXT,
                best_model TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Ensemble weights
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ensemble_weights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name TEXT NOT NULL,
                ticker TEXT,
                weight REAL NOT NULL,
                reason TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(model_name, ticker)
            )
        ''')

        conn.commit()
        conn.close()

    # ============================================================
    # PERFORMANCE TRACKING
    # ============================================================

    def record_signal(self, ticker: str, model_name: str, signal: str,
                      entry_price: float, entry_date: str):
        """Record a new signal for tracking"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO signal_outcomes
            (ticker, model_name, signal, entry_price, entry_date)
            VALUES (?, ?, ?, ?, ?)
        ''', (ticker, model_name, signal, entry_price, entry_date))

        conn.commit()
        conn.close()
        return cursor.lastrowid

    def update_signal_outcome(self, signal_id: int, exit_price: float, exit_date: str):
        """Update a signal with its outcome"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get original signal
        cursor.execute('SELECT signal, entry_price FROM signal_outcomes WHERE id = ?', (signal_id,))
        row = cursor.fetchone()

        if row:
            signal, entry_price = row
            return_pct = ((exit_price - entry_price) / entry_price) * 100

            # Determine if signal was correct
            if signal == "BUY":
                was_correct = return_pct > 0
            elif signal == "SELL":
                was_correct = return_pct < 0
            else:
                was_correct = abs(return_pct) < 5

            cursor.execute('''
                UPDATE signal_outcomes
                SET exit_price = ?, exit_date = ?, return_pct = ?, was_correct = ?
                WHERE id = ?
            ''', (exit_price, exit_date, return_pct, int(was_correct), signal_id))

            conn.commit()

        conn.close()

    def get_model_win_rate(self, model_name: str, ticker: str = None,
                           days: int = 90) -> Dict:
        """Get win rate for a model with exponential decay weighting"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        if ticker:
            cursor.execute('''
                SELECT was_correct, return_pct, entry_date
                FROM signal_outcomes
                WHERE model_name = ? AND ticker = ?
                AND entry_date >= ? AND was_correct IS NOT NULL
                ORDER BY entry_date DESC
            ''', (model_name, ticker, cutoff))
        else:
            cursor.execute('''
                SELECT was_correct, return_pct, entry_date
                FROM signal_outcomes
                WHERE model_name = ?
                AND entry_date >= ? AND was_correct IS NOT NULL
                ORDER BY entry_date DESC
            ''', (model_name, cutoff))

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return {"win_rate": 50.0, "weighted_win_rate": 50.0, "signals": 0}

        # Calculate exponentially weighted win rate
        total_weight = 0
        weighted_correct = 0
        simple_correct = 0

        for i, (correct, return_pct, entry_date) in enumerate(rows):
            # More recent signals get higher weight
            weight = self.decay_factor ** i
            total_weight += weight

            if correct:
                weighted_correct += weight
                simple_correct += 1

        weighted_win_rate = (weighted_correct / total_weight * 100) if total_weight > 0 else 50.0
        simple_win_rate = (simple_correct / len(rows) * 100) if rows else 50.0

        return {
            "win_rate": round(simple_win_rate, 1),
            "weighted_win_rate": round(weighted_win_rate, 1),
            "signals": len(rows),
            "recent_signals": len([r for r in rows[:10]])
        }

    # ============================================================
    # ENSEMBLE WEIGHTING
    # ============================================================

    def calculate_ensemble_weights(self, ticker: str = None) -> Dict[str, float]:
        """
        Calculate ensemble weights for each model based on recent performance.

        Uses Thompson Sampling-inspired approach:
        - Models with higher win rates get higher weights
        - Some exploration for less-used models
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get all unique models
        if ticker:
            cursor.execute('''
                SELECT DISTINCT model_name FROM signal_outcomes WHERE ticker = ?
            ''', (ticker,))
        else:
            cursor.execute('SELECT DISTINCT model_name FROM signal_outcomes')

        models = [row[0] for row in cursor.fetchall()]
        conn.close()

        if not models:
            # Default weights if no data
            return {
                "V15.0 Connors RSI(2)": 0.2,
                "V16.0 Multi-Confluence": 0.25,
                "V17.0 Extreme Oversold": 0.25,
                "V18.0 Triple Confirmation": 0.2,
                "V19.0 Consecutive Days": 0.1
            }

        # Get performance for each model
        performances = {}
        for model in models:
            perf = self.get_model_win_rate(model, ticker)
            performances[model] = perf

        # Thompson Sampling: Sample from Beta distribution
        # Beta(wins + 1, losses + 1)
        weights = {}
        for model, perf in performances.items():
            signals = perf.get("signals", 0)
            win_rate = perf.get("weighted_win_rate", 50) / 100

            wins = int(signals * win_rate)
            losses = signals - wins

            # Sample from Beta distribution (approximation using mean + noise)
            alpha = wins + 1
            beta = losses + 1

            # Thompson sample (simplified)
            if random.random() < self.exploration_rate:
                # Exploration: random weight
                sample = random.random()
            else:
                # Exploitation: use mean of Beta distribution with small noise
                mean = alpha / (alpha + beta)
                noise = random.gauss(0, 0.05)
                sample = max(0.1, min(0.9, mean + noise))

            weights[model] = sample

        # Normalize weights to sum to 1
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        # Save weights
        self._save_ensemble_weights(weights, ticker)

        return weights

    def _save_ensemble_weights(self, weights: Dict[str, float], ticker: str = None):
        """Save ensemble weights to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for model, weight in weights.items():
            cursor.execute('''
                INSERT INTO ensemble_weights (model_name, ticker, weight, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(model_name, ticker) DO UPDATE SET
                weight = ?, updated_at = ?
            ''', (model, ticker, weight, datetime.now().isoformat(),
                  weight, datetime.now().isoformat()))

        conn.commit()
        conn.close()

    # ============================================================
    # PARAMETER OPTIMIZATION
    # ============================================================

    def optimize_parameters(self, model_name: str, ticker: str,
                            current_params: Dict, current_win_rate: float) -> Dict:
        """
        Bayesian-inspired parameter optimization.

        Uses recent performance to adjust parameters:
        - If win rate < 60%: explore more (wider parameter changes)
        - If win rate > 75%: exploit (small refinements)
        """
        optimized = current_params.copy()

        # Exploration vs exploitation based on performance
        if current_win_rate < 60:
            # High exploration: make larger changes
            adjustment_scale = 0.2
        elif current_win_rate < 75:
            # Medium exploration
            adjustment_scale = 0.1
        else:
            # Low exploration: small refinements
            adjustment_scale = 0.05

        # Adjust each parameter
        for param, value in optimized.items():
            if param not in self.param_ranges:
                continue

            min_val, max_val = self.param_ranges[param]
            param_range = max_val - min_val

            # Random adjustment within scale
            adjustment = random.gauss(0, param_range * adjustment_scale)
            new_value = value + adjustment

            # Clamp to valid range
            new_value = max(min_val, min(max_val, new_value))

            # Round appropriately
            if param in ["confluence_required", "trend_filter_period"]:
                new_value = int(round(new_value))
            else:
                new_value = round(new_value, 2)

            optimized[param] = new_value

        # Save optimized parameters
        self._save_parameters(model_name, ticker, optimized, current_win_rate)

        return optimized

    def get_best_parameters(self, model_name: str, ticker: str = None) -> Dict:
        """Get the best performing parameters for a model"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if ticker:
            cursor.execute('''
                SELECT param_name, param_value
                FROM model_parameters
                WHERE model_name = ? AND ticker = ?
                ORDER BY performance_score DESC
            ''', (model_name, ticker))
        else:
            cursor.execute('''
                SELECT param_name, param_value
                FROM model_parameters
                WHERE model_name = ? AND ticker IS NULL
                ORDER BY performance_score DESC
            ''', (model_name,))

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            # Return defaults
            return {
                "rsi_oversold": 10,
                "rsi_overbought": 90,
                "trend_filter_period": 200,
                "volume_threshold": 1.5,
                "confluence_required": 3
            }

        return {row[0]: row[1] for row in rows}

    def _save_parameters(self, model_name: str, ticker: str,
                         params: Dict, performance_score: float):
        """Save optimized parameters"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for param_name, param_value in params.items():
            cursor.execute('''
                INSERT INTO model_parameters
                (model_name, ticker, param_name, param_value, performance_score, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_name, ticker, param_name) DO UPDATE SET
                param_value = ?, performance_score = ?, updated_at = ?
            ''', (model_name, ticker, param_name, param_value, performance_score,
                  datetime.now().isoformat(),
                  param_value, performance_score, datetime.now().isoformat()))

        conn.commit()
        conn.close()

    # ============================================================
    # MARKET REGIME DETECTION
    # ============================================================

    def detect_regime(self, spy_closes: List[float], vix_level: float = None) -> str:
        """
        Detect current market regime.

        Regimes:
        - BULL: SPY > SMA50 > SMA200, VIX < 20
        - BEAR: SPY < SMA50 < SMA200, VIX > 25
        - HIGH_VOL: VIX > 30
        - NEUTRAL: Mixed signals
        """
        if len(spy_closes) < 200:
            return "UNKNOWN"

        price = spy_closes[-1]
        sma50 = sum(spy_closes[-50:]) / 50
        sma200 = sum(spy_closes[-200:]) / 200

        # Determine regime
        if vix_level and vix_level > 30:
            regime = "HIGH_VOL"
        elif price > sma50 > sma200:
            if vix_level and vix_level < 15:
                regime = "STRONG_BULL"
            else:
                regime = "BULL"
        elif price < sma50 < sma200:
            regime = "BEAR"
        else:
            regime = "NEUTRAL"

        # Save regime
        self._save_regime(regime, vix_level, "BULL" if price > sma200 else "BEAR")

        return regime

    def get_best_model_for_regime(self, regime: str) -> str:
        """Get historically best performing model for current regime"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT best_model, COUNT(*) as cnt
            FROM market_regimes
            WHERE regime = ?
            GROUP BY best_model
            ORDER BY cnt DESC
            LIMIT 1
        ''', (regime,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return row[0]

        # Defaults by regime
        regime_defaults = {
            "STRONG_BULL": "V15.0 Connors RSI(2)",
            "BULL": "V16.0 Multi-Confluence",
            "NEUTRAL": "V18.0 Triple Confirmation",
            "BEAR": "V17.0 Extreme Oversold",
            "HIGH_VOL": "V19.0 Consecutive Days"
        }

        return regime_defaults.get(regime, "V16.0 Multi-Confluence")

    def _save_regime(self, regime: str, vix_level: float, spy_trend: str):
        """Save market regime detection"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO market_regimes (date, regime, vix_level, spy_trend)
            VALUES (?, ?, ?, ?)
        ''', (datetime.now().strftime('%Y-%m-%d'), regime, vix_level, spy_trend))

        conn.commit()
        conn.close()

    # ============================================================
    # LEARNING SUMMARY
    # ============================================================

    def get_learning_summary(self) -> Dict:
        """Get summary of all learning data"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Total signals
        cursor.execute('SELECT COUNT(*) FROM signal_outcomes')
        total_signals = cursor.fetchone()[0]

        # Completed signals (with outcome)
        cursor.execute('SELECT COUNT(*) FROM signal_outcomes WHERE was_correct IS NOT NULL')
        completed_signals = cursor.fetchone()[0]

        # Overall win rate
        cursor.execute('''
            SELECT SUM(was_correct), COUNT(*)
            FROM signal_outcomes
            WHERE was_correct IS NOT NULL
        ''')
        row = cursor.fetchone()
        if row[1] > 0:
            overall_win_rate = (row[0] / row[1]) * 100
        else:
            overall_win_rate = 0

        # Best performing model
        cursor.execute('''
            SELECT model_name,
                   SUM(was_correct) * 1.0 / COUNT(*) as win_rate,
                   COUNT(*) as signals
            FROM signal_outcomes
            WHERE was_correct IS NOT NULL
            GROUP BY model_name
            HAVING signals >= 5
            ORDER BY win_rate DESC
            LIMIT 1
        ''')
        best_model_row = cursor.fetchone()
        best_model = {
            "name": best_model_row[0] if best_model_row else "Unknown",
            "win_rate": round(best_model_row[1] * 100, 1) if best_model_row else 0,
            "signals": best_model_row[2] if best_model_row else 0
        }

        # Current ensemble weights
        cursor.execute('''
            SELECT model_name, weight FROM ensemble_weights
            WHERE ticker IS NULL
            ORDER BY weight DESC
        ''')
        ensemble_weights = {row[0]: round(row[1], 3) for row in cursor.fetchall()}

        # Recent regime
        cursor.execute('''
            SELECT regime, date FROM market_regimes
            ORDER BY date DESC LIMIT 1
        ''')
        regime_row = cursor.fetchone()
        current_regime = regime_row[0] if regime_row else "UNKNOWN"

        conn.close()

        return {
            "total_signals_tracked": total_signals,
            "completed_signals": completed_signals,
            "overall_win_rate": round(overall_win_rate, 1),
            "best_model": best_model,
            "ensemble_weights": ensemble_weights,
            "current_regime": current_regime,
            "learning_status": "ACTIVE" if total_signals > 0 else "NO_DATA"
        }

    def run_learning_cycle(self, model_performances: Dict[str, Dict]) -> Dict:
        """
        Run a complete learning cycle.

        This should be called after each backtest to update the learning state.

        Args:
            model_performances: Dict of model_name -> {win_rate, signals, avg_return}

        Returns:
            Updated ensemble weights and parameter suggestions
        """
        results = {}

        for model_name, perf in model_performances.items():
            win_rate = perf.get("win_rate", 50)
            signals = perf.get("signals", 0)

            # Only learn from models with sufficient signals
            if signals < 5:
                continue

            # Record performance
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO model_performance
                (model_name, win_rate, total_signals, correct_signals, avg_return, period_end)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (model_name, win_rate, signals,
                  int(signals * win_rate / 100),
                  perf.get("avg_return", 0),
                  datetime.now().isoformat()))
            conn.commit()
            conn.close()

            # Get current parameters
            current_params = self.get_best_parameters(model_name)

            # Optimize if win rate < 80%
            if win_rate < 80:
                new_params = self.optimize_parameters(
                    model_name, None, current_params, win_rate
                )
                results[model_name] = {
                    "previous_win_rate": win_rate,
                    "optimized_params": new_params,
                    "action": "PARAMETERS_ADJUSTED"
                }
            else:
                results[model_name] = {
                    "win_rate": win_rate,
                    "action": "NO_CHANGE_NEEDED"
                }

        # Update ensemble weights
        new_weights = self.calculate_ensemble_weights()

        return {
            "model_updates": results,
            "new_ensemble_weights": new_weights,
            "learning_summary": self.get_learning_summary()
        }


# ============================================================
# MAIN / TESTING
# ============================================================

def main():
    """Test the ML Learning Engine"""
    print("=" * 70)
    print("ML Learning Engine - Continuous Model Improvement")
    print("=" * 70)

    engine = MLLearningEngine()

    # Simulate some signal outcomes for testing
    print("\nRecording test signals...")

    test_signals = [
        ("VST", "V15.0 Connors RSI(2)", "BUY", 165.0, "2026-01-01", 175.0, True),
        ("VST", "V15.0 Connors RSI(2)", "BUY", 170.0, "2026-01-05", 168.0, False),
        ("VST", "V16.0 Multi-Confluence", "BUY", 160.0, "2026-01-02", 172.0, True),
        ("VST", "V16.0 Multi-Confluence", "BUY", 168.0, "2026-01-06", 175.0, True),
        ("LLY", "V17.0 Extreme Oversold", "BUY", 1050.0, "2026-01-03", 1080.0, True),
        ("LLY", "V17.0 Extreme Oversold", "BUY", 1070.0, "2026-01-07", 1090.0, True),
        ("MRVL", "V18.0 Triple Confirmation", "BUY", 82.0, "2026-01-04", 80.0, False),
        ("MRVL", "V18.0 Triple Confirmation", "SELL", 85.0, "2026-01-08", 82.0, True),
    ]

    for ticker, model, signal, entry, entry_date, exit_price, correct in test_signals:
        signal_id = engine.record_signal(ticker, model, signal, entry, entry_date)
        engine.update_signal_outcome(signal_id, exit_price,
                                     (datetime.strptime(entry_date, '%Y-%m-%d') + timedelta(days=7)).strftime('%Y-%m-%d'))

    # Get learning summary
    print("\n" + "=" * 50)
    print("LEARNING SUMMARY")
    print("=" * 50)

    summary = engine.get_learning_summary()
    print(f"\nTotal signals tracked: {summary['total_signals_tracked']}")
    print(f"Completed signals: {summary['completed_signals']}")
    print(f"Overall win rate: {summary['overall_win_rate']}%")
    print(f"\nBest model: {summary['best_model']['name']}")
    print(f"  Win rate: {summary['best_model']['win_rate']}%")
    print(f"  Signals: {summary['best_model']['signals']}")

    # Calculate ensemble weights
    print("\n" + "=" * 50)
    print("ENSEMBLE WEIGHTS")
    print("=" * 50)

    weights = engine.calculate_ensemble_weights()
    for model, weight in sorted(weights.items(), key=lambda x: -x[1]):
        print(f"  {model}: {weight:.3f}")

    # Run learning cycle
    print("\n" + "=" * 50)
    print("RUNNING LEARNING CYCLE")
    print("=" * 50)

    # Simulate model performances from backtest
    performances = {
        "V15.0 Connors RSI(2)": {"win_rate": 75, "signals": 20, "avg_return": 1.5},
        "V16.0 Multi-Confluence": {"win_rate": 82, "signals": 15, "avg_return": 2.1},
        "V17.0 Extreme Oversold": {"win_rate": 88, "signals": 8, "avg_return": 2.8},
        "V18.0 Triple Confirmation": {"win_rate": 70, "signals": 12, "avg_return": 1.2},
        "V19.0 Consecutive Days": {"win_rate": 65, "signals": 10, "avg_return": 0.9},
    }

    results = engine.run_learning_cycle(performances)

    print("\nModel Updates:")
    for model, update in results["model_updates"].items():
        print(f"  {model}: {update['action']}")
        if "optimized_params" in update:
            print(f"    New params: {update['optimized_params']}")

    print(f"\nNew Ensemble Weights:")
    for model, weight in sorted(results["new_ensemble_weights"].items(), key=lambda x: -x[1]):
        print(f"  {model}: {weight:.3f}")


if __name__ == "__main__":
    main()
