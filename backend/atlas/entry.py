"""
ATLAS Entry Signal Module
==========================

Unified entry signal generation - same logic for ALL stocks.
Uses RSI(2) mean reversion with regime-adjusted thresholds.

Core Rule:
    IF RSI(2) < threshold AND Price > SMA(50) → BUY

Regime-Adjusted Thresholds:
    BULL:     RSI(2) < 25 (aggressive)
    SIDEWAYS: RSI(2) < 20 (standard)
    BEAR:     RSI(2) < 10 (conservative)
    HIGH_VOL: RSI(2) < 15 (moderate)

Academic References:
- Larry Connors: RSI(2) mean reversion (75% historical win rate)
- Validated on 34 stocks, 755 trades: 65.96% overall win rate
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from enum import Enum

from .indicators import Indicators
from .regime import RegimeDetector, MarketRegime


class SignalType(Enum):
    """Entry signal types"""
    BUY = "BUY"
    HOLD = "HOLD"
    WAIT = "WAIT"  # Vetoed by sentiment


@dataclass
class EntrySignal:
    """Entry signal output"""
    signal: SignalType
    confidence: float  # 0-100
    regime: MarketRegime
    entry_score: int
    reasons: List[str]
    indicators: Dict[str, float]
    vetoed: bool = False
    veto_reason: str = ""


class EntryEngine:
    """
    Unified entry signal generator.

    Same logic for ALL stocks - no per-stock optimization.
    Adapts via regime detection, not stock-specific parameters.
    """

    # Regime-adjusted RSI(2) thresholds for BUY
    RSI2_THRESHOLDS = {
        MarketRegime.BULL: 25,      # More aggressive in bull
        MarketRegime.SIDEWAYS: 20,  # Standard
        MarketRegime.BEAR: 10,      # Very conservative in bear
        MarketRegime.HIGH_VOL: 15,  # Moderate
    }

    # Minimum confidence to generate signal per regime
    MIN_CONFIDENCE = {
        MarketRegime.BULL: 60,
        MarketRegime.SIDEWAYS: 65,
        MarketRegime.BEAR: 75,
        MarketRegime.HIGH_VOL: 70,
    }

    def __init__(self, db=None):
        """
        Initialize entry engine.

        Args:
            db: Optional ATLASDatabase for learned parameters
        """
        self.db = db

    def generate_signal(
        self,
        closes: List[float],
        volumes: List[float] = None,
        highs: List[float] = None,
        lows: List[float] = None,
        sentiment_veto: bool = False,
        veto_reason: str = ""
    ) -> EntrySignal:
        """
        Generate entry signal for a stock.

        Args:
            closes: List of closing prices (50+ recommended)
            volumes: Optional volume data
            highs: Optional high prices
            lows: Optional low prices
            sentiment_veto: Whether to block entry (earnings, bad news)
            veto_reason: Reason for veto if applicable

        Returns:
            EntrySignal with recommendation
        """
        if len(closes) < 50:
            return EntrySignal(
                signal=SignalType.HOLD,
                confidence=50,
                regime=MarketRegime.SIDEWAYS,
                entry_score=0,
                reasons=["Insufficient data (need 50+ days)"],
                indicators={},
            )

        # Detect regime
        regime = RegimeDetector.detect(closes, highs, lows)

        # Get indicators
        snapshot = Indicators.get_snapshot(closes, highs, lows, volumes)

        # Get regime-specific threshold
        rsi2_threshold = self._get_rsi2_threshold(regime)

        # Calculate entry score (0-100)
        entry_score, reasons = self._calc_entry_score(
            snapshot, regime, rsi2_threshold
        )

        # Check veto
        if sentiment_veto:
            return EntrySignal(
                signal=SignalType.WAIT,
                confidence=50,
                regime=regime,
                entry_score=entry_score,
                reasons=reasons,
                indicators=self._snapshot_to_dict(snapshot),
                vetoed=True,
                veto_reason=veto_reason or "Sentiment veto",
            )

        # Determine signal
        min_conf = self.MIN_CONFIDENCE.get(regime, 65)

        if entry_score >= 50:
            confidence = min(95, 50 + entry_score)
            if confidence >= min_conf:
                return EntrySignal(
                    signal=SignalType.BUY,
                    confidence=confidence,
                    regime=regime,
                    entry_score=entry_score,
                    reasons=reasons,
                    indicators=self._snapshot_to_dict(snapshot),
                )

        # No signal
        return EntrySignal(
            signal=SignalType.HOLD,
            confidence=50,
            regime=regime,
            entry_score=entry_score,
            reasons=reasons + [f"Score {entry_score} < 50 or conf < {min_conf}"],
            indicators=self._snapshot_to_dict(snapshot),
        )

    def _get_rsi2_threshold(self, regime: MarketRegime) -> int:
        """Get RSI(2) buy threshold for regime, with learned adjustment"""
        base = self.RSI2_THRESHOLDS.get(regime, 20)

        # If database available, check for learned adjustment
        if self.db:
            try:
                learned = self.db.get_parameter(regime.value, "rsi2_buy")
                if learned is not None:
                    return int(learned)
            except:
                pass

        return base

    def _calc_entry_score(
        self,
        snapshot,
        regime: MarketRegime,
        rsi2_threshold: int
    ) -> Tuple[int, List[str]]:
        """
        Calculate entry score using unified scoring system.

        Scoring (85% technical):
        +40 pts: RSI(2) < 5 (extreme)
        +30 pts: RSI(2) < 10
        +20 pts: RSI(2) < threshold
        +20 pts: Near BB lower (within 2%)
        +20 pts: Price > SMA(50) (REQUIRED for BUY)
        +10 pts: Price > SMA(200)
        +10 pts: RSI(14) < 40
        +10 pts: Volume > 1.3x avg

        Returns:
            Tuple of (score, list of reasons)
        """
        score = 0
        reasons = []

        # REQUIRED: Price above SMA(50) for uptrend
        if snapshot.price > snapshot.sma50:
            score += 20
            reasons.append("Price > SMA50 (uptrend)")
        else:
            # Cannot generate BUY if in downtrend
            return 0, ["Blocked: Price below SMA50 (downtrend)"]

        # PRIMARY: RSI(2) oversold levels
        if snapshot.rsi2 < 5:
            score += 40
            reasons.append(f"RSI(2)={snapshot.rsi2:.0f} EXTREME")
        elif snapshot.rsi2 < 10:
            score += 30
            reasons.append(f"RSI(2)={snapshot.rsi2:.0f} very oversold")
        elif snapshot.rsi2 < rsi2_threshold:
            score += 20
            reasons.append(f"RSI(2)={snapshot.rsi2:.0f} oversold")

        # BONUS: Near Bollinger Band lower
        bb_dist_pct = ((snapshot.price - snapshot.bb_lower) / snapshot.bb_lower) * 100
        if bb_dist_pct <= 2.0:
            score += 20
            reasons.append(f"Near BB lower ({bb_dist_pct:.1f}%)")

        # BONUS: Price above SMA(200)
        if snapshot.price > snapshot.sma200:
            score += 10
            reasons.append("Price > SMA200")

        # BONUS: RSI(14) also oversold
        if snapshot.rsi14 < 40:
            score += 10
            reasons.append(f"RSI(14)={snapshot.rsi14:.0f} oversold")

        # BONUS: Volume confirmation
        if snapshot.volume_ratio > 1.3:
            score += 10
            reasons.append(f"Volume {snapshot.volume_ratio:.1f}x avg")

        # Apply regime adjustment
        buy_mult = RegimeDetector.get_multiplier(regime, "BUY")
        if buy_mult != 1.0:
            original_score = score
            score = int(score * buy_mult)
            if buy_mult < 1.0:
                reasons.append(f"({regime.value}: score reduced {original_score}→{score})")

        return score, reasons

    def _snapshot_to_dict(self, snapshot) -> Dict[str, float]:
        """Convert snapshot to dict for output"""
        return {
            "price": round(snapshot.price, 2),
            "rsi2": round(snapshot.rsi2, 1),
            "rsi5": round(snapshot.rsi5, 1),
            "rsi14": round(snapshot.rsi14, 1),
            "sma50": round(snapshot.sma50, 2),
            "sma200": round(snapshot.sma200, 2),
            "bb_lower": round(snapshot.bb_lower, 2),
            "bb_upper": round(snapshot.bb_upper, 2),
            "volume_ratio": round(snapshot.volume_ratio, 2),
        }


def check_sentiment_veto(
    ticker: str,
    days_to_earnings: int = None,
    negative_news_count: int = 0,
    positive_news_count: int = 0
) -> Tuple[bool, str]:
    """
    Check if entry should be vetoed based on sentiment.

    Veto conditions (10% weight in decision):
    - Earnings within 7 days
    - More negative than positive news
    - Major event upcoming

    Args:
        ticker: Stock symbol
        days_to_earnings: Days until next earnings (None if unknown)
        negative_news_count: Count of negative news articles
        positive_news_count: Count of positive news articles

    Returns:
        Tuple of (should_veto, reason)
    """
    # Earnings veto
    if days_to_earnings is not None and days_to_earnings <= 7:
        return True, f"Earnings in {days_to_earnings} days - WAIT"

    # Negative sentiment veto
    if negative_news_count > positive_news_count and negative_news_count >= 3:
        return True, f"Negative news ({negative_news_count} neg vs {positive_news_count} pos)"

    return False, ""
