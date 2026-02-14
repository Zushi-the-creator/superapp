"""
V5.0 Quantitative Alpha Engine
Statistical approach using Z-Scores, Bayesian filtering, and Kelly Criterion
Target: 1% monthly profit with controlled risk
"""

import math
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class AlphaSignal:
    """Output from V5.0 Alpha Engine"""
    ticker: str
    composite_alpha: float  # -100 to +100 scale
    z_price: float          # Price momentum Z-score
    z_analyst: float        # Analyst velocity Z-score
    z_volume: float         # Volume surge Z-score
    regime: str             # BULL, NEUTRAL, BEAR, PANIC
    bayesian_win_prob: float
    kelly_fraction: float
    position_size_dollars: float
    signal: str             # STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL
    confidence: float       # 0-100%


class ZScoreEngine:
    """
    Phase I: Statistical Normalization
    Converts raw values to Z-scores (standard deviations from mean)
    """

    @staticmethod
    def calculate_z_score(current: float, mean: float, std: float) -> float:
        """
        Z = (X - μ) / σ

        Returns how many standard deviations current is from mean
        """
        if std == 0 or std is None:
            return 0.0
        return (current - mean) / std

    @staticmethod
    def calculate_rolling_stats(prices: List[float], window: int = 90) -> tuple:
        """Calculate rolling mean and std for Z-score"""
        if len(prices) < window:
            window = len(prices)

        if window < 2:
            return prices[-1] if prices else 0, 1

        recent = prices[-window:]
        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / len(recent)
        std = math.sqrt(variance) if variance > 0 else 1

        return mean, std

    @staticmethod
    def calculate_composite_alpha(z_price: float, z_analyst: float, z_volume: float) -> float:
        """
        Composite Alpha Score (Sα)

        Sα = 25 × [(0.5 × Zp) + (0.3 × Za) + (0.2 × Zv)] + 50

        Weights:
        - Price Momentum: 50%
        - Analyst Velocity: 30%
        - Volume Surge: 20%

        Returns: 0-100 scale (50 = neutral)
        """
        raw_score = (0.5 * z_price) + (0.3 * z_analyst) + (0.2 * z_volume)
        # Scale to 0-100 where 50 is neutral
        # Assuming typical Z-scores range from -3 to +3
        scaled = 25 * raw_score + 50
        return max(0, min(100, scaled))


class BayesianRegimeFilter:
    """
    Phase II: Bayesian Regime Filtering
    Adjusts win probability based on market volatility (VIX)
    """

    # VIX regime thresholds
    REGIMES = {
        'BULL': (0, 15),      # Low fear
        'NEUTRAL': (15, 20),  # Normal
        'BEAR': (20, 30),     # Elevated fear
        'PANIC': (30, 100)    # Extreme fear
    }

    # Win rate adjustments by regime
    WIN_RATE_MULTIPLIERS = {
        'BULL': 1.15,      # Boost in low vol
        'NEUTRAL': 1.0,    # No adjustment
        'BEAR': 0.85,      # Reduce in high vol
        'PANIC': 0.70      # Significant reduction
    }

    @classmethod
    def get_regime(cls, vix: float) -> str:
        """Determine market regime from VIX level"""
        for regime, (low, high) in cls.REGIMES.items():
            if low <= vix < high:
                return regime
        return 'PANIC'

    @classmethod
    def bayesian_update(cls, prior_win_rate: float, vix: float) -> float:
        """
        Bayesian update of win probability based on VIX

        P(Win|VIX) = Prior × Regime_Multiplier

        Args:
            prior_win_rate: Base historical win rate (e.g., 0.55)
            vix: Current VIX level

        Returns:
            Adjusted win probability
        """
        regime = cls.get_regime(vix)
        multiplier = cls.WIN_RATE_MULTIPLIERS[regime]

        posterior = prior_win_rate * multiplier
        # Cap between 0.30 and 0.80
        return max(0.30, min(0.80, posterior))


