"""
Entry Engine Module
===================

Based on research:
- Larry Connors RSI(2): 75-91% win rate historically
- QuantifiedStrategies: Multi-factor improves reliability
- Jha et al. (2025): Triple-indicator confirmation = 85.4% accuracy
- FMZ Research: Avoid trading when trend_strength > 25%

Entry Scoring (85% Technical):
+40 pts: RSI(2) extreme oversold (<5)
+25 pts: RSI(2) oversold (<10)
+15 pts: RSI(2) moderately oversold (<20)
+20 pts: Price > SMA(50) (REQUIRED)
+10 pts: Price > SMA(200)
+10 pts: Volume > 1.5x average
+10 pts: RSI(14) < 40 (double confirmation)
-20 pts: Trend strength > 25% (mean reversion less effective)

VETO Conditions (10% Sentiment):
- Earnings within 7 days
- Strong negative news sentiment
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import Enum

from .regime import RegimeDetector, MarketRegime, RegimeInfo


class SignalType(Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    WAIT = "WAIT"  # Good setup but vetoed


@dataclass
class EntrySignal:
    signal: SignalType
    score: float  # 0-100
    confidence: float  # 0-100 based on historical win rate
    regime: MarketRegime
    rsi2: float
    rsi14: float
    factors: List[str]  # Reasons for signal
    vetoed: bool = False
    veto_reason: str = ""


class EntryEngine:
    """
    Multi-factor entry engine with regime adaptation.

    Research-backed rules:
    1. RSI(2) < threshold (regime-dependent)
    2. Price > SMA(50) (trend filter - REQUIRED)
    3. Volume confirmation (optional boost)
    4. RSI(14) < 40 (double confirmation)
    5. Trend strength < 25% (mean reversion works better)
    """

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

    @staticmethod
    def calc_sma(prices: List[float], period: int) -> float:
        """Calculate SMA"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        return sum(prices[-period:]) / period

    @staticmethod
    def calc_volume_ratio(volumes: List[float], period: int = 20) -> float:
        """Calculate current volume vs average"""
        if not volumes or len(volumes) < period:
            return 1.0
        avg_vol = sum(volumes[-period:]) / period
        return volumes[-1] / avg_vol if avg_vol > 0 else 1.0

    def generate_signal(
        self,
        closes: List[float],
        volumes: List[float] = None,
        highs: List[float] = None,
        lows: List[float] = None,
        days_to_earnings: int = None,
        sentiment_score: float = 0,  # -1 to +1
        learned_params: dict = None  # From Thompson Sampling
    ) -> EntrySignal:
        """
        Generate entry signal with multi-factor scoring.

        Args:
            closes: Price history
            volumes: Volume history
            highs: High prices
            lows: Low prices
            days_to_earnings: Days until earnings (veto if < 7)
            sentiment_score: -1 (negative) to +1 (positive)
            learned_params: Parameters from Thompson Sampling learner

        Returns:
            EntrySignal with score and factors
        """
        # Get regime
        regime_info = RegimeDetector.detect(closes, highs, lows, volumes)
        regime_params = RegimeDetector.get_regime_params(regime_info.regime)

        # Override with learned params if provided
        if learned_params:
            regime_params.update(learned_params)

        # Calculate indicators
        rsi2 = self.calc_rsi(closes, 2)
        rsi14 = self.calc_rsi(closes, 14)
        sma50 = self.calc_sma(closes, 50)
        sma200 = self.calc_sma(closes, 200)
        price = closes[-1]
        vol_ratio = self.calc_volume_ratio(volumes) if volumes else 1.0

        # Scoring
        score = 0
        factors = []

        # === REQUIRED: Price > SMA(50) ===
        if price <= sma50:
            return EntrySignal(
                signal=SignalType.HOLD,
                score=0,
                confidence=0,
                regime=regime_info.regime,
                rsi2=rsi2,
                rsi14=rsi14,
                factors=["REJECTED: Price below SMA(50) - no uptrend"]
            )

        factors.append(f"Price ${price:.2f} > SMA50 ${sma50:.2f} (uptrend)")
        score += 20

        # === RSI(2) Scoring ===
        rsi_threshold = regime_params['rsi_threshold']

        if rsi2 < 5:
            score += 40
            factors.append(f"RSI(2)={rsi2:.1f} EXTREME oversold (<5)")
        elif rsi2 < 10:
            score += 25
            factors.append(f"RSI(2)={rsi2:.1f} very oversold (<10)")
        elif rsi2 < rsi_threshold:
            score += 15
            factors.append(f"RSI(2)={rsi2:.1f} oversold (<{rsi_threshold})")
        else:
            return EntrySignal(
                signal=SignalType.HOLD,
                score=score,
                confidence=0,
                regime=regime_info.regime,
                rsi2=rsi2,
                rsi14=rsi14,
                factors=[f"RSI(2)={rsi2:.1f} not oversold (need <{rsi_threshold})"]
            )

        # === Additional Factors ===

        # Price > SMA(200) bonus
        if price > sma200:
            score += 10
            factors.append(f"Price > SMA200 ${sma200:.2f} (strong uptrend)")

        # Volume confirmation
        if vol_ratio > 1.5:
            score += 10
            factors.append(f"Volume {vol_ratio:.1f}x average (confirmation)")

        # RSI(14) double confirmation
        if rsi14 < 40:
            score += 10
            factors.append(f"RSI(14)={rsi14:.1f} < 40 (double confirmation)")

        # Trend strength penalty
        if regime_info.trend_strength > 25:
            score -= 20
            factors.append(f"WARNING: Trend strength {regime_info.trend_strength:.1f}% > 25% (mean reversion less effective)")

        # === VETO Checks (10% Sentiment) ===
        vetoed = False
        veto_reason = ""

        if days_to_earnings is not None and days_to_earnings <= 7:
            vetoed = True
            veto_reason = f"Earnings in {days_to_earnings} days - binary event risk"
            factors.append(f"VETO: {veto_reason}")

        if sentiment_score < -0.3:
            vetoed = True
            veto_reason = f"Strong negative sentiment ({sentiment_score:.2f})"
            factors.append(f"VETO: {veto_reason}")

        # === Determine Signal ===
        min_score = regime_params['min_confidence']

        if score >= min_score:
            if vetoed:
                signal = SignalType.WAIT
            else:
                signal = SignalType.BUY
        else:
            signal = SignalType.HOLD

        # Confidence based on score and regime
        confidence = min(100, score * regime_params['position_multiplier'])

        return EntrySignal(
            signal=signal,
            score=score,
            confidence=confidence,
            regime=regime_info.regime,
            rsi2=rsi2,
            rsi14=rsi14,
            factors=factors,
            vetoed=vetoed,
            veto_reason=veto_reason
        )
