"""
Regime Detection Module
=======================

Based on research:
- Zhang et al. (2023): Meta-learning for volatility regime adaptation
- Banerjee et al. (2024): Attention-based contextual weighting

Regimes:
- BULL: SMA50 > SMA200, price > SMA50 (aggressive entries)
- BEAR: SMA50 < SMA200, price < SMA50 (defensive, avoid)
- SIDEWAYS: Mixed signals (tighter thresholds)
- HIGH_VOL: ATR > 2x normal (reduce position size)
"""

from enum import Enum
from dataclasses import dataclass
from typing import List, Tuple
import statistics


class MarketRegime(Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOL = "HIGH_VOL"


@dataclass
class RegimeInfo:
    regime: MarketRegime
    confidence: float  # 0-100
    trend_strength: float  # 0-100, >25 = strong trend
    volatility_ratio: float  # current vol / historical vol
    sma50: float
    sma200: float
    atr14: float


class RegimeDetector:
    """
    Detect market regime for adaptive strategy selection.

    Research shows:
    - Mean reversion works poorly when trend_strength > 25%
    - Volatility >2x normal requires position size reduction
    """

    @staticmethod
    def calc_sma(prices: List[float], period: int) -> float:
        """Calculate Simple Moving Average"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        return sum(prices[-period:]) / period

    @staticmethod
    def calc_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(closes) < period + 1:
            return 0

        tr_values = []
        for i in range(1, len(closes)):
            high = highs[i] if i < len(highs) else closes[i]
            low = lows[i] if i < len(lows) else closes[i]
            prev_close = closes[i-1]

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            tr_values.append(tr)

        if len(tr_values) < period:
            return sum(tr_values) / len(tr_values) if tr_values else 0

        return sum(tr_values[-period:]) / period

    @staticmethod
    def calc_trend_strength(closes: List[float], period: int = 20) -> float:
        """
        Calculate trend strength (0-100).
        Based on price position relative to moving average.

        Research: Mean reversion performs poorly when trend_strength > 25%
        """
        if len(closes) < period:
            return 0

        sma = sum(closes[-period:]) / period
        price = closes[-1]

        # Calculate as percentage deviation from SMA
        deviation = abs(price - sma) / sma * 100

        # Normalize to 0-100 scale (cap at 10% deviation = 100 strength)
        return min(100, deviation * 10)

    @classmethod
    def detect(
        cls,
        closes: List[float],
        highs: List[float] = None,
        lows: List[float] = None,
        volumes: List[float] = None
    ) -> RegimeInfo:
        """
        Detect current market regime.

        Args:
            closes: List of closing prices (need 200+ for full analysis)
            highs: Optional high prices
            lows: Optional low prices
            volumes: Optional volumes

        Returns:
            RegimeInfo with regime classification and metrics
        """
        if len(closes) < 50:
            return RegimeInfo(
                regime=MarketRegime.SIDEWAYS,
                confidence=0,
                trend_strength=0,
                volatility_ratio=1.0,
                sma50=closes[-1] if closes else 0,
                sma200=closes[-1] if closes else 0,
                atr14=0
            )

        # Use closes for highs/lows if not provided
        if highs is None:
            highs = closes
        if lows is None:
            lows = closes

        # Calculate indicators
        sma50 = cls.calc_sma(closes, 50)
        sma200 = cls.calc_sma(closes, 200) if len(closes) >= 200 else sma50
        atr14 = cls.calc_atr(highs, lows, closes, 14)
        trend_strength = cls.calc_trend_strength(closes, 20)

        price = closes[-1]

        # Calculate historical volatility for comparison
        if len(closes) >= 60:
            recent_vol = statistics.stdev(closes[-20:]) if len(closes) >= 20 else 0
            hist_vol = statistics.stdev(closes[-60:])
            volatility_ratio = recent_vol / hist_vol if hist_vol > 0 else 1.0
        else:
            volatility_ratio = 1.0

        # Determine regime
        if volatility_ratio > 2.0:
            regime = MarketRegime.HIGH_VOL
            confidence = min(100, (volatility_ratio - 1) * 50)
        elif sma50 > sma200 and price > sma50:
            regime = MarketRegime.BULL
            confidence = min(100, ((sma50 - sma200) / sma200 * 100) + 50)
        elif sma50 < sma200 and price < sma50:
            regime = MarketRegime.BEAR
            confidence = min(100, ((sma200 - sma50) / sma200 * 100) + 50)
        else:
            regime = MarketRegime.SIDEWAYS
            confidence = 50

        return RegimeInfo(
            regime=regime,
            confidence=confidence,
            trend_strength=trend_strength,
            volatility_ratio=volatility_ratio,
            sma50=sma50,
            sma200=sma200,
            atr14=atr14
        )

    @classmethod
    def get_regime_params(cls, regime: MarketRegime) -> dict:
        """
        Get regime-specific parameters.

        Based on research:
        - BULL: More aggressive (RSI < 25)
        - BEAR: Very conservative (RSI < 5, or skip)
        - SIDEWAYS: Standard (RSI < 15)
        - HIGH_VOL: Reduce position size 50%
        """
        params = {
            MarketRegime.BULL: {
                'rsi_threshold': 25,
                'position_multiplier': 1.0,
                'min_confidence': 60,
                'exit_days': 7,
                'profit_target_pct': 5.0,
                'stop_loss_pct': 8.0,
            },
            MarketRegime.BEAR: {
                'rsi_threshold': 5,  # Very strict
                'position_multiplier': 0.25,  # Small positions
                'min_confidence': 80,
                'exit_days': 3,  # Quick exits
                'profit_target_pct': 3.0,
                'stop_loss_pct': 4.0,
            },
            MarketRegime.SIDEWAYS: {
                'rsi_threshold': 15,
                'position_multiplier': 0.75,
                'min_confidence': 65,
                'exit_days': 5,
                'profit_target_pct': 4.0,
                'stop_loss_pct': 5.0,
            },
            MarketRegime.HIGH_VOL: {
                'rsi_threshold': 10,
                'position_multiplier': 0.5,  # Half size
                'min_confidence': 70,
                'exit_days': 5,
                'profit_target_pct': 6.0,  # Larger moves possible
                'stop_loss_pct': 10.0,  # Wider stops
            },
        }
        return params.get(regime, params[MarketRegime.SIDEWAYS])
