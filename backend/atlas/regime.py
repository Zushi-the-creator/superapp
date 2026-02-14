"""
ATLAS Regime Detection Module
==============================

Market regime detection for adaptive signal adjustment.
Determines BULL, BEAR, SIDEWAYS, or HIGH_VOL regime.

Ported from regime_model_v24.py:111-165 with enhancements.

Academic References:
- Zhang et al. (2023): Meta-learning for volatility regime adaptation
- Trend-following research: SMA alignment for trend detection
"""

from enum import Enum
from typing import List, Dict, Tuple
from dataclasses import dataclass

from .indicators import Indicators


class MarketRegime(Enum):
    """Market regime classification"""
    BULL = "BULL"              # Strong uptrend
    BEAR = "BEAR"              # Strong downtrend
    SIDEWAYS = "SIDEWAYS"      # Range-bound
    HIGH_VOL = "HIGH_VOL"      # Extreme volatility


@dataclass
class RegimeInfo:
    """Full regime analysis output"""
    regime: MarketRegime
    price: float
    sma20: float
    sma50: float
    sma200: float
    volatility: float
    direction_consistency: float
    buy_multiplier: float
    sell_multiplier: float
    recommended_stop_pct: float
    recommended_target_pct: float


class RegimeDetector:
    """
    Market regime detection based on academic research.

    Detection Logic:
    - BULL: Price > SMA50 > SMA200 (uptrend alignment)
    - BEAR: Price < SMA50 < SMA200 (downtrend alignment)
    - HIGH_VOL: Volatility > 50% annualized
    - SIDEWAYS: Mixed signals (default)

    Signal Adjustments by Regime:
    - BULL: Aggressive entries (RSI<25), suppress sells (0.3x)
    - BEAR: Conservative entries (RSI<10), aggressive sells (1.2x)
    - SIDEWAYS: Standard parameters
    - HIGH_VOL: Tighter stops, smaller positions
    """

    # Regime-specific signal multipliers
    REGIME_MULTIPLIERS = {
        MarketRegime.BULL: {"BUY": 1.2, "SELL": 0.3, "HOLD": 1.0},
        MarketRegime.BEAR: {"BUY": 0.3, "SELL": 1.2, "HOLD": 1.0},
        MarketRegime.SIDEWAYS: {"BUY": 1.0, "SELL": 1.0, "HOLD": 1.0},
        MarketRegime.HIGH_VOL: {"BUY": 0.5, "SELL": 0.5, "HOLD": 1.0},
    }

    # Regime-specific trading parameters
    REGIME_PARAMS = {
        MarketRegime.BULL: {
            "rsi2_buy": 25,
            "rsi2_sell": 95,
            "stop_pct": 8.0,
            "target_pct": 10.0,
            "use_trailing": True,
        },
        MarketRegime.BEAR: {
            "rsi2_buy": 10,
            "rsi2_sell": 85,
            "stop_pct": 4.0,
            "target_pct": 3.0,
            "use_trailing": False,
        },
        MarketRegime.SIDEWAYS: {
            "rsi2_buy": 20,
            "rsi2_sell": 90,
            "stop_pct": 5.0,
            "target_pct": 5.0,
            "use_trailing": True,
        },
        MarketRegime.HIGH_VOL: {
            "rsi2_buy": 15,
            "rsi2_sell": 90,
            "stop_pct": 4.0,
            "target_pct": 4.0,
            "use_trailing": False,
        },
    }

    # Volatility threshold for HIGH_VOL regime
    HIGH_VOL_THRESHOLD = 0.50  # 50% annualized

    @classmethod
    def detect(
        cls,
        closes: List[float],
        highs: List[float] = None,
        lows: List[float] = None
    ) -> MarketRegime:
        """
        Detect current market regime.

        Args:
            closes: List of closing prices (200+ for best results)
            highs: Optional high prices (for ATR)
            lows: Optional low prices (for ATR)

        Returns:
            MarketRegime enum value
        """
        if len(closes) < 50:
            return MarketRegime.SIDEWAYS

        price = closes[-1]
        sma50 = Indicators.calc_sma(closes, 50)
        sma200 = Indicators.calc_sma(closes, 200) if len(closes) >= 200 else sma50

        # Calculate volatility
        volatility = Indicators.calc_volatility(closes, 20)

        # High volatility takes precedence
        if volatility > cls.HIGH_VOL_THRESHOLD:
            return MarketRegime.HIGH_VOL

        # BULL: Price > SMA50 > SMA200 (uptrend alignment)
        if price > sma50 > sma200:
            return MarketRegime.BULL

        # BEAR: Price < SMA50 < SMA200 (downtrend alignment)
        if price < sma50 < sma200:
            return MarketRegime.BEAR

        # Default: SIDEWAYS
        return MarketRegime.SIDEWAYS

    @classmethod
    def get_full_analysis(
        cls,
        closes: List[float],
        highs: List[float] = None,
        lows: List[float] = None
    ) -> RegimeInfo:
        """
        Get full regime analysis with parameters.

        Args:
            closes: List of closing prices
            highs: Optional high prices
            lows: Optional low prices

        Returns:
            RegimeInfo with full analysis
        """
        regime = cls.detect(closes, highs, lows)

        price = closes[-1] if closes else 0.0
        sma20 = Indicators.calc_sma(closes, 20)
        sma50 = Indicators.calc_sma(closes, 50)
        sma200 = Indicators.calc_sma(closes, 200) if len(closes) >= 200 else sma50
        volatility = Indicators.calc_volatility(closes, 20)

        # Calculate direction consistency
        direction_consistency = cls._calc_direction_consistency(closes)

        # Get multipliers
        multipliers = cls.REGIME_MULTIPLIERS[regime]
        params = cls.REGIME_PARAMS[regime]

        return RegimeInfo(
            regime=regime,
            price=price,
            sma20=sma20,
            sma50=sma50,
            sma200=sma200,
            volatility=volatility,
            direction_consistency=direction_consistency,
            buy_multiplier=multipliers["BUY"],
            sell_multiplier=multipliers["SELL"],
            recommended_stop_pct=params["stop_pct"],
            recommended_target_pct=params["target_pct"],
        )

    @staticmethod
    def _calc_direction_consistency(closes: List[float], period: int = 20) -> float:
        """
        Calculate directional consistency of price movement.

        Returns:
            0.0 = perfectly choppy (10 up, 10 down)
            1.0 = perfectly trending (all same direction)
        """
        if len(closes) < period + 1:
            return 0.5

        up_days = sum(
            1 for i in range(1, min(period + 1, len(closes)))
            if closes[-i] > closes[-(i + 1)]
        )

        # 0 up_days or 20 up_days = 1.0 consistency
        # 10 up_days = 0.0 consistency
        return abs(up_days - period / 2) / (period / 2)

    @classmethod
    def get_multiplier(cls, regime: MarketRegime, signal: str) -> float:
        """
        Get signal multiplier for a regime.

        Args:
            regime: MarketRegime enum
            signal: "BUY", "SELL", or "HOLD"

        Returns:
            Multiplier (0.3 to 1.2)
        """
        return cls.REGIME_MULTIPLIERS.get(regime, {}).get(signal, 1.0)

    @classmethod
    def get_params(cls, regime: MarketRegime) -> Dict:
        """
        Get trading parameters for a regime.

        Returns:
            Dict with rsi2_buy, rsi2_sell, stop_pct, target_pct, use_trailing
        """
        return cls.REGIME_PARAMS.get(regime, cls.REGIME_PARAMS[MarketRegime.SIDEWAYS])

    @classmethod
    def should_suppress_signal(
        cls,
        signal: str,
        regime: MarketRegime,
        confidence: float
    ) -> Tuple[bool, float, str]:
        """
        Determine if a signal should be suppressed based on regime.

        Academic basis: Zhang et al. (2023) - regime-dependent signal filtering

        Args:
            signal: "BUY" or "SELL"
            regime: Current MarketRegime
            confidence: Original signal confidence

        Returns:
            Tuple of (suppress, adjusted_confidence, reason)
        """
        multiplier = cls.get_multiplier(regime, signal)
        adjusted_confidence = confidence * multiplier

        if multiplier < 0.5:
            # Suppressed
            if signal == "SELL" and regime == MarketRegime.BULL:
                return True, adjusted_confidence, "SELL suppressed in BULL regime"
            elif signal == "BUY" and regime == MarketRegime.BEAR:
                return True, adjusted_confidence, "BUY suppressed in BEAR regime"
            elif regime == MarketRegime.HIGH_VOL:
                return True, adjusted_confidence, f"{signal} suppressed in HIGH_VOL"

        return False, adjusted_confidence, ""

    @classmethod
    def adjust_for_regime(
        cls,
        buy_score: float,
        sell_score: float,
        regime: MarketRegime
    ) -> Tuple[float, float]:
        """
        Adjust entry/exit scores based on regime.

        This is the key fix from V24.0 that improved win rate from 48.7% to 60.8%.

        Args:
            buy_score: Raw buy signal score (0-100)
            sell_score: Raw sell signal score (0-100)
            regime: Current MarketRegime

        Returns:
            Tuple of (adjusted_buy_score, adjusted_sell_score)
        """
        buy_mult = cls.REGIME_MULTIPLIERS[regime]["BUY"]
        sell_mult = cls.REGIME_MULTIPLIERS[regime]["SELL"]

        return buy_score * buy_mult, sell_score * sell_mult
