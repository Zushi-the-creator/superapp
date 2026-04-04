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
    V3.0 Exit System — Per-strategy hold periods (backtested 76K trades, 10yr).

    Hold periods (10yr backtest, 48,849 trades):
    - MR Fixed60d: +3.48% avg, 54.8% WR, PF 1.51 — beats 45d (+2.34%)
    - MOM Fixed90d: best momentum hold period
    - ALL stops/targets/trailing stops HURT mean reversion returns

    Valid early exit reasons:
    (a) Earnings within 7 days — binary event risk
    (b) Stock-specific negative sentiment — EXIT
    (c) Model EXIT signal (both ATLAS WR + zone WR fail 65%) — EXIT
    """

    MR_HOLD_DAYS = 60
    MOM_HOLD_DAYS = 90
    HOLD_DAYS = 60  # Default for backward compat

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
        learned_params: dict = None,
        earnings_within_7d: bool = False,
        negative_sentiment: bool = False,
        atlas_wr_fail: bool = False,
        strategy: str = "MEAN_REVERSION",
    ) -> ExitSignal:
        """
        V3.0: Per-strategy hold periods. MR=45d, MOM=60d.
        No stops, no targets, no RSI exits.
        Only valid early exits: earnings, stock-specific bad news, model failure.
        """
        return_pct = ((current_price - entry_price) / entry_price) * 100
        rsi2 = self.calc_rsi(closes, 2) if len(closes) >= 3 else 50
        hold_target = self.MOM_HOLD_DAYS if strategy == "MOMENTUM" else self.MR_HOLD_DAYS
        days_remaining = max(0, hold_target - days_held)

        # === VALID EARLY EXIT TRIGGERS (V2.6) ===

        # 1. Earnings within 7 days — binary event risk
        if earnings_within_7d:
            return ExitSignal(
                action=ExitAction.SELL_TIME,
                urgency=95,
                current_return_pct=return_pct,
                days_held=days_held,
                reason=f"EARNINGS EXIT: Earnings within 7 days, return {return_pct:.1f}%"
            )

        # 2. Stock-specific negative sentiment
        if negative_sentiment:
            return ExitSignal(
                action=ExitAction.SELL_REGIME,
                urgency=85,
                current_return_pct=return_pct,
                days_held=days_held,
                reason=f"SENTIMENT EXIT: Stock-specific negative news, return {return_pct:.1f}%"
            )

        # 3. Model EXIT signal (both ATLAS WR + zone WR fail 65%)
        if atlas_wr_fail:
            return ExitSignal(
                action=ExitAction.SELL_STOP,
                urgency=80,
                current_return_pct=return_pct,
                days_held=days_held,
                reason=f"MODEL EXIT: Both ATLAS WR + zone WR fail 65%, return {return_pct:.1f}%"
            )

        # 4. Fixed time exit (MR=45d, MOM=60d)
        if days_held >= hold_target:
            return ExitSignal(
                action=ExitAction.SELL_TIME,
                urgency=70,
                current_return_pct=return_pct,
                days_held=days_held,
                reason=f"TIME EXIT: Held {days_held} days (Fixed{hold_target}d {strategy}), return {return_pct:.1f}%"
            )

        # 5. HOLD — let the trade work
        return ExitSignal(
            action=ExitAction.HOLD,
            urgency=0,
            current_return_pct=return_pct,
            days_held=days_held,
            reason=f"HOLD: Day {days_held}/{hold_target}, {days_remaining}d remaining, return {return_pct:.1f}%, RSI(2)={rsi2:.1f}"
        )

    def get_scale_out_signal(
        self,
        entry_price: float,
        current_price: float,
        regime: MarketRegime = None
    ) -> Optional[dict]:
        """
        V2.6: No scale-out. Fixed 30-day hold only.
        Kept for API compatibility — always returns None.
        """
        return None
