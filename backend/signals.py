"""
Technical Signal Engine
Calculates RSI, EMA crossovers, Volume Spikes, and generates Entry/Exit signals
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from datetime import datetime


class SignalEngine:
    """Calculate technical indicators and generate trading signals"""

    def __init__(self):
        self.rsi_period = 14
        self.ema_fast = 9
        self.ema_slow = 21
        self.volume_threshold = 2.0  # 2x average volume

    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_ema(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate Exponential Moving Average"""
        return prices.ewm(span=period, adjust=False).mean()

    def calculate_volume_spike(self, volumes: pd.Series, period: int = 20) -> pd.Series:
        """Detect volume spikes (current volume / average volume)"""
        avg_volume = volumes.rolling(window=period).mean()
        volume_ratio = volumes / avg_volume
        return volume_ratio

    def generate_signals(self, df: pd.DataFrame) -> Dict:
        """
        Generate comprehensive trading signals

        Args:
            df: DataFrame with columns: Open, High, Low, Close, Volume

        Returns:
            Dict with signal data and reasoning
        """
        if len(df) < 30:  # Need minimum data
            return self._empty_signal()

        # Calculate indicators
        df['RSI'] = self.calculate_rsi(df['Close'], self.rsi_period)
        df['EMA_Fast'] = self.calculate_ema(df['Close'], self.ema_fast)
        df['EMA_Slow'] = self.calculate_ema(df['Close'], self.ema_slow)
        df['Volume_Ratio'] = self.calculate_volume_spike(df['Volume'])

        # Get latest values
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # Signal logic
        signal_type = "HOLD"
        signal_strength = 0.0
        reasons = []

        # RSI Signals
        rsi = latest['RSI']
        if rsi < 30:
            signal_type = "BUY"
            signal_strength += 0.4
            reasons.append(f"RSI Oversold ({rsi:.1f})")
        elif rsi > 70:
            signal_type = "SELL"
            signal_strength += 0.4
            reasons.append(f"RSI Overbought ({rsi:.1f})")

        # EMA Crossover
        ema_cross = self._detect_ema_crossover(
            prev['EMA_Fast'], prev['EMA_Slow'],
            latest['EMA_Fast'], latest['EMA_Slow']
        )

        if ema_cross == "BULLISH":
            if signal_type != "SELL":
                signal_type = "BUY"
            signal_strength += 0.3
            reasons.append("EMA Bullish Crossover")
        elif ema_cross == "BEARISH":
            if signal_type != "BUY":
                signal_type = "SELL"
            signal_strength += 0.3
            reasons.append("EMA Bearish Crossover")

        # Volume Spike
        vol_ratio = latest['Volume_Ratio']
        if vol_ratio > self.volume_threshold:
            signal_strength += 0.3
            reasons.append(f"Volume Spike ({vol_ratio:.1f}x avg)")

        # Price momentum
        price_change = ((latest['Close'] - prev['Close']) / prev['Close']) * 100
        if abs(price_change) > 2:  # 2% move
            reasons.append(f"Strong momentum ({price_change:+.2f}%)")
            signal_strength += 0.2

        # Normalize signal strength
        signal_strength = min(signal_strength, 1.0)

        return {
            "signal": signal_type,
            "strength": round(signal_strength * 100, 2),
            "rsi": round(rsi, 2),
            "ema_fast": round(latest['EMA_Fast'], 2),
            "ema_slow": round(latest['EMA_Slow'], 2),
            "volume_ratio": round(vol_ratio, 2),
            "price_change_pct": round(price_change, 2),
            "price": round(latest['Close'], 2),
            "reasons": reasons,
            "timestamp": datetime.now().isoformat()
        }

    def _detect_ema_crossover(self, prev_fast: float, prev_slow: float,
                             curr_fast: float, curr_slow: float) -> str:
        """Detect EMA crossover"""
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            return "BULLISH"
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            return "BEARISH"
        return "NONE"

    def _empty_signal(self) -> Dict:
        """Return empty signal when insufficient data"""
        return {
            "signal": "HOLD",
            "strength": 0.0,
            "rsi": 0.0,
            "ema_fast": 0.0,
            "ema_slow": 0.0,
            "volume_ratio": 0.0,
            "price_change_pct": 0.0,
            "price": 0.0,
            "reasons": ["Insufficient data"],
            "timestamp": datetime.now().isoformat()
        }


class AdvancedSignals:
    """Additional advanced signals for institutional-grade analysis"""

    @staticmethod
    def calculate_bollinger_bands(prices: pd.Series, period: int = 20, std: int = 2) -> Tuple:
        """Calculate Bollinger Bands"""
        sma = prices.rolling(window=period).mean()
        std_dev = prices.rolling(window=period).std()
        upper_band = sma + (std_dev * std)
        lower_band = sma - (std_dev * std)
        return upper_band, sma, lower_band

    @staticmethod
    def calculate_macd(prices: pd.Series) -> Tuple:
        """Calculate MACD (Moving Average Convergence Divergence)"""
        ema_12 = prices.ewm(span=12, adjust=False).mean()
        ema_26 = prices.ewm(span=26, adjust=False).mean()
        macd_line = ema_12 - ema_26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range (volatility)"""
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())

        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = true_range.rolling(window=period).mean()
        return atr
