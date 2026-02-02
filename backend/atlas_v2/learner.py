"""
Thompson Sampling Learner Module
================================

Based on research:
- arXiv 2024 (2403.00540): Epsilon-Greedy Thompson Sampling
- Stanford Tutorial: Thompson Sampling for bandit problems
- arXiv 2024 (2411.17071): Fast, Precise Thompson Sampling

Thompson Sampling:
- Bayesian approach to exploration/exploitation
- Maintains Beta distribution for each parameter
- Samples from posterior to decide actions
- Naturally balances trying new things vs using what works

Key improvement: ε-greedy policy (10% exploration)
- When losing: explore more (try different thresholds)
- When winning: exploit (stick with what works)

Exponential Decay:
- Recent trades weighted more heavily
- Decay factor: 0.95 (most recent trade = 1.0, 10th trade = 0.60)
"""

import random
import math
import json
import sqlite3
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from .regime import MarketRegime


@dataclass
class TradeOutcome:
    """Record of a single trade"""
    ticker: str
    regime: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float
    win: bool
    days_held: int
    rsi2_at_entry: float
    exit_reason: str


@dataclass
class ParameterState:
    """Bayesian state for a parameter"""
    name: str
    regime: str
    alpha: float  # Wins + 1 (Beta distribution)
    beta: float   # Losses + 1 (Beta distribution)
    current_value: float
    min_value: float
    max_value: float
    samples: int
    last_updated: str


