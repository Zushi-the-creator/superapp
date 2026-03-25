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
    V2.6 Exit System — Fixed 30-day hold (universal).

    Mega-study (2,829 stocks, 307K trades) confirms:
    - Fixed30d beats ALL other exits: +4.31% avg, 61% WR, PF 2.21
    - ALL stops/targets/trailing stops HURT mean reversion returns
    - No profit targets: let positions run to their optimal exit

    Valid early exit reasons (from CLAUDE.md):
    (a) Earnings within 7 days — binary event risk
    (b) Stock-specific negative sentiment — EXIT
    (c) Model EXIT signal (both ATLAS WR + zone WR fail 65%) — EXIT
    """

    # V2.6: Fixed 30-day hold for ALL regimes
    HOLD_DAYS = 30

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
        # V2.6 early exit triggers
        earnings_within_7d: bool = False,
        negative_sentiment: bool = False,
        atlas_wr_fail: bool = False,
    ) -> ExitSignal:
        """
        V2.6: Fixed 30-day hold. No stops, no targets, no RSI exits.
        Only valid early exits: earnings, stock-specific bad news, model failure.

        Args:
            entry_price: Original entry price
            current_price: Current price
            days_held: Days since entry
            closes: Recent price history
            highs: High prices
            lows: Low prices
            learned_params: (ignored in V2.6 — kept for API compat)
            earnings_within_7d: True if earnings < 7 days away
            negative_sentiment: True if stock-specific negative news
            atlas_wr_fail: True if both ATLAS WR + zone WR fail 65%
        """
        return_pct = ((current_price - entry_price) / entry_price) * 100
        rsi2 = self.calc_rsi(closes, 2) if len(closes) >= 3 else 50
        days_remaining = max(0, self.HOLD_DAYS - days_held)

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

        # 4. Fixed 30-day time exit
        if days_held >= self.HOLD_DAYS:
            return ExitSignal(
                action=ExitAction.SELL_TIME,
                urgency=70,
                current_return_pct=return_pct,
                days_held=days_held,
                reason=f"TIME EXIT: Held {days_held} days (Fixed{self.HOLD_DAYS}d), return {return_pct:.1f}%"
            )

        # 5. HOLD — let the trade work
        return ExitSignal(
            action=ExitAction.HOLD,
            urgency=0,
            current_return_pct=return_pct,
            days_held=days_held,
            reason=f"HOLD: Day {days_held}/{self.HOLD_DAYS}, {days_remaining}d remaining, return {return_pct:.1f}%, RSI(2)={rsi2:.1f}"
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
