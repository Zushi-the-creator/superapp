"""
Model Backtester
Validates V1.0 (RSI/EMA) and V5.0 (Quant Alpha) models against historical data
Calculates true win rates for proper model weighting
"""

import math
from typing import Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class BacktestResult:
    """Result of a single backtest signal"""
    date: str
    signal: str
    entry_price: float
    exit_price_7d: float
    exit_price_14d: float
    exit_price_30d: float
    return_7d: float
    return_14d: float
    return_30d: float
    correct_7d: bool
    correct_14d: bool
    correct_30d: bool


@dataclass
class ModelPerformance:
    """Aggregated model performance metrics"""
    model_name: str
    total_signals: int
    buy_signals: int
    sell_signals: int
    hold_signals: int
    win_rate_7d: float
    win_rate_14d: float
    win_rate_30d: float
    avg_return_7d: float
    avg_return_14d: float
    avg_return_30d: float
    profit_factor: float  # Total wins / Total losses
    sharpe_ratio: float
    max_drawdown: float


class ModelBacktester:
    """
    Backtests trading models against historical data
    """

    def __init__(self):
        self.results_v1: List[BacktestResult] = []
        self.results_v5: List[BacktestResult] = []

    # ==========================================
    # V1.0 MODEL (RSI/EMA)
    # ==========================================

    def _calculate_rsi(self, closes: List[float], period: int = 14) -> float:
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
        if len(closes) < period:
            return closes[-1] if closes else 0

        k = 2 / (period + 1)
        ema = sum(closes[:period]) / period

        for price in closes[period:]:
            ema = price * k + ema * (1 - k)

        return ema

    def v1_signal(self, closes: List[float]) -> Tuple[str, float]:
        """
        Generate V1.0 (RSI/EMA) signal

        Returns: (signal, strength)
        """
        if len(closes) < 30:
            return "HOLD", 0

        rsi = self._calculate_rsi(closes)
        ema9 = self._calculate_ema(closes, 9)
        ema21 = self._calculate_ema(closes, 21)

        signal = "HOLD"
        strength = 0

        # RSI signals
        if rsi < 30:
            signal = "BUY"
            strength += 40
        elif rsi > 70:
            signal = "SELL"
            strength += 40

        # EMA crossover
        if ema9 > ema21:
            if signal != "SELL":
                signal = "BUY"
            strength += 30
        elif ema9 < ema21:
            if signal != "BUY":
                signal = "SELL"
            strength += 30

        return signal, min(strength, 100)

    # ==========================================
    # V5.0 MODEL (Quantitative Alpha)
    # ==========================================

    def _calculate_z_score(self, current: float, data: List[float], window: int) -> float:
        if len(data) < window:
            window = len(data)
        if window < 2:
            return 0.0

        recent = data[-window:]
        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / len(recent)
        std = math.sqrt(variance) if variance > 0 else 1

        return (current - mean) / std

    def v5_signal(self, closes: List[float], volumes: List[float],
                  analyst_upside: float = 0.10, vix: float = 18.0) -> Tuple[str, float]:
        """
        Generate V5.0 (Quantitative Alpha) signal

        Returns: (signal, confidence)
        """
        if len(closes) < 30:
            return "HOLD", 0

        current_price = closes[-1]
        current_volume = volumes[-1] if volumes else 0

        # Z-Scores
        z_price = self._calculate_z_score(current_price, closes[:-1], 90)
        z_volume = self._calculate_z_score(current_volume, volumes[:-1], 60) if volumes else 0
        z_analyst = analyst_upside * 3  # Scale upside to Z-score equivalent

        # Composite Alpha
        raw_score = (0.5 * z_price) + (0.3 * z_analyst) + (0.2 * z_volume)
        composite_alpha = max(0, min(100, 25 * raw_score + 50))

        # Bayesian regime adjustment
        if vix < 15:
            regime_mult = 1.15
        elif vix < 20:
            regime_mult = 1.0
        elif vix < 30:
            regime_mult = 0.85
        else:
            regime_mult = 0.70

        base_win_rate = 0.55
        bayesian_win_prob = min(0.80, max(0.30, base_win_rate * regime_mult))

        # Confidence
        confidence = min(100, composite_alpha * (bayesian_win_prob / 0.55))

        # Signal
        if composite_alpha >= 75:
            signal = "BUY"  # STRONG_BUY simplified
        elif composite_alpha >= 62.5:
            signal = "BUY"
        elif composite_alpha <= 25:
            signal = "SELL"  # STRONG_SELL simplified
        elif composite_alpha <= 40:
            signal = "SELL"
        else:
            signal = "HOLD"

        return signal, confidence

    # ==========================================
    # BACKTESTING ENGINE
    # ==========================================

    def backtest_models(self, closes: List[float], volumes: List[float],
                        dates: List[str], analyst_upside: float = 0.10,
                        vix_history: List[float] = None) -> Tuple[ModelPerformance, ModelPerformance]:
        """
        Backtest both models on historical data

        Args:
            closes: List of closing prices (oldest first)
            volumes: List of volumes
            dates: List of date strings
            analyst_upside: Assumed analyst upside (constant for simplicity)
            vix_history: Optional VIX history (if None, assume 18)

        Returns:
            (V1.0 Performance, V5.0 Performance)
        """
        self.results_v1 = []
        self.results_v5 = []

        min_lookback = 90  # Need 90 days for proper Z-scores

        # Walk through data, leaving room for forward returns
        for i in range(min_lookback, len(closes) - 30):
            # Historical data up to this point
            hist_closes = closes[:i+1]
            hist_volumes = volumes[:i+1] if volumes else []
            current_date = dates[i]
            entry_price = closes[i]

            # Forward prices
            exit_7d = closes[min(i + 7, len(closes) - 1)]
            exit_14d = closes[min(i + 14, len(closes) - 1)]
            exit_30d = closes[min(i + 30, len(closes) - 1)]

            # Forward returns
            return_7d = ((exit_7d - entry_price) / entry_price) * 100
            return_14d = ((exit_14d - entry_price) / entry_price) * 100
            return_30d = ((exit_30d - entry_price) / entry_price) * 100

            # VIX at this point
            vix = vix_history[i] if vix_history and i < len(vix_history) else 18.0

            # V1.0 Signal
            v1_signal, v1_strength = self.v1_signal(hist_closes)

            # V5.0 Signal
            v5_signal, v5_confidence = self.v5_signal(hist_closes, hist_volumes, analyst_upside, vix)

            # Determine correctness
            # BUY is correct if price went up, SELL is correct if price went down
            def is_correct(signal: str, ret: float) -> bool:
                if signal == "BUY":
                    return ret > 0
                elif signal == "SELL":
                    return ret < 0
                else:  # HOLD
                    return abs(ret) < 5  # Within 5% is "correct" for hold

            # Store V1.0 result
            self.results_v1.append(BacktestResult(
                date=current_date,
                signal=v1_signal,
                entry_price=entry_price,
                exit_price_7d=exit_7d,
                exit_price_14d=exit_14d,
                exit_price_30d=exit_30d,
                return_7d=return_7d,
                return_14d=return_14d,
                return_30d=return_30d,
                correct_7d=is_correct(v1_signal, return_7d),
                correct_14d=is_correct(v1_signal, return_14d),
                correct_30d=is_correct(v1_signal, return_30d)
            ))

            # Store V5.0 result
            self.results_v5.append(BacktestResult(
                date=current_date,
                signal=v5_signal,
                entry_price=entry_price,
                exit_price_7d=exit_7d,
                exit_price_14d=exit_14d,
                exit_price_30d=exit_30d,
                return_7d=return_7d,
                return_14d=return_14d,
                return_30d=return_30d,
                correct_7d=is_correct(v5_signal, return_7d),
                correct_14d=is_correct(v5_signal, return_14d),
                correct_30d=is_correct(v5_signal, return_30d)
            ))

        # Calculate performance metrics
        v1_perf = self._calculate_performance("V1.0 (RSI/EMA)", self.results_v1)
        v5_perf = self._calculate_performance("V5.0 (Quant Alpha)", self.results_v5)

        return v1_perf, v5_perf

    def _calculate_performance(self, model_name: str, results: List[BacktestResult]) -> ModelPerformance:
        """Calculate aggregate performance metrics"""
        if not results:
            return ModelPerformance(
                model_name=model_name,
                total_signals=0, buy_signals=0, sell_signals=0, hold_signals=0,
                win_rate_7d=0, win_rate_14d=0, win_rate_30d=0,
                avg_return_7d=0, avg_return_14d=0, avg_return_30d=0,
                profit_factor=0, sharpe_ratio=0, max_drawdown=0
            )

        total = len(results)
        buys = [r for r in results if r.signal == "BUY"]
        sells = [r for r in results if r.signal == "SELL"]
        holds = [r for r in results if r.signal == "HOLD"]

        # Win rates (excluding HOLD for directional accuracy)
        directional = [r for r in results if r.signal in ["BUY", "SELL"]]

        if directional:
            win_rate_7d = sum(1 for r in directional if r.correct_7d) / len(directional)
            win_rate_14d = sum(1 for r in directional if r.correct_14d) / len(directional)
            win_rate_30d = sum(1 for r in directional if r.correct_30d) / len(directional)
        else:
            win_rate_7d = win_rate_14d = win_rate_30d = 0.5

        # Average returns (for BUY signals only, as that's our primary use case)
        if buys:
            avg_return_7d = sum(r.return_7d for r in buys) / len(buys)
            avg_return_14d = sum(r.return_14d for r in buys) / len(buys)
            avg_return_30d = sum(r.return_30d for r in buys) / len(buys)
        else:
            avg_return_7d = avg_return_14d = avg_return_30d = 0

        # Profit factor (gross profits / gross losses)
        profits = sum(r.return_7d for r in directional if r.return_7d > 0)
        losses = abs(sum(r.return_7d for r in directional if r.return_7d < 0))
        profit_factor = profits / losses if losses > 0 else profits

        # Sharpe ratio (simplified: avg return / std dev of returns)
        if directional:
            returns = [r.return_7d for r in directional]
            avg_ret = sum(returns) / len(returns)
            variance = sum((r - avg_ret) ** 2 for r in returns) / len(returns)
            std_dev = math.sqrt(variance) if variance > 0 else 1
            sharpe_ratio = avg_ret / std_dev
        else:
            sharpe_ratio = 0

        # Max drawdown (simplified)
        cumulative = 0
        peak = 0
        max_dd = 0
        for r in directional:
            if r.signal == "BUY":
                cumulative += r.return_7d
            else:
                cumulative -= r.return_7d  # Inverse for sells

            if cumulative > peak:
                peak = cumulative

            drawdown = peak - cumulative
            if drawdown > max_dd:
                max_dd = drawdown

        return ModelPerformance(
            model_name=model_name,
            total_signals=total,
            buy_signals=len(buys),
            sell_signals=len(sells),
            hold_signals=len(holds),
            win_rate_7d=round(win_rate_7d * 100, 2),
            win_rate_14d=round(win_rate_14d * 100, 2),
            win_rate_30d=round(win_rate_30d * 100, 2),
            avg_return_7d=round(avg_return_7d, 2),
            avg_return_14d=round(avg_return_14d, 2),
            avg_return_30d=round(avg_return_30d, 2),
            profit_factor=round(profit_factor, 2),
            sharpe_ratio=round(sharpe_ratio, 3),
            max_drawdown=round(max_dd, 2)
        )

    def get_weighted_recommendation(self, v1_signal: str, v1_strength: float,
                                     v5_signal: str, v5_confidence: float,
                                     v1_perf: ModelPerformance,
                                     v5_perf: ModelPerformance) -> Dict:
        """
        Get weighted recommendation based on historical performance

        Uses: signal × strength × historical_win_rate
        """
        # Use 7-day win rate as primary metric
        v1_win_rate = v1_perf.win_rate_7d / 100
        v5_win_rate = v5_perf.win_rate_7d / 100

        # Weighted scores
        v1_weighted = (v1_strength / 100) * v1_win_rate
        v5_weighted = (v5_confidence / 100) * v5_win_rate

        # Normalize to 100
        total = v1_weighted + v5_weighted
        if total > 0:
            v1_pct = (v1_weighted / total) * 100
            v5_pct = (v5_weighted / total) * 100
        else:
            v1_pct = v5_pct = 50

        # Winner
        if v5_weighted > v1_weighted:
            winner = "V5.0"
            winner_signal = v5_signal
            winner_confidence = v5_pct
        else:
            winner = "V1.0"
            winner_signal = v1_signal
            winner_confidence = v1_pct

        return {
            "v1_signal": v1_signal,
            "v1_strength": v1_strength,
            "v1_win_rate": v1_perf.win_rate_7d,
            "v1_weighted_score": round(v1_weighted * 100, 2),
            "v1_contribution": round(v1_pct, 1),

            "v5_signal": v5_signal,
            "v5_confidence": v5_confidence,
            "v5_win_rate": v5_perf.win_rate_7d,
            "v5_weighted_score": round(v5_weighted * 100, 2),
            "v5_contribution": round(v5_pct, 1),

            "winner": winner,
            "winner_signal": winner_signal,
            "winner_confidence": round(winner_confidence, 1),

            "recommendation": winner_signal,
            "combined_confidence": round(max(v1_pct, v5_pct), 1)
        }
