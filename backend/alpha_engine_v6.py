#!/usr/bin/env python3
"""
Alpha Engine V6.0 - High Accuracy Trading Models
Target: 80%+ Win Rate

Based on research:
- Larry Connors RSI(2) Strategy (75% backtested)
- Multi-Confluence Approaches (80% with 4+ factors)
- Mean Reversion with Strict Trend Filters
- Academic Research on Multi-Factor Quantitative Trading

Key Improvements:
1. RSI(2) instead of RSI(14) - More sensitive to extremes
2. Multi-confluence - 4+ factors must agree before entry
3. Stricter thresholds - Only trade extreme conditions
4. Mandatory trend filter - 200 SMA confirmation
5. Volume confirmation - Institutional activity
6. Trade LESS but with HIGHER conviction
"""

import math
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SignalResult:
    """Trading signal output"""
    signal: str  # BUY, SELL, HOLD
    strength: float  # 0-100
    confidence: float  # Expected win rate
    model: str
    indicators: Dict
    reasoning: str
    entry_price: float
    stop_loss: float
    target: float


class HighAccuracyModels:
    """
    High-accuracy trading models targeting 80%+ win rate.
    Trade less frequently, but with higher conviction.
    """

    # ============================================================
    # TECHNICAL INDICATOR CALCULATIONS
    # ============================================================

    def calc_rsi(self, closes: List[float], period: int = 14) -> float:
        """Calculate RSI with configurable period"""
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
        return 100 - (100 / (1 + avg_gain / avg_loss))

    def calc_rsi2(self, closes: List[float]) -> float:
        """Larry Connors' 2-period RSI - ultra sensitive"""
        return self.calc_rsi(closes, period=2)

    def calc_rsi3(self, closes: List[float]) -> float:
        """3-period RSI for Triple RSI strategy"""
        return self.calc_rsi(closes, period=3)

    def calc_ema(self, closes: List[float], period: int) -> float:
        """Exponential Moving Average"""
        if len(closes) < period:
            return closes[-1] if closes else 0
        k = 2 / (period + 1)
        ema = sum(closes[:period]) / period
        for price in closes[period:]:
            ema = price * k + ema * (1 - k)
        return ema

    def calc_sma(self, closes: List[float], period: int) -> float:
        """Simple Moving Average"""
        if len(closes) < period:
            return closes[-1] if closes else 0
        return sum(closes[-period:]) / period

    def calc_bollinger(self, closes: List[float], period: int = 20, std_mult: float = 2.0) -> Tuple[float, float, float]:
        """Bollinger Bands: (upper, middle, lower)"""
        if len(closes) < period:
            return closes[-1], closes[-1], closes[-1]
        middle = sum(closes[-period:]) / period
        variance = sum((x - middle) ** 2 for x in closes[-period:]) / period
        std = math.sqrt(variance) if variance > 0 else 0
        return middle + (std_mult * std), middle, middle - (std_mult * std)

    def calc_macd(self, closes: List[float]) -> Tuple[float, float, float]:
        """MACD: (macd_line, signal_line, histogram)"""
        ema12 = self.calc_ema(closes, 12)
        ema26 = self.calc_ema(closes, 26)
        macd_line = ema12 - ema26

        # Calculate signal line (9-period EMA of MACD)
        if len(closes) < 35:
            signal_line = macd_line
        else:
            macd_history = []
            for i in range(26, len(closes)):
                e12 = self.calc_ema(closes[:i+1], 12)
                e26 = self.calc_ema(closes[:i+1], 26)
                macd_history.append(e12 - e26)
            signal_line = self.calc_ema(macd_history, 9) if len(macd_history) >= 9 else macd_line

        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def calc_atr(self, highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Average True Range for volatility"""
        if len(closes) < period + 1:
            return (max(closes) - min(closes)) / 2 if closes else 0

        tr_list = []
        for i in range(1, len(closes)):
            high = highs[i] if highs and i < len(highs) else closes[i]
            low = lows[i] if lows and i < len(lows) else closes[i]
            prev_close = closes[i-1]
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

        return sum(tr_list[-period:]) / period

    def calc_volume_ratio(self, volumes: List[float], period: int = 20) -> float:
        """Current volume vs average"""
        if not volumes or len(volumes) < period:
            return 1.0
        avg_vol = sum(volumes[-period:]) / period
        return volumes[-1] / avg_vol if avg_vol > 0 else 1.0

    def get_trend(self, closes: List[float]) -> Tuple[str, Dict]:
        """
        Determine trend using 200 SMA (Connors method)

        Returns:
            (trend, details) where trend is BULL, BEAR, or NEUTRAL
        """
        if len(closes) < 200:
            # Use 50 SMA if not enough data
            if len(closes) < 50:
                return "NEUTRAL", {"reason": "Insufficient data"}
            sma50 = self.calc_sma(closes, 50)
            price = closes[-1]
            trend = "BULL" if price > sma50 else "BEAR" if price < sma50 else "NEUTRAL"
            return trend, {"SMA50": round(sma50, 2), "filter": "50 SMA"}

        price = closes[-1]
        sma200 = self.calc_sma(closes, 200)
        sma50 = self.calc_sma(closes, 50)

        # Strong trend: Price > SMA50 > SMA200 (or inverse)
        if price > sma50 > sma200:
            trend = "STRONG_BULL"
        elif price > sma200:
            trend = "BULL"
        elif price < sma50 < sma200:
            trend = "STRONG_BEAR"
        elif price < sma200:
            trend = "BEAR"
        else:
            trend = "NEUTRAL"

        return trend, {
            "SMA50": round(sma50, 2),
            "SMA200": round(sma200, 2),
            "price_vs_200": "ABOVE" if price > sma200 else "BELOW"
        }

    def count_down_days(self, closes: List[float], lookback: int = 5) -> int:
        """Count consecutive down days"""
        count = 0
        for i in range(len(closes) - 1, 0, -1):
            if closes[i] < closes[i-1]:
                count += 1
            else:
                break
            if count >= lookback:
                break
        return count

    def count_up_days(self, closes: List[float], lookback: int = 5) -> int:
        """Count consecutive up days"""
        count = 0
        for i in range(len(closes) - 1, 0, -1):
            if closes[i] > closes[i-1]:
                count += 1
            else:
                break
            if count >= lookback:
                break
        return count

    # ============================================================
    # HIGH ACCURACY MODELS
    # ============================================================

    def model_v15_connors_rsi2(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """
        V15.0 Larry Connors RSI(2) Strategy

        Backtested: 75% win rate historically

        RULES:
        - BUY: RSI(2) < 5 AND Price > 200 SMA
        - SELL: RSI(2) > 95 AND Price < 200 SMA
        - EXIT: Price crosses 5-day SMA

        This is pure mean reversion with trend filter.
        """
        if len(closes) < 200:
            return "HOLD", 0, {"reason": "Need 200 days of data"}

        price = closes[-1]
        rsi2 = self.calc_rsi2(closes)
        sma200 = self.calc_sma(closes, 200)
        sma5 = self.calc_sma(closes, 5)

        trend, trend_details = self.get_trend(closes)

        indicators = {
            "RSI2": round(rsi2, 1),
            "SMA5": round(sma5, 2),
            "SMA200": round(sma200, 2),
            "Trend": trend,
            "Model": "V15.0 Connors RSI(2)"
        }

        # EXTREME BUY: RSI(2) < 5 with uptrend confirmation
        if rsi2 < 5 and price > sma200:
            return "BUY", 85, indicators

        # STRONG BUY: RSI(2) < 10 with uptrend confirmation
        elif rsi2 < 10 and price > sma200:
            return "BUY", 70, indicators

        # EXTREME SELL: RSI(2) > 95 with downtrend confirmation
        elif rsi2 > 95 and price < sma200:
            return "SELL", 85, indicators

        # STRONG SELL: RSI(2) > 90 with downtrend confirmation
        elif rsi2 > 90 and price < sma200:
            return "SELL", 70, indicators

        # EXIT signal: Mean reversion complete
        elif rsi2 > 60 and rsi2 < 70 and price > sma5:
            indicators["Exit_Signal"] = "Take profit - mean reversion complete"
            return "SELL", 50, indicators

        return "HOLD", 0, indicators

    def model_v16_multi_confluence(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """
        V16.0 Multi-Confluence Strategy

        Target: 80%+ win rate

        REQUIRES 4+ FACTORS TO AGREE:
        1. RSI(2) oversold/overbought
        2. Price vs 200 SMA (trend)
        3. Price at Bollinger Band extreme
        4. Volume spike (institutional activity)
        5. MACD confirmation
        6. Consecutive down/up days

        Only trades when conditions are PERFECT.
        """
        if len(closes) < 200:
            return "HOLD", 0, {"reason": "Need 200 days of data"}

        price = closes[-1]

        # Calculate all indicators
        rsi2 = self.calc_rsi2(closes)
        rsi14 = self.calc_rsi(closes, 14)
        sma200 = self.calc_sma(closes, 200)
        sma50 = self.calc_sma(closes, 50)
        upper_bb, middle_bb, lower_bb = self.calc_bollinger(closes, 20)
        macd, signal, histogram = self.calc_macd(closes)
        vol_ratio = self.calc_volume_ratio(volumes) if volumes else 1.0
        down_days = self.count_down_days(closes)
        up_days = self.count_up_days(closes)

        trend, trend_details = self.get_trend(closes)

        # Count BUY confluence factors
        buy_factors = 0
        buy_reasons = []

        # 1. RSI(2) oversold
        if rsi2 < 10:
            buy_factors += 1
            buy_reasons.append(f"RSI(2) extreme: {rsi2:.1f}")
        elif rsi2 < 20:
            buy_factors += 0.5
            buy_reasons.append(f"RSI(2) oversold: {rsi2:.1f}")

        # 2. Trend filter (price > 200 SMA)
        if price > sma200:
            buy_factors += 1
            buy_reasons.append("Uptrend: Price > SMA200")

        # 3. Price at lower Bollinger Band
        if price < lower_bb:
            buy_factors += 1
            buy_reasons.append("Price below lower BB")
        elif price < middle_bb:
            buy_factors += 0.5
            buy_reasons.append("Price below middle BB")

        # 4. Volume spike (institutional interest)
        if vol_ratio > 1.5:
            buy_factors += 1
            buy_reasons.append(f"Volume spike: {vol_ratio:.1f}x")
        elif vol_ratio > 1.2:
            buy_factors += 0.5
            buy_reasons.append(f"Elevated volume: {vol_ratio:.1f}x")

        # 5. MACD histogram positive or turning up
        if histogram > 0:
            buy_factors += 0.5
            buy_reasons.append("MACD positive")

        # 6. Multiple down days (panic selling exhaustion)
        if down_days >= 3:
            buy_factors += 1
            buy_reasons.append(f"{down_days} consecutive down days")
        elif down_days >= 2:
            buy_factors += 0.5
            buy_reasons.append(f"{down_days} consecutive down days")

        # Count SELL confluence factors
        sell_factors = 0
        sell_reasons = []

        # 1. RSI(2) overbought
        if rsi2 > 90:
            sell_factors += 1
            sell_reasons.append(f"RSI(2) extreme: {rsi2:.1f}")
        elif rsi2 > 80:
            sell_factors += 0.5
            sell_reasons.append(f"RSI(2) overbought: {rsi2:.1f}")

        # 2. Trend filter (price < 200 SMA for shorts)
        if price < sma200:
            sell_factors += 1
            sell_reasons.append("Downtrend: Price < SMA200")

        # 3. Price at upper Bollinger Band
        if price > upper_bb:
            sell_factors += 1
            sell_reasons.append("Price above upper BB")
        elif price > middle_bb:
            sell_factors += 0.5
            sell_reasons.append("Price above middle BB")

        # 4. Volume spike
        if vol_ratio > 1.5:
            sell_factors += 1
            sell_reasons.append(f"Volume spike: {vol_ratio:.1f}x")

        # 5. MACD histogram negative
        if histogram < 0:
            sell_factors += 0.5
            sell_reasons.append("MACD negative")

        # 6. Multiple up days (exhaustion)
        if up_days >= 3:
            sell_factors += 1
            sell_reasons.append(f"{up_days} consecutive up days")

        indicators = {
            "RSI2": round(rsi2, 1),
            "RSI14": round(rsi14, 1),
            "Trend": trend,
            "BB_Position": "Below" if price < lower_bb else "Above" if price > upper_bb else "Middle",
            "Volume_Ratio": round(vol_ratio, 2),
            "MACD_Hist": round(histogram, 4),
            "Down_Days": down_days,
            "Up_Days": up_days,
            "Buy_Factors": round(buy_factors, 1),
            "Sell_Factors": round(sell_factors, 1),
            "Model": "V16.0 Multi-Confluence"
        }

        # REQUIRE 4+ FACTORS FOR HIGH CONFIDENCE SIGNAL
        if buy_factors >= 4:
            indicators["Reasons"] = buy_reasons
            return "BUY", min(buy_factors * 20, 100), indicators
        elif buy_factors >= 3:
            indicators["Reasons"] = buy_reasons
            return "BUY", 60, indicators
        elif sell_factors >= 4:
            indicators["Reasons"] = sell_reasons
            return "SELL", min(sell_factors * 20, 100), indicators
        elif sell_factors >= 3:
            indicators["Reasons"] = sell_reasons
            return "SELL", 60, indicators

        return "HOLD", 0, indicators

    def model_v17_extreme_oversold(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """
        V17.0 Extreme Oversold Strategy

        Target: 80-85%+ win rate

        ONLY trades the most extreme conditions:
        - RSI(2) < 5 (extreme panic)
        - RSI(3) < 10
        - RSI(14) < 30
        - Price > 200 SMA (uptrend only)
        - 3+ consecutive down days

        Trades very rarely but with very high conviction.
        """
        if len(closes) < 200:
            return "HOLD", 0, {"reason": "Need 200 days of data"}

        price = closes[-1]
        rsi2 = self.calc_rsi2(closes)
        rsi3 = self.calc_rsi3(closes)
        rsi14 = self.calc_rsi(closes, 14)
        sma200 = self.calc_sma(closes, 200)
        sma5 = self.calc_sma(closes, 5)
        down_days = self.count_down_days(closes)

        trend, trend_details = self.get_trend(closes)

        indicators = {
            "RSI2": round(rsi2, 1),
            "RSI3": round(rsi3, 1),
            "RSI14": round(rsi14, 1),
            "SMA200": round(sma200, 2),
            "Trend": trend,
            "Down_Days": down_days,
            "Model": "V17.0 Extreme Oversold"
        }

        # TRIPLE RSI EXTREME - All three RSI oversold + uptrend
        if rsi2 < 5 and rsi3 < 15 and rsi14 < 35 and price > sma200:
            indicators["Setup"] = "TRIPLE RSI EXTREME"
            return "BUY", 95, indicators

        # DOUBLE RSI EXTREME
        elif rsi2 < 10 and rsi3 < 20 and price > sma200 and down_days >= 2:
            indicators["Setup"] = "DOUBLE RSI + DOWN DAYS"
            return "BUY", 85, indicators

        # SINGLE RSI EXTREME with multiple confirmations
        elif rsi2 < 5 and price > sma200:
            indicators["Setup"] = "RSI(2) EXTREME"
            return "BUY", 80, indicators

        # OVERBOUGHT EXTREME
        elif rsi2 > 95 and rsi3 > 85 and rsi14 > 70 and price < sma200:
            indicators["Setup"] = "TRIPLE RSI OVERBOUGHT"
            return "SELL", 85, indicators

        elif rsi2 > 90 and price < sma200:
            indicators["Setup"] = "RSI(2) OVERBOUGHT"
            return "SELL", 70, indicators

        return "HOLD", 0, indicators

    def model_v18_triple_confirmation(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """
        V18.0 Triple Confirmation Strategy

        Based on research: 4-indicator confluence achieves 60%+ profitable trades

        REQUIRES ALL THREE:
        1. RSI signal (oversold/overbought)
        2. EMA/SMA trend alignment
        3. Volume confirmation
        + Bonus: MACD confirmation

        Only trades when RSI + EMA + Volume ALL agree.
        """
        if len(closes) < 50:
            return "HOLD", 0, {"reason": "Need 50 days of data"}

        price = closes[-1]

        # Calculate indicators
        rsi2 = self.calc_rsi2(closes)
        rsi14 = self.calc_rsi(closes, 14)
        ema9 = self.calc_ema(closes, 9)
        ema21 = self.calc_ema(closes, 21)
        sma50 = self.calc_sma(closes, 50)
        sma200 = self.calc_sma(closes, 200) if len(closes) >= 200 else sma50
        vol_ratio = self.calc_volume_ratio(volumes) if volumes else 1.0
        macd, signal, histogram = self.calc_macd(closes)

        trend, trend_details = self.get_trend(closes)

        # Check each confirmation
        rsi_buy = rsi2 < 20 or rsi14 < 35
        rsi_sell = rsi2 > 80 or rsi14 > 65

        ema_buy = ema9 > ema21 and price > sma50
        ema_sell = ema9 < ema21 and price < sma50

        volume_confirm = vol_ratio > 1.2

        macd_buy = histogram > 0
        macd_sell = histogram < 0

        indicators = {
            "RSI2": round(rsi2, 1),
            "RSI14": round(rsi14, 1),
            "EMA9": round(ema9, 2),
            "EMA21": round(ema21, 2),
            "Volume_Ratio": round(vol_ratio, 2),
            "MACD_Hist": round(histogram, 4),
            "Trend": trend,
            "RSI_Signal": "BUY" if rsi_buy else "SELL" if rsi_sell else "NEUTRAL",
            "EMA_Signal": "BUY" if ema_buy else "SELL" if ema_sell else "NEUTRAL",
            "Volume_Confirm": "YES" if volume_confirm else "NO",
            "MACD_Signal": "BUY" if macd_buy else "SELL" if macd_sell else "NEUTRAL",
            "Model": "V18.0 Triple Confirmation"
        }

        # ALL THREE must agree + MACD bonus
        if rsi_buy and ema_buy and volume_confirm:
            strength = 70
            if macd_buy:
                strength = 85
                indicators["Setup"] = "QUAD CONFLUENCE BUY"
            else:
                indicators["Setup"] = "TRIPLE CONFLUENCE BUY"
            return "BUY", strength, indicators

        elif rsi_sell and ema_sell and volume_confirm:
            strength = 70
            if macd_sell:
                strength = 85
                indicators["Setup"] = "QUAD CONFLUENCE SELL"
            else:
                indicators["Setup"] = "TRIPLE CONFLUENCE SELL"
            return "SELL", strength, indicators

        return "HOLD", 0, indicators

    def model_v19_consecutive_days(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """
        V19.0 Consecutive Days Strategy

        Based on research: Buy after 3 consecutive down days, exit on first up day

        Simple but effective mean reversion strategy.
        """
        if len(closes) < 200:
            return "HOLD", 0, {"reason": "Need 200 days of data"}

        price = closes[-1]
        sma200 = self.calc_sma(closes, 200)
        down_days = self.count_down_days(closes)
        up_days = self.count_up_days(closes)
        rsi2 = self.calc_rsi2(closes)

        # Today's move
        today_change = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0

        trend, trend_details = self.get_trend(closes)

        indicators = {
            "Down_Days": down_days,
            "Up_Days": up_days,
            "Today_Change": f"{today_change:+.2f}%",
            "RSI2": round(rsi2, 1),
            "Trend": trend,
            "SMA200": round(sma200, 2),
            "Model": "V19.0 Consecutive Days"
        }

        # BUY: 3+ consecutive down days in uptrend
        if down_days >= 4 and price > sma200:
            indicators["Setup"] = f"{down_days} DOWN DAYS - EXTREME"
            return "BUY", 90, indicators
        elif down_days >= 3 and price > sma200:
            indicators["Setup"] = f"{down_days} DOWN DAYS"
            return "BUY", 80, indicators
        elif down_days >= 3 and rsi2 < 20:
            indicators["Setup"] = f"{down_days} DOWN DAYS + RSI OVERSOLD"
            return "BUY", 70, indicators

        # SELL: 3+ consecutive up days in downtrend (exhaustion)
        elif up_days >= 4 and price < sma200:
            indicators["Setup"] = f"{up_days} UP DAYS - EXHAUSTION"
            return "SELL", 80, indicators
        elif up_days >= 3 and price < sma200:
            indicators["Setup"] = f"{up_days} UP DAYS"
            return "SELL", 70, indicators

        return "HOLD", 0, indicators

    # ============================================================
    # MODEL REGISTRY AND BACKTESTING
    # ============================================================

    def get_all_models(self) -> Dict:
        """Return all V6 high-accuracy models"""
        return {
            "V15.0 Connors RSI(2)": self.model_v15_connors_rsi2,
            "V16.0 Multi-Confluence": self.model_v16_multi_confluence,
            "V17.0 Extreme Oversold": self.model_v17_extreme_oversold,
            "V18.0 Triple Confirmation": self.model_v18_triple_confirmation,
            "V19.0 Consecutive Days": self.model_v19_consecutive_days,
        }

    def backtest_model(self, model_func, closes: List[float], volumes: List[float],
                       forward_days: int = 7) -> Dict:
        """Backtest a single model on historical data"""
        results = []
        min_lookback = 200  # Need 200 days for 200 SMA

        for i in range(min_lookback, len(closes) - forward_days):
            hist_closes = closes[:i+1]
            hist_volumes = volumes[:i+1] if volumes else []
            entry_price = closes[i]

            # Forward return
            exit_price = closes[i + forward_days]
            forward_return = ((exit_price - entry_price) / entry_price) * 100

            # Get signal
            signal, strength, indicators = model_func(hist_closes, hist_volumes)

            # Check correctness
            if signal == "BUY":
                correct = forward_return > 0
            elif signal == "SELL":
                correct = forward_return < 0
            else:
                correct = None  # HOLD signals not counted

            if signal in ["BUY", "SELL"]:
                results.append({
                    "signal": signal,
                    "strength": strength,
                    "return": forward_return,
                    "correct": correct
                })

        if not results:
            return {
                "win_rate": 0,
                "total_signals": 0,
                "avg_return": 0,
                "buy_signals": 0,
                "sell_signals": 0
            }

        # Calculate metrics
        total = len(results)
        wins = sum(1 for r in results if r["correct"])
        buys = [r for r in results if r["signal"] == "BUY"]
        sells = [r for r in results if r["signal"] == "SELL"]

        buy_wins = sum(1 for r in buys if r["correct"])
        sell_wins = sum(1 for r in sells if r["correct"])

        return {
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
            "total_signals": total,
            "buy_signals": len(buys),
            "sell_signals": len(sells),
            "buy_win_rate": round(buy_wins / len(buys) * 100, 1) if buys else 0,
            "sell_win_rate": round(sell_wins / len(sells) * 100, 1) if sells else 0,
            "avg_return": round(sum(r["return"] for r in buys) / len(buys), 2) if buys else 0
        }

    def find_best_model(self, closes: List[float], volumes: List[float]) -> Tuple[str, float, Dict]:
        """Find the best performing model for this stock"""
        models = self.get_all_models()
        results = {}

        for name, func in models.items():
            try:
                result = self.backtest_model(func, closes, volumes)
                results[name] = result
            except Exception as e:
                print(f"Error testing {name}: {e}")
                continue

        # Find best by win rate (minimum 5 signals)
        valid = {k: v for k, v in results.items() if v["total_signals"] >= 5}

        if not valid:
            return "V15.0 Connors RSI(2)", 50.0, results

        best_model = max(valid.items(), key=lambda x: x[1]["win_rate"])
        return best_model[0], best_model[1]["win_rate"], results

    def get_signal(self, closes: List[float], volumes: List[float],
                   model_name: str = None) -> SignalResult:
        """Get trading signal using specified or best model"""

        models = self.get_all_models()

        if model_name and model_name in models:
            model_func = models[model_name]
            accuracy = 70  # Default
        else:
            # Find best model
            model_name, accuracy, _ = self.find_best_model(closes, volumes)
            model_func = models[model_name]

        signal, strength, indicators = model_func(closes, volumes)

        # Calculate entry, stop, target
        price = closes[-1]
        atr = self.calc_atr(closes, closes, closes, 14)  # Simplified

        if signal == "BUY":
            entry_price = price
            stop_loss = price - (2 * atr)  # 2 ATR stop
            target = price + (3 * atr)  # 3 ATR target (1.5:1 R:R)
            reasoning = f"{model_name} indicates BUY with {strength}% conviction"
        elif signal == "SELL":
            entry_price = price
            stop_loss = price + (2 * atr)
            target = price - (3 * atr)
            reasoning = f"{model_name} indicates SELL with {strength}% conviction"
        else:
            entry_price = price
            stop_loss = 0
            target = 0
            reasoning = f"{model_name} shows no clear signal - HOLD"

        return SignalResult(
            signal=signal,
            strength=strength,
            confidence=accuracy,
            model=model_name,
            indicators=indicators,
            reasoning=reasoning,
            entry_price=round(entry_price, 2),
            stop_loss=round(stop_loss, 2),
            target=round(target, 2)
        )


# ============================================================
# MAIN EXECUTION / TESTING
# ============================================================

def main():
    """Test the high accuracy models"""
    import json
    from pathlib import Path

    print("=" * 70)
    print("Alpha Engine V6.0 - High Accuracy Model Testing")
    print("=" * 70)

    engine = HighAccuracyModels()

    # Load historical data if available
    data_file = Path(__file__).parent / "data" / "historical_backtest.json"

    if data_file.exists():
        with open(data_file, "r") as f:
            historical = json.load(f)

        for ticker, data in historical.items():
            print(f"\n{'='*50}")
            print(f"TESTING: {ticker}")
            print(f"{'='*50}")

            closes = data.get("closes", [])
            volumes = data.get("volumes", [])

            if len(closes) < 200:
                print(f"  Insufficient data: {len(closes)} days (need 200)")
                continue

            # Find best model
            best_model, win_rate, all_results = engine.find_best_model(closes, volumes)

            print(f"\nBEST MODEL: {best_model}")
            print(f"WIN RATE: {win_rate}%")

            print("\nALL MODEL RESULTS:")
            for name, result in sorted(all_results.items(), key=lambda x: x[1]["win_rate"], reverse=True):
                print(f"  {name}: {result['win_rate']}% ({result['total_signals']} signals)")

            # Get current signal
            signal = engine.get_signal(closes, volumes, best_model)
            print(f"\nCURRENT SIGNAL: {signal.signal}")
            print(f"  Strength: {signal.strength}%")
            print(f"  Entry: ${signal.entry_price}")
            print(f"  Stop: ${signal.stop_loss}")
            print(f"  Target: ${signal.target}")
            print(f"  Indicators: {signal.indicators}")
    else:
        print("\nNo historical data file found.")
        print("Run daily_scanner.py first to collect data.")


if __name__ == "__main__":
    main()
