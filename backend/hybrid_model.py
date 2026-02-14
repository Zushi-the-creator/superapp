"""
Hybrid Model Selector
Automatically picks the best prediction model for each stock based on historical backtesting.
Always uses the most accurate model for each ticker.

Transaction Cost Awareness (Added 2026-01-21):
- Platform fee: $1.50 per trade
- Round-trip cost: $3.00
- Signals filtered to ensure profit > transaction costs
"""

import math
import json
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass
from datetime import datetime


# ============================================================
# TRANSACTION COST CONSTANTS
# ============================================================
TRANSACTION_COST_PER_TRADE = 1.50  # USD per trade
ROUND_TRIP_COST = TRANSACTION_COST_PER_TRADE * 2  # $3.00
MIN_PROFIT_BUFFER = 2.0  # Require 2x cost to justify trade
MIN_PROFIT_THRESHOLD = ROUND_TRIP_COST * MIN_PROFIT_BUFFER  # $6.00


@dataclass
class ModelResult:
    """Result from a single model backtest"""
    model_name: str
    win_rate_7d: float
    win_rate_14d: float
    avg_return: float
    total_signals: int
    buy_signals: int
    sell_signals: int


@dataclass
class Signal:
    """Trading signal output"""
    ticker: str
    model_used: str
    model_accuracy: float
    signal: str  # BUY, SELL, HOLD
    strength: float
    indicators: Dict
    reasoning: str
    # Transaction cost fields (added 2026-01-21)
    position_value: float = 0.0
    min_move_pct: float = 0.0
    fee_adjusted: bool = False
    net_signal: str = ""  # Signal after fee filter (may be HOLD if not profitable)


