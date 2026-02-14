"""
ATLAS Indicators Module
========================

Technical analysis calculations used across all ATLAS components.
Single source of truth for indicator calculations.

Ported from regime_model_v24.py:55-108 with enhancements.
"""

import statistics
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class IndicatorSnapshot:
    """All indicators at a point in time"""
    price: float
    rsi2: float
    rsi5: float
    rsi14: float
    sma5: float
    sma20: float
    sma50: float
    sma200: float
    ema9: float
    ema21: float
    bb_upper: float
    bb_middle: float
    bb_lower: float
    bb_width: float
    atr14: float
    volume_ratio: float


class Indicators:
    """
    Technical indicators for ATLAS trading signals.

    All calculations are vectorized where possible and
    handle edge cases (insufficient data) gracefully.
    """

    # ==================== RSI ====================

    @staticmethod
    def calc_rsi(closes: List[float], period: int = 14) -> float:
        """
        Calculate Relative Strength Index.

        RSI = 100 - (100 / (1 + RS))
        RS = Average Gain / Average Loss

        Args:
            closes: List of closing prices (most recent last)
            period: RSI period (default 14, also commonly 2 or 5)

        Returns:
            RSI value 0-100 (50 if insufficient data)
        """
        if len(closes) < period + 1:
            return 50.0

        gains = []
        losses = []
        for i in range(1, period + 1):
            diff = closes[-i] - closes[-(i + 1)]
            gains.append(max(0, diff))
            losses.append(max(0, -diff))

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    # ==================== MOVING AVERAGES ====================

    @staticmethod
    def calc_sma(closes: List[float], period: int) -> float:
        """
        Calculate Simple Moving Average.

        Args:
            closes: List of closing prices
            period: SMA period

        Returns:
            SMA value (last close if insufficient data)
        """
        if len(closes) < period:
            return closes[-1] if closes else 0.0
        return sum(closes[-period:]) / period

    @staticmethod
    def calc_ema(closes: List[float], period: int) -> float:
        """
        Calculate Exponential Moving Average.

        EMA_today = (Price_today * k) + (EMA_yesterday * (1-k))
        k = 2 / (period + 1)

        Args:
            closes: List of closing prices
            period: EMA period

        Returns:
            EMA value
        """
        if len(closes) < period:
            return closes[-1] if closes else 0.0

        multiplier = 2 / (period + 1)
        ema = sum(closes[:period]) / period  # Start with SMA

        for price in closes[period:]:
            ema = (price - ema) * multiplier + ema

        return ema

    # ==================== BOLLINGER BANDS ====================

    @staticmethod
    def calc_bollinger_bands(
        closes: List[float],
        period: int = 20,
        std_dev: float = 2.0
    ) -> Tuple[float, float, float]:
        """
        Calculate Bollinger Bands.

        Upper = SMA + (std_dev * σ)
        Middle = SMA
        Lower = SMA - (std_dev * σ)

        Args:
            closes: List of closing prices
            period: Band period (default 20)
            std_dev: Standard deviation multiplier (default 2.0)

        Returns:
            Tuple of (middle, upper, lower) band values
        """
        if len(closes) < period:
            price = closes[-1] if closes else 0.0
            return price, price, price

        sma = sum(closes[-period:]) / period
        std = statistics.stdev(closes[-period:])

        upper = sma + std_dev * std
        lower = sma - std_dev * std

        return sma, upper, lower

    @staticmethod
    def calc_bb_position(price: float, upper: float, lower: float) -> float:
        """
        Calculate price position within Bollinger Bands.

        Returns:
            0.0 = at lower band
            0.5 = at middle
            1.0 = at upper band
            <0 or >1 = outside bands
        """
        band_width = upper - lower
        if band_width == 0:
            return 0.5
        return (price - lower) / band_width

    # ==================== VOLATILITY ====================

    @staticmethod
    def calc_atr(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int = 14
    ) -> float:
        """
        Calculate Average True Range.

        True Range = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )

        Args:
            highs: List of high prices
            lows: List of low prices
            closes: List of closing prices
            period: ATR period (default 14)

        Returns:
            ATR value (0 if insufficient data)
        """
        if len(closes) < period + 1:
            return 0.0

        tr_list = []
        for i in range(1, min(period + 1, len(closes))):
            high_low = highs[-i] - lows[-i]
            high_close = abs(highs[-i] - closes[-(i + 1)])
            low_close = abs(lows[-i] - closes[-(i + 1)])
            tr_list.append(max(high_low, high_close, low_close))

        return sum(tr_list) / len(tr_list) if tr_list else 0.0

    @staticmethod
    def calc_volatility(closes: List[float], period: int = 20) -> float:
        """
        Calculate annualized volatility from daily returns.

        Returns:
            Annualized volatility as decimal (e.g., 0.25 = 25%)
        """
        if len(closes) < period + 1:
            return 0.30  # Default 30%

        returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(len(closes) - period, len(closes))
        ]

        daily_vol = statistics.stdev(returns)
        annualized = daily_vol * (252 ** 0.5)
        return annualized

    # ==================== VOLUME ====================

    @staticmethod
    def calc_volume_ratio(volumes: List[float], period: int = 20) -> float:
        """
        Calculate current volume relative to average.

        Returns:
            Ratio (e.g., 1.5 = 50% above average)
        """
        if len(volumes) < period + 1:
            return 1.0

        avg_volume = sum(volumes[-period - 1:-1]) / period
        if avg_volume == 0:
            return 1.0

        return volumes[-1] / avg_volume

    # ==================== TREND ====================

    @staticmethod
    def calc_consecutive_days(closes: List[float], direction: str = "down") -> int:
        """
        Count consecutive up or down days.

        Args:
            closes: List of closing prices
            direction: "up" or "down"

        Returns:
            Number of consecutive days in that direction
        """
        if len(closes) < 2:
            return 0

        count = 0
        for i in range(1, min(10, len(closes))):
            if direction == "down" and closes[-i] < closes[-(i + 1)]:
                count += 1
            elif direction == "up" and closes[-i] > closes[-(i + 1)]:
                count += 1
            else:
                break

        return count

    @staticmethod
    def calc_distance_from_high(closes: List[float], period: int = 20) -> float:
        """
        Calculate % distance from period high.

        Returns:
            Negative percentage (e.g., -5.0 = 5% below high)
        """
        if len(closes) < period:
            return 0.0

        high = max(closes[-period:])
        current = closes[-1]
        return ((current - high) / high) * 100

    @staticmethod
    def calc_distance_from_low(closes: List[float], period: int = 20) -> float:
        """
        Calculate % distance from period low.

        Returns:
            Positive percentage (e.g., 5.0 = 5% above low)
        """
        if len(closes) < period:
            return 0.0

        low = min(closes[-period:])
        current = closes[-1]
        return ((current - low) / low) * 100

    # ==================== SNAPSHOT ====================

    @classmethod
    def get_snapshot(
        cls,
        closes: List[float],
        highs: List[float] = None,
        lows: List[float] = None,
        volumes: List[float] = None
    ) -> IndicatorSnapshot:
        """
        Get all indicators at current point.

        Args:
            closes: List of closing prices (required)
            highs: List of high prices (optional, uses closes if None)
            lows: List of low prices (optional, uses closes if None)
            volumes: List of volumes (optional)

        Returns:
            IndicatorSnapshot with all indicator values
        """
        if highs is None:
            highs = closes
        if lows is None:
            lows = closes

        price = closes[-1] if closes else 0.0
        bb_mid, bb_upper, bb_lower = cls.calc_bollinger_bands(closes)

        return IndicatorSnapshot(
            price=price,
            rsi2=cls.calc_rsi(closes, 2),
            rsi5=cls.calc_rsi(closes, 5),
            rsi14=cls.calc_rsi(closes, 14),
            sma5=cls.calc_sma(closes, 5),
            sma20=cls.calc_sma(closes, 20),
            sma50=cls.calc_sma(closes, 50),
            sma200=cls.calc_sma(closes, 200),
            ema9=cls.calc_ema(closes, 9),
            ema21=cls.calc_ema(closes, 21),
            bb_upper=bb_upper,
            bb_middle=bb_mid,
            bb_lower=bb_lower,
            bb_width=(bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0,
            atr14=cls.calc_atr(highs, lows, closes, 14),
            volume_ratio=cls.calc_volume_ratio(volumes) if volumes else 1.0,
        )