class KellyRiskEngine:
    """
    Phase III: Kelly Criterion Position Sizing
    Calculates optimal position size for 1% monthly target
    """

    TARGET_DAILY_VOL = 0.0005  # 0.05% daily volatility target
    TARGET_MONTHLY_RETURN = 0.01  # 1% monthly

    @classmethod
    def calculate_kelly_fraction(cls, win_prob: float, reward_risk_ratio: float = 2.0) -> float:
        """
        Kelly Criterion: f* = p - (q / b)

        Where:
        - p = probability of win
        - q = probability of loss (1 - p)
        - b = reward-to-risk ratio

        We use Half-Kelly for safety
        """
        q = 1 - win_prob
        if reward_risk_ratio <= 0:
            return 0

        kelly = win_prob - (q / reward_risk_ratio)

        # Half-Kelly for safety
        safe_kelly = max(0, kelly * 0.5)

        # Cap at 25% of account per position
        return min(safe_kelly, 0.25)

    @classmethod
    def calculate_position_size(cls, account_value: float, win_prob: float,
                                 reward_risk_ratio: float, atr_pct: float) -> float:
        """
        Calculate position size using Kelly + Volatility targeting

        Args:
            account_value: Total account value
            win_prob: Bayesian-adjusted win probability
            reward_risk_ratio: Expected reward / risk
            atr_pct: Average True Range as percentage of price

        Returns:
            Maximum position size in dollars
        """
        # 1. Kelly-based size
        kelly_fraction = cls.calculate_kelly_fraction(win_prob, reward_risk_ratio)
        kelly_size = account_value * kelly_fraction

        # 2. Volatility-targeted size (0.05% daily vol target)
        if atr_pct > 0:
            vol_cap = (account_value * cls.TARGET_DAILY_VOL) / atr_pct
        else:
            vol_cap = kelly_size

        # 3. Return the more conservative of the two
        return min(kelly_size, vol_cap)