class ThompsonSamplingLearner:
    """
    Continuous learning via Thompson Sampling.

    After each trade:
    1. Record outcome
    2. Update Beta distribution (alpha/beta)
    3. Sample new parameters for next trade
    4. Apply exponential decay to weight recent trades more

    Key Parameters Optimized:
    - RSI threshold (entry)
    - Profit target %
    - Stop loss %
    - Max holding days
    """

    DECAY_FACTOR = 0.95  # Weight decay per trade
    EXPLORATION_RATE = 0.10  # 10% exploration
    MIN_SAMPLES_FOR_UPDATE = 5  # Minimum trades before adjusting

    # Parameter bounds
    PARAM_BOUNDS = {
        'rsi_threshold': (5, 30),
        'profit_target_pct': (3, 15),
        'stop_loss_pct': (3, 12),
        'max_days': (3, 14),
    }

    def __init__(self, db_path: str = None):
        """
        Initialize learner with SQLite database.

        Args:
            db_path: Path to database (default: atlas_v2_learning.db)
        """
        if db_path is None:
            db_path = Path(__file__).parent / "atlas_v2_learning.db"
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Trades table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                regime TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_date TEXT,
                exit_price REAL,
                return_pct REAL,
                win INTEGER,
                days_held INTEGER,
                rsi2_at_entry REAL,
                exit_reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Parameters table (Bayesian state)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS parameters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                regime TEXT NOT NULL,
                param_name TEXT NOT NULL,
                alpha REAL NOT NULL DEFAULT 1,
                beta REAL NOT NULL DEFAULT 1,
                current_value REAL NOT NULL,
                min_value REAL NOT NULL,
                max_value REAL NOT NULL,
                samples INTEGER DEFAULT 0,
                last_updated TEXT,
                UNIQUE(regime, param_name)
            )
        """)

        # Performance snapshots
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS performance_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                regime TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                total_trades INTEGER,
                win_rate REAL,
                avg_return REAL,
                weighted_win_rate REAL
            )
        """)

        conn.commit()
        conn.close()

        # Initialize default parameters if not exist
        self._init_default_params()

    def _init_default_params(self):
        """Initialize default parameters for each regime"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        defaults = {
            'BULL': {'rsi_threshold': 25, 'profit_target_pct': 10, 'stop_loss_pct': 8, 'max_days': 10},
            'BEAR': {'rsi_threshold': 5, 'profit_target_pct': 5, 'stop_loss_pct': 4, 'max_days': 5},
            'SIDEWAYS': {'rsi_threshold': 15, 'profit_target_pct': 7, 'stop_loss_pct': 5, 'max_days': 7},
            'HIGH_VOL': {'rsi_threshold': 10, 'profit_target_pct': 12, 'stop_loss_pct': 10, 'max_days': 7},
        }

        for regime, params in defaults.items():
            for param_name, value in params.items():
                min_val, max_val = self.PARAM_BOUNDS[param_name]
                cursor.execute("""
                    INSERT OR IGNORE INTO parameters
                    (regime, param_name, alpha, beta, current_value, min_value, max_value, samples, last_updated)
                    VALUES (?, ?, 1, 1, ?, ?, ?, 0, ?)
                """, (regime, param_name, value, min_val, max_val, datetime.now().isoformat()))

        conn.commit()
        conn.close()

    def record_trade(self, outcome: TradeOutcome) -> int:
        """
        Record a trade outcome and trigger learning.

        Args:
            outcome: TradeOutcome with all details

        Returns:
            Trade ID
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO trades
            (ticker, regime, entry_date, entry_price, exit_date, exit_price,
             return_pct, win, days_held, rsi2_at_entry, exit_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            outcome.ticker, outcome.regime, outcome.entry_date, outcome.entry_price,
            outcome.exit_date, outcome.exit_price, outcome.return_pct,
            1 if outcome.win else 0, outcome.days_held, outcome.rsi2_at_entry,
            outcome.exit_reason
        ))

        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Trigger learning update
        self._update_parameters(outcome.regime)

        return trade_id

    def _update_parameters(self, regime: str):
        """
        Update parameters using Thompson Sampling with exponential decay.

        Args:
            regime: Market regime to update
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get recent trades for this regime
        cursor.execute("""
            SELECT win, return_pct, rsi2_at_entry, days_held
            FROM trades
            WHERE regime = ?
            ORDER BY created_at DESC
            LIMIT 30
        """, (regime,))

        trades = cursor.fetchall()

        if len(trades) < self.MIN_SAMPLES_FOR_UPDATE:
            conn.close()
            return

        # Calculate weighted wins/losses with exponential decay
        weighted_wins = 0
        weighted_losses = 0

        for i, (win, return_pct, rsi2, days) in enumerate(trades):
            weight = self.DECAY_FACTOR ** i  # More recent = higher weight
            if win:
                weighted_wins += weight
            else:
                weighted_losses += weight

        # Update Beta distribution parameters
        for param_name in self.PARAM_BOUNDS.keys():
            cursor.execute("""
                SELECT alpha, beta, current_value, min_value, max_value
                FROM parameters
                WHERE regime = ? AND param_name = ?
            """, (regime, param_name))

            row = cursor.fetchone()
            if not row:
                continue

            old_alpha, old_beta, current_value, min_val, max_val = row

            # Update alpha/beta (Bayesian update)
            new_alpha = old_alpha + weighted_wins
            new_beta = old_beta + weighted_losses

            # Thompson Sampling: sample from Beta distribution
            if random.random() < self.EXPLORATION_RATE:
                # Exploration: sample from full Beta
                sampled_rate = random.betavariate(new_alpha, new_beta)
            else:
                # Exploitation: use mean with small noise
                mean_rate = new_alpha / (new_alpha + new_beta)
                noise = random.gauss(0, 0.02)
                sampled_rate = max(0.01, min(0.99, mean_rate + noise))

            # Calculate new parameter value
            new_value = self._calculate_new_value(
                param_name, current_value, sampled_rate,
                weighted_wins / (weighted_wins + weighted_losses),
                min_val, max_val
            )

            # Update database
            cursor.execute("""
                UPDATE parameters
                SET alpha = ?, beta = ?, current_value = ?, samples = samples + 1, last_updated = ?
                WHERE regime = ? AND param_name = ?
            """, (new_alpha, new_beta, new_value, datetime.now().isoformat(), regime, param_name))

        # Record performance snapshot
        win_rate = weighted_wins / (weighted_wins + weighted_losses) * 100
        avg_return = sum(t[1] for t in trades) / len(trades)

        cursor.execute("""
            INSERT INTO performance_snapshots
            (regime, snapshot_date, total_trades, win_rate, avg_return, weighted_win_rate)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (regime, datetime.now().isoformat(), len(trades), win_rate, avg_return, win_rate))

        conn.commit()
        conn.close()

    def _calculate_new_value(
        self,
        param_name: str,
        current_value: float,
        sampled_rate: float,
        win_rate: float,
        min_val: float,
        max_val: float
    ) -> float:
        """
        Calculate new parameter value based on Thompson sample.

        Key insight: Adjust parameters based on whether we're winning or losing.
        - Winning: Small adjustments (exploit)
        - Losing: Larger adjustments (explore)
        """
        # Scale of adjustment based on win rate
        if win_rate < 0.55:
            scale = 0.15  # Large exploration when losing
        elif win_rate < 0.65:
            scale = 0.10  # Medium
        elif win_rate < 0.75:
            scale = 0.05  # Small
        else:
            scale = 0.02  # Tiny - mostly exploit when winning

        # Direction based on sampled rate vs baseline
        baseline = 0.65  # Target win rate
        direction = 1 if sampled_rate > baseline else -1

        # Parameter-specific adjustments
        if param_name == 'rsi_threshold':
            # Higher sampled rate = can be more aggressive (higher threshold)
            adjustment = direction * scale * 5
        elif param_name == 'profit_target_pct':
            # Higher sampled rate = can aim for larger targets
            adjustment = direction * scale * 2
        elif param_name == 'stop_loss_pct':
            # Higher sampled rate = can use tighter stops
            adjustment = -direction * scale * 1.5
        elif param_name == 'max_days':
            # Higher sampled rate = can hold longer
            adjustment = direction * scale * 2
        else:
            adjustment = 0

        new_value = current_value + adjustment
        return round(max(min_val, min(max_val, new_value)), 1)

    def get_learned_params(self, regime: str) -> dict:
        """
        Get current learned parameters for a regime.

        Args:
            regime: Market regime

        Returns:
            dict of parameter name to value
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT param_name, current_value
            FROM parameters
            WHERE regime = ?
        """, (regime,))

        params = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()

        return params

    def get_learning_summary(self) -> dict:
        """
        Get summary of learning state across all regimes.

        Returns:
            dict with stats per regime
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        summary = {}

        for regime in ['BULL', 'BEAR', 'SIDEWAYS', 'HIGH_VOL']:
            # Get current parameters
            cursor.execute("""
                SELECT param_name, current_value, alpha, beta, samples
                FROM parameters
                WHERE regime = ?
            """, (regime,))

            params = {}
            total_samples = 0
            for row in cursor.fetchall():
                param_name, value, alpha, beta, samples = row
                win_rate = alpha / (alpha + beta) * 100
                params[param_name] = {
                    'value': value,
                    'estimated_win_rate': round(win_rate, 1),
                    'samples': samples
                }
                total_samples = max(total_samples, samples)

            # Get recent performance
            cursor.execute("""
                SELECT win_rate, avg_return
                FROM performance_snapshots
                WHERE regime = ?
                ORDER BY snapshot_date DESC
                LIMIT 1
            """, (regime,))

            perf = cursor.fetchone()

            summary[regime] = {
                'parameters': params,
                'total_samples': total_samples,
                'recent_win_rate': perf[0] if perf else None,
                'recent_avg_return': perf[1] if perf else None,
            }

        conn.close()
        return summary

    def get_regime_confidence(self, regime: str) -> float:
        """
        Get confidence level for a regime based on sample size.

        Returns:
            Confidence 0-100 (more samples = higher confidence)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM trades
            WHERE regime = ?
        """, (regime,))

        count = cursor.fetchone()[0]
        conn.close()

        # Confidence formula: asymptotic to 100 as samples increase
        # 10 trades = 50%, 30 trades = 75%, 50 trades = 85%, 100 trades = 95%
        confidence = 100 * (1 - math.exp(-count / 30))
        return round(confidence, 1)
