"""
Exit Engine Module
==================

Based on research:
- QuantifiedStrategies: Time-based exits outperform trailing stops
- Trade Ideas: "Exits shape the outcome more than entries"
- Emini-Watch: Profit targets work better than trailing stops
- Research: Scaling out 25-50% at first target is effective

Exit Priority (in order):
1. STOP LOSS: Hard stop (regime-dependent %)
2. PROFIT TARGET: Fixed target (regime-dependent %)
3. TIME EXIT: Max holding period (regime-dependent days)
4. RSI EXIT: RSI(2) > 80 (mean reversion complete)

Key Finding: Trailing stops reduce total profits despite limiting drawdown.
We use fixed stops + time exits instead.
"""

from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

from .regime import RegimeDetector, MarketRegime


class ExitAction(Enum):
    HOLD = "HOLD"
    SELL_STOP = "SELL_STOP"  # Hit stop loss
    SELL_TARGET = "SELL_TARGET"  # Hit profit target
    SELL_TIME = "SELL_TIME"  # Max holding period
    SELL_RSI = "SELL_RSI"  # RSI overbought
    SELL_REGIME = "SELL_REGIME"  # Regime changed to BEAR


@dataclass
class ExitSignal:
    action: ExitAction
    urgency: float  # 0-100 (100 = exit immediately)
    current_return_pct: float
    days_held: int
    reason: str
    target_price: float = None
    stop_price: float = None