class AlphaEngineV5:
    """
    Main V5.0 Quantitative Alpha Engine
    Combines all components for signal generation
    """

    # Base win rate from historical backtesting
    BASE_WIN_RATE = 0.55

    # Entry threshold: Only trade when Alpha > 62.5 (top 2.5% statistical event)
    # This corresponds to Z > 0.5 composite
    ALPHA_ENTRY_THRESHOLD = 62.5

    # Exit threshold: Hard stop at Alpha < 25 (Z < -1)
    ALPHA_EXIT_THRESHOLD = 25

    def __init__(self, account_value: float = 3200):
        self.account_value = account_value
        self.z_engine = ZScoreEngine()
        self.regime_filter = BayesianRegimeFilter()
        self.risk_engine = KellyRiskEngine()

    def analyze(self, ticker: str, price_history: List[float],
                volume_history: List[float], current_price: float,
                current_volume: float, analyst_target: float,
                analyst_target_history: List[float], vix: float,
                atr_pct: float = 0.02) -> AlphaSignal:
        """
        Full V5.0 analysis pipeline

        Args:
            ticker: Stock symbol
            price_history: List of historical closing prices (90+ days ideal)
            volume_history: List of historical volumes
            current_price: Today's price
            current_volume: Today's volume
            analyst_target: Current analyst consensus target
            analyst_target_history: Historical analyst targets
            vix: Current VIX level
            atr_pct: ATR as percentage of price

        Returns:
            AlphaSignal with full analysis
        """

        # Phase I: Z-Score Calculations
        # Price momentum (20-day price vs 90-day mean)
        price_mean, price_std = self.z_engine.calculate_rolling_stats(price_history, 90)
        z_price = self.z_engine.calculate_z_score(current_price, price_mean, price_std)

        # Analyst velocity (current target vs 30-day mean of targets)
        if analyst_target_history and len(analyst_target_history) >= 5:
            analyst_mean, analyst_std = self.z_engine.calculate_rolling_stats(analyst_target_history, 30)
            z_analyst = self.z_engine.calculate_z_score(analyst_target, analyst_mean, analyst_std)
        else:
            # If no history, check upside potential
            upside = (analyst_target - current_price) / current_price if current_price > 0 else 0
            z_analyst = upside * 3  # Scale upside to Z-score equivalent

        # Volume surge (today vs 60-day average)
        vol_mean, vol_std = self.z_engine.calculate_rolling_stats(volume_history, 60)
        z_volume = self.z_engine.calculate_z_score(current_volume, vol_mean, vol_std)

        # Composite Alpha Score
        composite_alpha = self.z_engine.calculate_composite_alpha(z_price, z_analyst, z_volume)

        # Phase II: Bayesian Regime Filter
        regime = self.regime_filter.get_regime(vix)
        bayesian_win_prob = self.regime_filter.bayesian_update(self.BASE_WIN_RATE, vix)

        # Adjust win prob based on alpha strength
        if composite_alpha > 70:
            bayesian_win_prob = min(0.80, bayesian_win_prob * 1.1)
        elif composite_alpha < 40:
            bayesian_win_prob = max(0.30, bayesian_win_prob * 0.9)

        # Phase III: Risk Engine
        # Calculate reward/risk ratio based on analyst target
        if current_price > 0 and analyst_target > current_price:
            upside_pct = (analyst_target - current_price) / current_price
            # Assume stop loss at -5%, so reward/risk = upside / 0.05
            reward_risk = min(upside_pct / 0.05, 5.0)  # Cap at 5:1
        else:
            reward_risk = 1.5  # Default

        kelly_fraction = self.risk_engine.calculate_kelly_fraction(bayesian_win_prob, reward_risk)
        position_size = self.risk_engine.calculate_position_size(
            self.account_value, bayesian_win_prob, reward_risk, atr_pct
        )

        # Generate Signal
        if composite_alpha >= 75:
            signal = "STRONG_BUY"
        elif composite_alpha >= self.ALPHA_ENTRY_THRESHOLD:
            signal = "BUY"
        elif composite_alpha <= self.ALPHA_EXIT_THRESHOLD:
            signal = "STRONG_SELL"
        elif composite_alpha <= 40:
            signal = "SELL"
        else:
            signal = "HOLD"

        # Confidence based on regime and alpha
        confidence = min(100, composite_alpha * (bayesian_win_prob / 0.55))

        return AlphaSignal(
            ticker=ticker,
            composite_alpha=round(composite_alpha, 2),
            z_price=round(z_price, 3),
            z_analyst=round(z_analyst, 3),
            z_volume=round(z_volume, 3),
            regime=regime,
            bayesian_win_prob=round(bayesian_win_prob, 3),
            kelly_fraction=round(kelly_fraction, 4),
            position_size_dollars=round(position_size, 2),
            signal=signal,
            confidence=round(confidence, 1)
        )


def compare_with_v1(v1_signal: str, v1_strength: float, v5_signal: AlphaSignal) -> Dict:
    """
    Compare V1.0 (RSI/EMA) signal with V5.0 (Quantitative) signal

    Returns recommendation and reasoning
    """
    # Map V1 signals to numeric
    v1_map = {'BUY': 2, 'HOLD': 0, 'SELL': -2}
    v5_map = {'STRONG_BUY': 3, 'BUY': 2, 'HOLD': 0, 'SELL': -2, 'STRONG_SELL': -3}

    v1_score = v1_map.get(v1_signal, 0)
    v5_score = v5_map.get(v5_signal.signal, 0)

    # Agreement check
    if (v1_score > 0 and v5_score > 0) or (v1_score < 0 and v5_score < 0):
        agreement = "ALIGNED"
        combined_action = v5_signal.signal  # Use V5's more nuanced signal
    elif v1_score == 0 and v5_score == 0:
        agreement = "BOTH_HOLD"
        combined_action = "HOLD"
    else:
        agreement = "CONFLICT"
        # In conflict, weight by confidence
        if v5_signal.confidence > v1_strength:
            combined_action = v5_signal.signal
        else:
            combined_action = v1_signal

    return {
        'v1_signal': v1_signal,
        'v1_strength': v1_strength,
        'v5_signal': v5_signal.signal,
        'v5_alpha': v5_signal.composite_alpha,
        'v5_confidence': v5_signal.confidence,
        'agreement': agreement,
        'combined_action': combined_action,
        'recommended_size': v5_signal.position_size_dollars
    }
