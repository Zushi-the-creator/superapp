"""
ATLAS Learning Engine Module
==============================

Continuous improvement using Thompson Sampling and
exponential decay weighting.

Learning Cycle:
1. Record every trade outcome
2. Update regime-specific win rates
3. Adjust parameters via Thompson Sampling
4. Apply exponential decay (recent trades weighted more)

Academic References:
- Thompson Sampling: Bayesian exploration/exploitation
- Exponential Decay: Recent performance matters more
"""

import random
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .database import ATLASDatabase, TradeRecord
from .regime import MarketRegime


@dataclass
class ParameterUpdate:
    """Result of parameter update"""
    regime: str
    param_name: str
    old_value: float
    new_value: float
    confidence: float
    samples: int
    reason: str


class LearningEngine:
    """
    Thompson Sampling-based continuous improvement.

    Features:
    - Bayesian parameter exploration
    - Exponential decay weighting
    - Regime-specific learning
    - Win rate tracking
    """

    # Learning configuration
    DECAY_FACTOR = 0.95  # Recent trades weighted more
    MIN_SAMPLES_FOR_UPDATE = 10  # Need at least 10 trades
    EXPLORATION_RATE = 0.1  # 10% exploration

    # Parameter bounds
    PARAM_BOUNDS = {
        "rsi2_buy": (5, 35),
        "rsi2_sell": (80, 98),
        "stop_loss_pct": (3, 10),
        "profit_target_pct": (3, 20),
        "trailing_stop_pct": (5, 15),
    }

    def __init__(self, db: ATLASDatabase):
        """
        Initialize learning engine.

        Args:
            db: ATLASDatabase instance
        """
        self.db = db

    def record_trade(self, trade: TradeRecord) -> int:
        """
        Record a trade for learning.

        Args:
            trade: TradeRecord to record

        Returns:
            Trade ID
        """
        trade_id = self.db.insert_trade(trade)

        # If trade is complete, trigger learning
        if trade.was_correct is not None:
            self._update_regime_stats(trade.regime)

        return trade_id

    def close_trade(
        self,
        trade_id: int,
        exit_date: str,
        exit_price: float,
        exit_reason: str = None
    ):
        """
        Close a trade and update learning.

        Args:
            trade_id: ID of trade to close
            exit_date: Exit date
            exit_price: Exit price
            exit_reason: Reason for exit
        """
        self.db.update_trade_exit(trade_id, exit_date, exit_price, exit_reason)

        # Get trade to find regime
        trades = self.db.get_recent_trades(limit=1)
        if trades:
            self._update_regime_stats(trades[0].get("regime", "SIDEWAYS"))

    def _update_regime_stats(self, regime: str):
        """
        Update performance stats for a regime.

        Args:
            regime: Regime name
        """
        # Get recent trades for this regime
        recent = self.db.get_recent_trades(limit=30, regime=regime)

        if len(recent) < self.MIN_SAMPLES_FOR_UPDATE:
            return

        # Calculate weighted win rate
        wins = 0
        total_weight = 0

        for i, trade in enumerate(recent):
            weight = self.DECAY_FACTOR ** i  # Exponential decay
            total_weight += weight
            if trade.get("was_correct"):
                wins += weight

        weighted_win_rate = (wins / total_weight * 100) if total_weight > 0 else 50

        # Calculate average return
        avg_return = sum(t.get("return_pct", 0) or 0 for t in recent) / len(recent)
        avg_hold = sum(t.get("holding_days", 7) or 7 for t in recent) / len(recent)

        # Record performance snapshot
        self.db.record_regime_performance(
            regime=regime,
            total_trades=len(recent),
            wins=int(sum(1 for t in recent if t.get("was_correct"))),
            avg_return=avg_return,
            avg_holding_days=avg_hold
        )

    def get_regime_win_rate(self, regime: str, lookback: int = 30) -> float:
        """
        Get weighted win rate for a regime.

        Args:
            regime: Regime name
            lookback: Number of trades to consider

        Returns:
            Weighted win rate (0-100)
        """
        recent = self.db.get_recent_trades(limit=lookback, regime=regime)

        if not recent:
            return 65.0  # Default assumption

        wins = 0
        total_weight = 0

        for i, trade in enumerate(recent):
            weight = self.DECAY_FACTOR ** i
            total_weight += weight
            if trade.get("was_correct"):
                wins += weight

        return (wins / total_weight * 100) if total_weight > 0 else 65.0

    def update_parameters(self, regime: str) -> List[ParameterUpdate]:
        """
        Update parameters for a regime using Thompson Sampling.

        Args:
            regime: Regime name

        Returns:
            List of parameter updates made
        """
        recent = self.db.get_recent_trades(limit=30, regime=regime)

        if len(recent) < self.MIN_SAMPLES_FOR_UPDATE:
            return []

        # Calculate current performance
        wins = sum(1 for t in recent if t.get("was_correct"))
        losses = len(recent) - wins
        win_rate = wins / len(recent) if recent else 0.5

        updates = []

        # Get current parameters
        current_params = self.db.get_parameters(regime)

        for param_name, (min_val, max_val) in self.PARAM_BOUNDS.items():
            current_value = current_params.get(param_name)
            if current_value is None:
                continue

            # Thompson Sampling: sample from Beta distribution
            # Beta(wins + 1, losses + 1)
            alpha = wins + 1
            beta = losses + 1

            # Sample or exploit
            if random.random() < self.EXPLORATION_RATE:
                # Exploration: random perturbation
                sampled_rate = random.betavariate(alpha, beta)
            else:
                # Exploitation: use mean with small noise
                mean_rate = alpha / (alpha + beta)
                noise = random.gauss(0, 0.02)
                sampled_rate = max(0, min(1, mean_rate + noise))

            # Calculate adjustment
            new_value = self._calculate_new_value(
                param_name, current_value, sampled_rate, win_rate,
                min_val, max_val
            )

            if new_value != current_value:
                # Update parameter
                confidence = min(0.95, len(recent) / 100)
                self.db.update_parameter(
                    regime=regime,
                    param_name=param_name,
                    param_value=new_value,
                    confidence=confidence,
                    samples=len(recent)
                )

                updates.append(ParameterUpdate(
                    regime=regime,
                    param_name=param_name,
                    old_value=current_value,
                    new_value=new_value,
                    confidence=confidence,
                    samples=len(recent),
                    reason=f"Win rate {win_rate*100:.1f}%, sampled {sampled_rate:.3f}"
                ))

        return updates

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
        Calculate new parameter value based on sampled rate.

        Args:
            param_name: Parameter name
            current_value: Current parameter value
            sampled_rate: Thompson-sampled rate
            win_rate: Current win rate
            min_val: Minimum allowed value
            max_val: Maximum allowed value

        Returns:
            New parameter value
        """
        # Determine exploration scale based on win rate
        if win_rate < 0.60:
            scale = 0.20  # High exploration when losing
        elif win_rate < 0.75:
            scale = 0.10  # Medium
        else:
            scale = 0.05  # Low - mostly exploit when winning

        # Calculate adjustment based on sampled rate vs baseline
        baseline = 0.65  # Target win rate
        adjustment_direction = 1 if sampled_rate > baseline else -1

        # Different parameters adjust differently
        if param_name == "rsi2_buy":
            # Higher sampled rate = can be more aggressive (higher threshold)
            adjustment = adjustment_direction * scale * 5  # RSI units
        elif param_name == "rsi2_sell":
            # Higher sampled rate = can wait longer to sell
            adjustment = adjustment_direction * scale * 3
        elif param_name in ["stop_loss_pct", "trailing_stop_pct"]:
            # Higher sampled rate = can use tighter stops
            adjustment = -adjustment_direction * scale * 1.5
        elif param_name == "profit_target_pct":
            # Higher sampled rate = can aim for larger targets
            adjustment = adjustment_direction * scale * 2
        else:
            adjustment = 0

        new_value = current_value + adjustment
        return round(max(min_val, min(max_val, new_value)), 1)

    def get_best_parameters(self, regime: str) -> Dict[str, float]:
        """
        Get best parameters for a regime.

        Args:
            regime: Regime name

        Returns:
            Dict of parameter name to value
        """
        params = self.db.get_parameters(regime)

        if not params:
            # Return defaults
            from .regime import RegimeDetector
            return RegimeDetector.REGIME_PARAMS.get(
                MarketRegime[regime],
                RegimeDetector.REGIME_PARAMS[MarketRegime.SIDEWAYS]
            )

        return params

    def should_retrain(self, regime: str, threshold_trades: int = 20) -> bool:
        """
        Check if we should update parameters.

        Args:
            regime: Regime name
            threshold_trades: Trades since last update

        Returns:
            True if should retrain
        """
        history = self.db.get_regime_performance_history(regime, limit=1)

        if not history:
            return True  # Never trained

        # Check trades since last update
        stats = self.db.get_regime_stats(regime, lookback_trades=100)
        if stats["total_trades"] >= threshold_trades:
            return True

        return False

    def get_learning_summary(self) -> Dict:
        """
        Get summary of learning state.

        Returns:
            Dict with learning metrics per regime
        """
        summary = {}

        for regime in ["BULL", "BEAR", "SIDEWAYS", "HIGH_VOL"]:
            stats = self.db.get_regime_stats(regime)
            params = self.db.get_parameters(regime)
            history = self.db.get_regime_performance_history(regime, limit=5)

            summary[regime] = {
                "current_stats": stats,
                "parameters": params,
                "performance_trend": [
                    {"date": h["window_end"], "win_rate": h["win_rate"]}
                    for h in history
                ] if history else [],
            }

        return summary

    def run_learning_cycle(self) -> Dict:
        """
        Run full learning cycle for all regimes.

        Returns:
            Dict with updates made
        """
        all_updates = {}

        for regime in ["BULL", "BEAR", "SIDEWAYS", "HIGH_VOL"]:
            if self.should_retrain(regime):
                updates = self.update_parameters(regime)
                if updates:
                    all_updates[regime] = [
                        {
                            "param": u.param_name,
                            "old": u.old_value,
                            "new": u.new_value,
                            "reason": u.reason
                        }
                        for u in updates
                    ]

        return all_updates