class ExitEngine:
    """
    Research-backed exit system.

    Key insight from research:
    "Even with random entries, keeping a good exit rule produced measurable returns.
    This highlights how much exits shape the outcome of a strategy."

    Exit Rules (by priority):
    1. Stop Loss: Fixed % based on regime (NOT trailing)
    2. Profit Target: Fixed % based on regime
    3. Time Exit: Maximum days based on regime
    4. RSI Exit: RSI(2) > 80 indicates mean reversion complete
    """

    def __init__(self):
        # Default exit parameters by regime
        self.exit_params = {
            MarketRegime.BULL: {
                'stop_loss_pct': 8.0,
                'profit_target_pct': 10.0,
                'max_days': 10,
                'rsi_exit_threshold': 85,
                'scale_out_pct': 50,  # Sell 50% at first target
                'scale_out_target_pct': 5.0,
            },
            MarketRegime.BEAR: {
                'stop_loss_pct': 4.0,  # Tight stops
                'profit_target_pct': 5.0,  # Quick profits
                'max_days': 5,  # Short holding
                'rsi_exit_threshold': 70,
                'scale_out_pct': 75,  # Exit most quickly
                'scale_out_target_pct': 3.0,
            },
            MarketRegime.SIDEWAYS: {
                'stop_loss_pct': 5.0,
                'profit_target_pct': 7.0,
                'max_days': 7,
                'rsi_exit_threshold': 80,
                'scale_out_pct': 50,
                'scale_out_target_pct': 4.0,
            },
            MarketRegime.HIGH_VOL: {
                'stop_loss_pct': 10.0,  # Wider stops for volatility
                'profit_target_pct': 12.0,  # Larger targets possible
                'max_days': 7,
                'rsi_exit_threshold': 85,
                'scale_out_pct': 50,
                'scale_out_target_pct': 6.0,
            },
        }

    @staticmethod
    def calc_rsi(closes: List[float], period: int) -> float:
        """Calculate RSI"""
        if len(closes) < period + 1:
            return 50

        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i-1]
            gains.append(max(0, diff))
            losses.append(max(0, -diff))

        if len(gains) < period:
            return 50

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def get_exit_signal(
        self,
        entry_price: float,
        current_price: float,
        days_held: int,
        closes: List[float],
        highs: List[float] = None,
        lows: List[float] = None,
        learned_params: dict = None  # From Thompson Sampling
    ) -> ExitSignal:
        """
        Determine if position should be exited.

        Args:
            entry_price: Original entry price
            current_price: Current price
            days_held: Days since entry
            closes: Recent price history for regime detection
            highs: High prices
            lows: Low prices
            learned_params: Parameters from Thompson Sampling learner

        Returns:
            ExitSignal with action and reason
        """
        # Detect current regime
        regime_info = RegimeDetector.detect(closes, highs, lows)
        params = self.exit_params.get(regime_info.regime, self.exit_params[MarketRegime.SIDEWAYS])

        # Override with learned params if provided
        if learned_params:
            params.update(learned_params)

        # Calculate current return
        return_pct = ((current_price - entry_price) / entry_price) * 100

        # Calculate RSI(2)
        rsi2 = self.calc_rsi(closes, 2)

        # Calculate stop and target prices
        stop_price = entry_price * (1 - params['stop_loss_pct'] / 100)
        target_price = entry_price * (1 + params['profit_target_pct'] / 100)

        # === CHECK EXIT CONDITIONS IN PRIORITY ORDER ===

        # 1. STOP LOSS (highest priority - protect capital)
        if current_price <= stop_price:
            return ExitSignal(
                action=ExitAction.SELL_STOP,
                urgency=100,
                current_return_pct=return_pct,
                days_held=days_held,
                reason=f"STOP LOSS: Price ${current_price:.2f} hit stop ${stop_price:.2f} ({return_pct:.1f}%)",
                target_price=target_price,
                stop_price=stop_price
            )

        # 2. REGIME CHANGE TO BEAR (sell if market turns against us)
        if regime_info.regime == MarketRegime.BEAR and return_pct > 0:
            return ExitSignal(
                action=ExitAction.SELL_REGIME,
                urgency=80,
                current_return_pct=return_pct,
                days_held=days_held,
                reason=f"REGIME CHANGE: Market turned BEAR, locking in {return_pct:.1f}% profit",
                target_price=target_price,
                stop_price=stop_price
            )

        # 3. PROFIT TARGET
        if current_price >= target_price:
            return ExitSignal(
                action=ExitAction.SELL_TARGET,
                urgency=90,
                current_return_pct=return_pct,
                days_held=days_held,
                reason=f"PROFIT TARGET: Price ${current_price:.2f} hit target ${target_price:.2f} ({return_pct:.1f}%)",
                target_price=target_price,
                stop_price=stop_price
            )

        # 4. TIME EXIT (mean reversion should complete within max_days)
        if days_held >= params['max_days']:
            return ExitSignal(
                action=ExitAction.SELL_TIME,
                urgency=70,
                current_return_pct=return_pct,
                days_held=days_held,
                reason=f"TIME EXIT: Held {days_held} days (max {params['max_days']}), return {return_pct:.1f}%",
                target_price=target_price,
                stop_price=stop_price
            )

        # 5. RSI EXIT (mean reversion complete)
        if rsi2 >= params['rsi_exit_threshold']:
            return ExitSignal(
                action=ExitAction.SELL_RSI,
                urgency=60,
                current_return_pct=return_pct,
                days_held=days_held,
                reason=f"RSI EXIT: RSI(2)={rsi2:.1f} >= {params['rsi_exit_threshold']} (mean reversion complete), return {return_pct:.1f}%",
                target_price=target_price,
                stop_price=stop_price
            )

        # 6. HOLD - no exit condition met
        return ExitSignal(
            action=ExitAction.HOLD,
            urgency=0,
            current_return_pct=return_pct,
            days_held=days_held,
            reason=f"HOLD: Return {return_pct:.1f}%, {params['max_days'] - days_held} days until time exit, RSI(2)={rsi2:.1f}",
            target_price=target_price,
            stop_price=stop_price
        )

    def get_scale_out_signal(
        self,
        entry_price: float,
        current_price: float,
        regime: MarketRegime
    ) -> Optional[dict]:
        """
        Check if we should scale out (sell partial position).

        Research: Scaling out 25-50% at first target locks in gains
        while keeping exposure to further upside.

        Returns:
            dict with scale_out_pct and reason, or None
        """
        params = self.exit_params.get(regime, self.exit_params[MarketRegime.SIDEWAYS])

        return_pct = ((current_price - entry_price) / entry_price) * 100
        scale_out_target = params['scale_out_target_pct']

        if return_pct >= scale_out_target:
            return {
                'scale_out_pct': params['scale_out_pct'],
                'reason': f"SCALE OUT: Return {return_pct:.1f}% hit {scale_out_target}% target, sell {params['scale_out_pct']}% of position"
            }

        return None