class HybridModelSelector:
    """
    Automatically selects and uses the best model for each ticker.

    Process:
    1. Backtest ALL models on historical data
    2. Rank models by win rate
    3. Select best model for each ticker
    4. Generate signal using only the best model
    """

    def __init__(self):
        self.model_cache: Dict[str, ModelResult] = {}
        self.best_models: Dict[str, str] = {}

    # ============================================================
    # TRANSACTION COST CALCULATIONS (Added 2026-01-21)
    # ============================================================

    def calculate_fee_impact(self, position_value: float, expected_move_pct: float = 0) -> Dict:
        """
        Calculate transaction cost impact for a given position.

        Args:
            position_value: Current position value in USD
            expected_move_pct: Expected price move percentage (optional)

        Returns:
            Dict with fee analysis
        """
        if position_value <= 0:
            return {
                "profitable": False,
                "min_move_pct": float('inf'),
                "min_profit_needed": MIN_PROFIT_THRESHOLD,
                "round_trip_cost": ROUND_TRIP_COST,
                "fee_impact_pct": float('inf')
            }

        # Minimum move needed to cover round-trip cost + buffer
        min_move_pct = (MIN_PROFIT_THRESHOLD / position_value) * 100

        # Fee as percentage of position
        fee_impact_pct = (ROUND_TRIP_COST / position_value) * 100

        # Is the expected move profitable after fees?
        expected_profit = position_value * (expected_move_pct / 100) if expected_move_pct > 0 else 0
        profitable = expected_profit > MIN_PROFIT_THRESHOLD

        return {
            "profitable": profitable,
            "min_move_pct": round(min_move_pct, 3),
            "min_profit_needed": MIN_PROFIT_THRESHOLD,
            "round_trip_cost": ROUND_TRIP_COST,
            "fee_impact_pct": round(fee_impact_pct, 3),
            "expected_profit": round(expected_profit, 2),
            "net_profit": round(expected_profit - ROUND_TRIP_COST, 2) if expected_move_pct > 0 else 0
        }

    def should_trade(self, position_value: float, win_rate: float,
                     avg_expected_return: float = 2.0) -> Dict:
        """
        Determine if a trade is worth making given fees and win rate.

        Uses expected value calculation:
        EV = (win_rate × avg_win) - ((1 - win_rate) × avg_loss) - fees

        Args:
            position_value: Position size in USD
            win_rate: Model win rate as decimal (0-1)
            avg_expected_return: Average expected return % per trade

        Returns:
            Dict with trade recommendation
        """
        if position_value <= 0:
            return {"should_trade": False, "reason": "No position value"}

        # Expected profit per trade (using win rate)
        avg_win = position_value * (avg_expected_return / 100)
        avg_loss = position_value * (avg_expected_return / 100) * 0.5  # Assume losses are 50% of wins

        expected_value = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) - ROUND_TRIP_COST

        # Also check minimum position size rule
        fee_impact = self.calculate_fee_impact(position_value)
        min_position_for_trading = 500  # Avoid frequent trading under $500

        should_trade = (
            expected_value > 0 and
            position_value >= min_position_for_trading and
            fee_impact["min_move_pct"] < 1.0  # Must not need >1% move just to break even
        )

        return {
            "should_trade": should_trade,
            "expected_value": round(expected_value, 2),
            "min_move_pct": fee_impact["min_move_pct"],
            "position_value": position_value,
            "reason": (
                "Profitable after fees" if should_trade
                else "Position too small for frequent trading" if position_value < min_position_for_trading
                else f"EV negative (${expected_value:.2f})"
            )
        }

    # ============================================================
    # TECHNICAL INDICATOR CALCULATIONS
    # ============================================================

    def _calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """Relative Strength Index"""
        if len(closes) < period + 1:
            return 50.0

        gains, losses = [], []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            gains.append(max(change, 0))
            losses.append(max(-change, 0))

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_ema(self, closes: List[float], period: int) -> float:
        """Exponential Moving Average"""
        if len(closes) < period:
            return closes[-1] if closes else 0

        k = 2 / (period + 1)
        ema = sum(closes[:period]) / period

        for price in closes[period:]:
            ema = price * k + ema * (1 - k)

        return ema

    def _calculate_sma(self, closes: List[float], period: int) -> float:
        """Simple Moving Average"""
        if len(closes) < period:
            return closes[-1] if closes else 0
        return sum(closes[-period:]) / period

    def _calculate_bollinger(self, closes: List[float], period: int = 20) -> Tuple[float, float, float]:
        """Bollinger Bands: (upper, middle, lower)"""
        if len(closes) < period:
            return closes[-1], closes[-1], closes[-1]

        middle = sum(closes[-period:]) / period
        variance = sum((x - middle) ** 2 for x in closes[-period:]) / period
        std = math.sqrt(variance) if variance > 0 else 0

        return middle + (2 * std), middle, middle - (2 * std)

    def _calculate_macd(self, closes: List[float]) -> Tuple[float, float, float]:
        """MACD: (macd_line, signal_line, histogram)"""
        ema12 = self._calculate_ema(closes, 12)
        ema26 = self._calculate_ema(closes, 26)
        macd_line = ema12 - ema26

        # Simplified signal line
        signal_line = macd_line * 0.9
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    def _calculate_momentum(self, closes: List[float], period: int = 10) -> float:
        """Price momentum over period (%)"""
        if len(closes) < period:
            return 0
        return (closes[-1] - closes[-period]) / closes[-period] * 100

    def _calculate_volume_ratio(self, volumes: List[float], period: int = 20) -> float:
        """Current volume vs average"""
        if len(volumes) < period:
            return 1.0
        avg_vol = sum(volumes[-period:]) / period
        if avg_vol == 0:
            return 1.0
        return volumes[-1] / avg_vol

    def _get_regime(self, closes: List[float]) -> Tuple[str, Dict]:
        """
        Determine market regime based on price vs major moving averages.

        Returns:
            (regime, details) where regime is BULL, BEAR, or NEUTRAL

        Rules:
        - BULL: Price > SMA50 AND Price > SMA200
        - BEAR: Price < SMA50 AND Price < SMA200
        - NEUTRAL: Mixed signals
        """
        if len(closes) < 200:
            # Not enough data for SMA200, use SMA50 only
            if len(closes) < 50:
                return "NEUTRAL", {"reason": "Insufficient data"}

            sma50 = self._calculate_sma(closes, 50)
            price = closes[-1]

            if price > sma50 * 1.02:  # 2% above
                return "BULL", {"SMA50": round(sma50, 2), "price_vs_sma50": "ABOVE"}
            elif price < sma50 * 0.98:  # 2% below
                return "BEAR", {"SMA50": round(sma50, 2), "price_vs_sma50": "BELOW"}
            else:
                return "NEUTRAL", {"SMA50": round(sma50, 2), "price_vs_sma50": "NEAR"}

        price = closes[-1]
        sma50 = self._calculate_sma(closes, 50)
        sma200 = self._calculate_sma(closes, 200)

        above_sma50 = price > sma50
        above_sma200 = price > sma200

        details = {
            "SMA50": round(sma50, 2),
            "SMA200": round(sma200, 2),
            "above_SMA50": above_sma50,
            "above_SMA200": above_sma200
        }

        if above_sma50 and above_sma200:
            return "BULL", details
        elif not above_sma50 and not above_sma200:
            return "BEAR", details
        else:
            return "NEUTRAL", details

    # ============================================================
    # ALL TRADING MODELS
    # ============================================================

    def _model_v1_rsi_ema(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """V1.0 RSI/EMA - Classic technical analysis"""
        if len(closes) < 30:
            return "HOLD", 0, {}

        rsi = self._calculate_rsi(closes)
        ema9 = self._calculate_ema(closes, 9)
        ema21 = self._calculate_ema(closes, 21)

        signal = "HOLD"
        strength = 0

        if rsi < 30:
            signal = "BUY"
            strength += 40
        elif rsi > 70:
            signal = "SELL"
            strength += 40

        if ema9 > ema21:
            if signal != "SELL":
                signal = "BUY"
            strength += 30
        elif ema9 < ema21:
            if signal != "BUY":
                signal = "SELL"
            strength += 30

        indicators = {
            "RSI": round(rsi, 1),
            "EMA9": round(ema9, 2),
            "EMA21": round(ema21, 2),
            "EMA_Cross": "Bullish" if ema9 > ema21 else "Bearish"
        }

        return signal, min(strength, 100), indicators

    def _model_v6_ensemble(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """V6.0 Ensemble - Requires 3+ indicators to agree"""
        if len(closes) < 50:
            return "HOLD", 0, {}

        buy_votes = 0
        sell_votes = 0

        # 1. RSI
        rsi = self._calculate_rsi(closes)
        if rsi < 35:
            buy_votes += 1
        elif rsi > 65:
            sell_votes += 1

        # 2. EMA Crossover
        ema9 = self._calculate_ema(closes, 9)
        ema21 = self._calculate_ema(closes, 21)
        if ema9 > ema21:
            buy_votes += 1
        elif ema9 < ema21:
            sell_votes += 1

        # 3. Price vs SMA50
        sma50 = self._calculate_sma(closes, 50)
        if closes[-1] > sma50:
            buy_votes += 1
        else:
            sell_votes += 1

        # 4. MACD
        macd, signal_line, hist = self._calculate_macd(closes)
        if hist > 0:
            buy_votes += 1
        elif hist < 0:
            sell_votes += 1

        # 5. Volume
        if volumes:
            vol_ratio = self._calculate_volume_ratio(volumes)
            if vol_ratio > 1.5:
                if closes[-1] > closes[-2]:
                    buy_votes += 1
                else:
                    sell_votes += 1

        indicators = {
            "Buy_Votes": buy_votes,
            "Sell_Votes": sell_votes,
            "RSI": round(rsi, 1),
            "MACD_Hist": round(hist, 3)
        }

        if buy_votes >= 3 and buy_votes > sell_votes:
            return "BUY", min(buy_votes * 20, 100), indicators
        elif sell_votes >= 3 and sell_votes > buy_votes:
            return "SELL", min(sell_votes * 20, 100), indicators
        else:
            return "HOLD", 0, indicators

    def _model_v7_trend_follow(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """V7.0 Trend Following - Only trade WITH the trend"""
        if len(closes) < 60:
            return "HOLD", 0, {}

        ema20 = self._calculate_ema(closes, 20)
        ema50 = self._calculate_ema(closes, 50)
        price = closes[-1]

        uptrend = price > ema20 > ema50
        downtrend = price < ema20 < ema50

        rsi = self._calculate_rsi(closes)

        indicators = {
            "Trend": "UP" if uptrend else "DOWN" if downtrend else "SIDEWAYS",
            "RSI": round(rsi, 1),
            "EMA20": round(ema20, 2),
            "EMA50": round(ema50, 2)
        }

        if uptrend and rsi < 45:
            return "BUY", 70, indicators
        elif uptrend and rsi < 55:
            return "BUY", 50, indicators
        elif downtrend and rsi > 55:
            return "SELL", 70, indicators
        elif downtrend and rsi > 45:
            return "SELL", 50, indicators

        return "HOLD", 0, indicators

    def _model_v8_mean_reversion(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """V8.0 Mean Reversion - Buy extremes, expect snap-back

        REGIME FILTER: Only BUY in BULL or NEUTRAL regime (never in BEAR)
        """
        if len(closes) < 30:
            return "HOLD", 0, {}

        price = closes[-1]
        upper, middle, lower = self._calculate_bollinger(closes, 20)
        rsi = self._calculate_rsi(closes)
        regime, regime_details = self._get_regime(closes)

        deviation = (price - middle) / middle * 100

        indicators = {
            "BB_Upper": round(upper, 2),
            "BB_Middle": round(middle, 2),
            "BB_Lower": round(lower, 2),
            "Deviation": f"{deviation:+.1f}%",
            "RSI": round(rsi, 1),
            "Regime": regime
        }
        indicators.update(regime_details)

        # SELL signals work in any regime
        if price > upper and rsi > 70:
            return "SELL", 80, indicators
        elif price > upper or rsi > 65:
            return "SELL", 60, indicators

        # BUY signals BLOCKED in BEAR regime
        if regime == "BEAR":
            indicators["Blocked"] = "BUY blocked - BEAR regime"
            return "HOLD", 0, indicators

        # BUY signals in BULL or NEUTRAL regime only
        if price < lower and rsi < 30:
            return "BUY", 80, indicators
        elif price < lower or rsi < 35:
            return "BUY", 60, indicators

        return "HOLD", 0, indicators

    def _model_v9_momentum(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """V9.0 Momentum - Follow strong moves with volume

        REGIME FILTER: Only BUY in BULL or NEUTRAL regime (never in BEAR)
        """
        if len(closes) < 30:
            return "HOLD", 0, {}

        mom5 = self._calculate_momentum(closes, 5)
        mom20 = self._calculate_momentum(closes, 20)
        vol_ratio = self._calculate_volume_ratio(volumes, 20) if volumes else 1.0
        rsi = self._calculate_rsi(closes)
        regime, regime_details = self._get_regime(closes)

        indicators = {
            "Mom_5d": f"{mom5:+.1f}%",
            "Mom_20d": f"{mom20:+.1f}%",
            "Volume_Ratio": round(vol_ratio, 2),
            "RSI": round(rsi, 1),
            "Regime": regime
        }
        indicators.update(regime_details)

        # SELL signals work in any regime
        if mom5 < -3 and mom20 < 0 and vol_ratio > 1.2 and rsi > 30:
            return "SELL", min(70 + abs(mom5) * 2, 100), indicators
        elif mom5 < -2 and mom20 < 0:
            return "SELL", 50, indicators

        # BUY signals BLOCKED in BEAR regime
        if regime == "BEAR":
            indicators["Blocked"] = "BUY blocked - BEAR regime"
            return "HOLD", 0, indicators

        # BUY signals in BULL or NEUTRAL regime only
        if mom5 > 3 and mom20 > 0 and vol_ratio > 1.2 and rsi < 70:
            return "BUY", min(70 + mom5 * 2, 100), indicators
        elif mom5 > 2 and mom20 > 0:
            return "BUY", 50, indicators

        return "HOLD", 0, indicators

    def _model_v11_buy_dip(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """V11.0 Buy The Dip - Buy pullbacks in uptrends

        FIXED: All BUY signals now require uptrend confirmation
        REGIME: Uses regime filter to block buys in BEAR markets
        """
        if len(closes) < 50:
            return "HOLD", 0, {}

        price = closes[-1]
        recent_high = max(closes[-20:])
        pullback = (recent_high - price) / recent_high * 100
        rsi = self._calculate_rsi(closes)
        sma50 = self._calculate_sma(closes, 50)
        regime, regime_details = self._get_regime(closes)

        # STRICT uptrend check: price must be ABOVE SMA50 (not 5% below)
        uptrend = price > sma50

        indicators = {
            "Pullback": f"{pullback:.1f}%",
            "20d_High": round(recent_high, 2),
            "RSI": round(rsi, 1),
            "SMA50": round(sma50, 2),
            "Uptrend": "Yes" if uptrend else "No",
            "Regime": regime
        }
        indicators.update(regime_details)

        # SELL signals work in any regime
        if pullback < 1 and rsi > 70:
            return "SELL", 70, indicators
        elif rsi > 75:
            return "SELL", 60, indicators

        # BUY signals BLOCKED in BEAR regime
        if regime == "BEAR":
            indicators["Blocked"] = "BUY blocked - BEAR regime"
            return "HOLD", 0, indicators

        # ALL BUY signals require uptrend (FIXED: removed bug at line 415)
        if not uptrend:
            indicators["Blocked"] = "BUY blocked - not in uptrend"
            return "HOLD", 0, indicators

        # BUY signals in uptrend only
        if pullback >= 8 and pullback <= 15 and rsi < 40:
            return "BUY", 85, indicators
        elif pullback >= 5 and pullback <= 12 and rsi < 45:
            return "BUY", 70, indicators
        elif pullback >= 3 and rsi < 40:
            return "BUY", 55, indicators

        return "HOLD", 0, indicators

    def _model_v12_support_resistance(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """V12.0 Support/Resistance - Trade bounces from key levels"""
        if len(closes) < 60:
            return "HOLD", 0, {}

        price = closes[-1]
        recent = closes[-60:]

        # Find pivot points
        pivots_high = []
        pivots_low = []

        for i in range(5, len(recent) - 5):
            if recent[i] == max(recent[i-5:i+6]):
                pivots_high.append(recent[i])
            if recent[i] == min(recent[i-5:i+6]):
                pivots_low.append(recent[i])

        if not pivots_high or not pivots_low:
            return "HOLD", 0, {}

        nearest_support = max([p for p in pivots_low if p < price], default=price * 0.95)
        nearest_resistance = min([p for p in pivots_high if p > price], default=price * 1.05)

        dist_to_support = (price - nearest_support) / price * 100
        dist_to_resistance = (nearest_resistance - price) / price * 100

        rsi = self._calculate_rsi(closes)

        indicators = {
            "Support": round(nearest_support, 2),
            "Resistance": round(nearest_resistance, 2),
            "Dist_Support": f"{dist_to_support:.1f}%",
            "Dist_Resistance": f"{dist_to_resistance:.1f}%",
            "RSI": round(rsi, 1)
        }

        if dist_to_support < 2 and rsi < 45:
            return "BUY", 75, indicators
        elif dist_to_support < 3 and rsi < 40:
            return "BUY", 60, indicators
        elif dist_to_resistance < 2 and rsi > 55:
            return "SELL", 75, indicators
        elif dist_to_resistance < 3 and rsi > 60:
            return "SELL", 60, indicators

        return "HOLD", 0, indicators

    def _model_v13_rsi_divergence(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """V13.0 RSI Divergence - Look for price/RSI divergences"""
        if len(closes) < 30:
            return "HOLD", 0, {}

        # Calculate RSI history
        rsi_values = []
        for i in range(20, len(closes) + 1):
            rsi_values.append(self._calculate_rsi(closes[:i]))

        if len(rsi_values) < 10:
            return "HOLD", 0, {}

        recent_prices = closes[-10:]
        recent_rsi = rsi_values[-10:]

        current_rsi = rsi_values[-1]

        # Check for divergences
        price_making_lows = recent_prices[-1] < min(recent_prices[:-1])
        rsi_making_higher = current_rsi > min(recent_rsi[:-1])

        price_making_highs = recent_prices[-1] > max(recent_prices[:-1])
        rsi_making_lower = current_rsi < max(recent_rsi[:-1])

        indicators = {
            "RSI": round(current_rsi, 1),
            "RSI_10d_Low": round(min(recent_rsi), 1),
            "RSI_10d_High": round(max(recent_rsi), 1),
            "Bullish_Div": "Yes" if (price_making_lows and rsi_making_higher) else "No",
            "Bearish_Div": "Yes" if (price_making_highs and rsi_making_lower) else "No"
        }

        # Bullish divergence
        if price_making_lows and rsi_making_higher and current_rsi < 45:
            return "BUY", 70, indicators

        # Bearish divergence
        if price_making_highs and rsi_making_lower and current_rsi > 55:
            return "SELL", 70, indicators

        # Simple RSI signals
        if current_rsi < 30:
            return "BUY", 60, indicators
        elif current_rsi > 70:
            return "SELL", 60, indicators

        return "HOLD", 0, indicators

    def _model_v14_volume_price(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """V14.0 Volume-Price - Volume precedes price moves

        REGIME FILTER: Only BUY in BULL or NEUTRAL regime (never in BEAR)
        """
        if len(closes) < 30 or not volumes or len(volumes) < 30:
            return "HOLD", 0, {}

        price = closes[-1]
        prev_price = closes[-2]
        price_change = (price - prev_price) / prev_price * 100

        avg_volume = sum(volumes[-20:]) / 20
        current_volume = volumes[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

        vol_3d_avg = sum(volumes[-3:]) / 3
        vol_prior_avg = sum(volumes[-6:-3]) / 3
        volume_expanding = vol_3d_avg > vol_prior_avg * 1.2

        rsi = self._calculate_rsi(closes)
        regime, regime_details = self._get_regime(closes)

        indicators = {
            "Price_Change": f"{price_change:+.2f}%",
            "Volume_Ratio": round(volume_ratio, 2),
            "Volume_Expanding": "Yes" if volume_expanding else "No",
            "RSI": round(rsi, 1),
            "Regime": regime
        }
        indicators.update(regime_details)

        # SELL signals work in any regime
        if volume_ratio > 1.5 and price_change < -1 and rsi > 35:
            return "SELL", 75, indicators
        elif volume_ratio > 1.3 and price_change < -0.5 and volume_expanding and rsi > 40:
            return "SELL", 60, indicators

        # BUY signals BLOCKED in BEAR regime
        if regime == "BEAR":
            indicators["Blocked"] = "BUY blocked - BEAR regime"
            return "HOLD", 0, indicators

        # BUY signals in BULL or NEUTRAL regime only
        if volume_ratio > 1.5 and price_change > 1 and rsi < 65:
            return "BUY", 75, indicators
        elif volume_ratio > 1.3 and price_change > 0.5 and volume_expanding and rsi < 60:
            return "BUY", 60, indicators

        return "HOLD", 0, indicators

    # ============================================================
    # MODEL REGISTRY
    # ============================================================

    def _get_all_models(self) -> Dict:
        """Return all available models"""
        return {
            "V1.0 RSI/EMA": self._model_v1_rsi_ema,
            "V6.0 Ensemble": self._model_v6_ensemble,
            "V7.0 Trend Follow": self._model_v7_trend_follow,
            "V8.0 Mean Reversion": self._model_v8_mean_reversion,
            "V9.0 Momentum": self._model_v9_momentum,
            "V11.0 Buy Dip": self._model_v11_buy_dip,
            "V12.0 Support/Resist": self._model_v12_support_resistance,
            "V13.0 RSI Divergence": self._model_v13_rsi_divergence,
            "V14.0 Volume-Price": self._model_v14_volume_price,
        }

    # ============================================================
    # BACKTESTING ENGINE
    # ============================================================

    def _backtest_model(self, model_func, closes: List[float],
                        volumes: List[float]) -> ModelResult:
        """Backtest a single model on historical data"""

        results = []
        min_lookback = 90

        for i in range(min_lookback, len(closes) - 7):
            hist_closes = closes[:i+1]
            hist_volumes = volumes[:i+1] if volumes else []
            entry_price = closes[i]

            # Forward returns
            exit_7d = closes[min(i + 7, len(closes) - 1)]
            exit_14d = closes[min(i + 14, len(closes) - 1)]
            return_7d = ((exit_7d - entry_price) / entry_price) * 100
            return_14d = ((exit_14d - entry_price) / entry_price) * 100

            # Get signal
            signal, strength, _ = model_func(hist_closes, hist_volumes)

            # Check correctness
            if signal == "BUY":
                correct_7d = return_7d > 0
                correct_14d = return_14d > 0
            elif signal == "SELL":
                correct_7d = return_7d < 0
                correct_14d = return_14d < 0
            else:
                correct_7d = abs(return_7d) < 5
                correct_14d = abs(return_14d) < 5

            results.append({
                "signal": signal,
                "return_7d": return_7d,
                "correct_7d": correct_7d,
                "correct_14d": correct_14d
            })

        # Calculate metrics
        directional = [r for r in results if r["signal"] in ["BUY", "SELL"]]
        buys = [r for r in results if r["signal"] == "BUY"]
        sells = [r for r in results if r["signal"] == "SELL"]

        if directional:
            win_rate_7d = sum(1 for r in directional if r["correct_7d"]) / len(directional) * 100
            win_rate_14d = sum(1 for r in directional if r["correct_14d"]) / len(directional) * 100
        else:
            win_rate_7d = win_rate_14d = 50.0

        avg_return = sum(r["return_7d"] for r in buys) / len(buys) if buys else 0

        return ModelResult(
            model_name="",  # Will be set by caller
            win_rate_7d=round(win_rate_7d, 1),
            win_rate_14d=round(win_rate_14d, 1),
            avg_return=round(avg_return, 2),
            total_signals=len(directional),
            buy_signals=len(buys),
            sell_signals=len(sells)
        )

    # ============================================================
    # MAIN PUBLIC METHODS
    # ============================================================

    def find_best_model(self, ticker: str, closes: List[float],
                        volumes: List[float]) -> Tuple[str, float, Dict]:
        """
        Backtest all models and return the best one for this ticker.

        Returns:
            (best_model_name, win_rate, all_results)
        """
        models = self._get_all_models()
        results = {}

        for model_name, model_func in models.items():
            try:
                result = self._backtest_model(model_func, closes, volumes)
                result.model_name = model_name
                results[model_name] = result
            except Exception as e:
                print(f"Error testing {model_name}: {e}")
                continue

        # Find best model by win rate (with minimum signal threshold)
        valid_results = {k: v for k, v in results.items() if v.total_signals >= 10}

        if not valid_results:
            # Fallback to V1.0 if no valid results
            return "V1.0 RSI/EMA", 50.0, results

        best_model = max(valid_results.items(), key=lambda x: x[1].win_rate_7d)

        # Cache the result
        self.best_models[ticker] = best_model[0]

        return best_model[0], best_model[1].win_rate_7d, results

    def get_signal(self, ticker: str, closes: List[float],
                   volumes: List[float], auto_select: bool = True,
                   position_value: float = 0.0, shares: float = 0.0) -> Signal:
        """
        Get trading signal using the best model for this ticker.

        Args:
            ticker: Stock symbol
            closes: List of closing prices
            volumes: List of volumes
            auto_select: If True, automatically find best model first
            position_value: Current position value for fee calculation
            shares: Number of shares held (used if position_value not provided)

        Returns:
            Signal object with recommendation (fee-adjusted)
        """
        # Find best model if not already cached
        if auto_select or ticker not in self.best_models:
            best_model_name, accuracy, _ = self.find_best_model(ticker, closes, volumes)
        else:
            best_model_name = self.best_models[ticker]
            accuracy = 0  # Will be set from cache

        # Get the model function
        models = self._get_all_models()
        model_func = models[best_model_name]

        # Generate signal
        signal, strength, indicators = model_func(closes, volumes)

        # Calculate position value if not provided
        current_price = closes[-1] if closes else 0
        if position_value <= 0 and shares > 0:
            position_value = shares * current_price

        # Calculate fee impact
        fee_impact = self.calculate_fee_impact(position_value)
        min_move_pct = fee_impact["min_move_pct"]

        # Determine if trade is worth making after fees
        trade_analysis = self.should_trade(
            position_value,
            win_rate=accuracy / 100 if accuracy > 0 else 0.5
        )

        # Apply fee filter to signal
        net_signal = signal
        fee_adjusted = False

        if signal in ["BUY", "SELL"] and position_value > 0:
            if not trade_analysis["should_trade"]:
                # Downgrade signal if not profitable after fees
                net_signal = "HOLD"
                fee_adjusted = True
                indicators["fee_warning"] = f"Signal filtered: {trade_analysis['reason']}"
            else:
                indicators["fee_ok"] = f"Min move needed: {min_move_pct:.2f}%"

        # Generate reasoning
        if signal == "BUY":
            reasoning = f"{best_model_name} ({accuracy:.1f}% accurate) indicates BUY conditions"
            if fee_adjusted:
                reasoning += f" [FILTERED: Position ${position_value:.0f} needs >{min_move_pct:.2f}% move]"
        elif signal == "SELL":
            reasoning = f"{best_model_name} ({accuracy:.1f}% accurate) indicates SELL conditions"
            if fee_adjusted:
                reasoning += f" [FILTERED: Position ${position_value:.0f} needs >{min_move_pct:.2f}% move]"
        else:
            reasoning = f"{best_model_name} ({accuracy:.1f}% accurate) shows no clear signal - HOLD"

        return Signal(
            ticker=ticker,
            model_used=best_model_name,
            model_accuracy=accuracy,
            signal=signal,
            strength=strength,
            indicators=indicators,
            reasoning=reasoning,
            position_value=position_value,
            min_move_pct=min_move_pct,
            fee_adjusted=fee_adjusted,
            net_signal=net_signal
        )


def analyze_portfolio(tickers: List[str], historical_data: Dict,
                      positions: Dict) -> Dict:
    """
    Analyze entire portfolio using hybrid model selection.

    Args:
        tickers: List of stock symbols
        historical_data: Dict with closes/volumes per ticker
        positions: Dict with shares/avg_entry per ticker

    Returns:
        Complete analysis with signals and recommendations (fee-adjusted)
    """
    selector = HybridModelSelector()
    results = {}
    total_fees_if_all_trade = 0

    for ticker in tickers:
        data = historical_data.get(ticker)
        if not data:
            continue

        closes = data["closes"]
        volumes = data["volumes"]

        # Find best model
        best_model, accuracy, all_results = selector.find_best_model(ticker, closes, volumes)

        # Calculate position value for fee analysis
        pos = positions.get(ticker, {})
        current_price = closes[-1]
        entry_price = pos.get("avg_entry", current_price)
        shares = pos.get("shares", 0)
        position_value = shares * current_price

        # Get signal (with fee awareness)
        signal = selector.get_signal(
            ticker, closes, volumes,
            auto_select=False,
            position_value=position_value,
            shares=shares
        )

        # Calculate P&L
        pnl = (current_price - entry_price) * shares
        pnl_pct = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0

        # Fee analysis
        fee_impact = selector.calculate_fee_impact(position_value)
        total_fees_if_all_trade += ROUND_TRIP_COST if signal.signal in ["BUY", "SELL"] else 0

        results[ticker] = {
            "ticker": ticker,
            "current_price": round(current_price, 2),
            "entry_price": entry_price,
            "shares": shares,
            "position_value": round(position_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "best_model": best_model,
            "model_accuracy": accuracy,
            "signal": signal.signal,
            "net_signal": signal.net_signal,  # Fee-adjusted signal
            "fee_adjusted": signal.fee_adjusted,
            "min_move_pct": signal.min_move_pct,
            "strength": signal.strength,
            "indicators": signal.indicators,
            "reasoning": signal.reasoning,
            "fee_analysis": fee_impact,
            "all_model_results": {k: {"win_rate": v.win_rate_7d, "signals": v.total_signals}
                                  for k, v in all_results.items()}
        }

    # Add portfolio-level fee summary
    total_value = sum(r["position_value"] for r in results.values())
    results["_fee_summary"] = {
        "transaction_cost_per_trade": TRANSACTION_COST_PER_TRADE,
        "round_trip_cost": ROUND_TRIP_COST,
        "min_profit_threshold": MIN_PROFIT_THRESHOLD,
        "total_portfolio_value": round(total_value, 2),
        "total_fees_if_all_rotate": round(total_fees_if_all_trade, 2),
        "fee_pct_of_portfolio": round((total_fees_if_all_trade / total_value) * 100, 3) if total_value > 0 else 0
    }

    return results


# ============================================================
# MAIN EXECUTION
# ============================================================

if __name__ == "__main__":
    # Load data
    with open("data/historical_backtest.json", "r") as f:
        historical_data = json.load(f)

    positions = {
        "VST": {"shares": 7.9038, "avg_entry": 169.58},
        "LLY": {"shares": 1, "avg_entry": 1080.50},
        "MRVL": {"shares": 9, "avg_entry": 86.50}
    }

    results = analyze_portfolio(["VST", "LLY", "MRVL"], historical_data, positions)

    print(json.dumps(results, indent=2))
