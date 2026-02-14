"""
ATLAS Position Sizing Module
==============================

Kelly Criterion position sizing with transaction cost awareness.
Ported from alpha_engine_v5.py:134-193 with enhancements.

Kelly Formula:
    f* = (p × b - q) / b

Where:
    p = probability of win
    q = probability of loss (1 - p)
    b = reward/risk ratio

We use Half-Kelly for safety (f* × 0.5)
Max position: 25% of account
"""

from dataclasses import dataclass
from typing import Dict, Optional

from .regime import MarketRegime


@dataclass
class PositionSize:
    """Position sizing output"""
    size_dollars: float
    size_pct: float
    kelly_fraction: float
    shares: int
    min_move_for_profit: float
    transaction_cost: float
    fee_feasible: bool
    regime_adjusted: bool
    notes: str


class PositionSizer:
    """
    Kelly Criterion position sizing with safety caps.

    Features:
    - Half-Kelly for conservative sizing
    - Volatility-based cap
    - Transaction cost filter
    - Regime-adjusted sizing
    """

    # Transaction costs
    TRANSACTION_COST_PER_TRADE = 1.50  # Per trade
    ROUND_TRIP_COST = 3.00  # Buy + Sell
    MIN_PROFIT_THRESHOLD = 6.00  # 2x round-trip cost

    # Position limits
    MAX_POSITION_PCT = 0.25  # Max 25% per position
    MIN_POSITION_DOLLARS = 100  # Don't bother with tiny positions

    # Volatility targeting
    TARGET_DAILY_VOL = 0.0005  # 0.05% daily portfolio volatility

    # Regime adjustments
    REGIME_SIZE_MULT = {
        MarketRegime.BULL: 1.0,       # Full size in bull
        MarketRegime.SIDEWAYS: 0.75,  # Reduced in sideways
        MarketRegime.BEAR: 0.50,      # Half size in bear
        MarketRegime.HIGH_VOL: 0.50,  # Half size in high vol
    }

    def __init__(self, account_value: float = 3700):
        """
        Initialize position sizer.

        Args:
            account_value: Total account value in dollars
        """
        self.account_value = account_value

    def update_account_value(self, value: float):
        """Update account value"""
        self.account_value = value

    def calculate_kelly_fraction(
        self,
        win_prob: float,
        reward_risk_ratio: float = 2.0
    ) -> float:
        """
        Calculate Kelly fraction.

        f* = p - (q / b)

        We use Half-Kelly for safety.

        Args:
            win_prob: Probability of winning (0-1)
            reward_risk_ratio: Expected reward / risk

        Returns:
            Kelly fraction (0 to MAX_POSITION_PCT)
        """
        if reward_risk_ratio <= 0 or win_prob <= 0:
            return 0.0

        q = 1 - win_prob
        kelly = win_prob - (q / reward_risk_ratio)

        # Half-Kelly for safety
        half_kelly = max(0, kelly * 0.5)

        # Cap at max position
        return min(half_kelly, self.MAX_POSITION_PCT)

    def calculate_position_size(
        self,
        win_prob: float,
        reward_risk_ratio: float = 2.0,
        current_price: float = None,
        atr_pct: float = 0.02,
        regime: MarketRegime = MarketRegime.SIDEWAYS
    ) -> PositionSize:
        """
        Calculate optimal position size.

        Args:
            win_prob: Probability of winning (0-1, e.g., 0.65)
            reward_risk_ratio: Expected reward / risk
            current_price: Current stock price (for share calculation)
            atr_pct: ATR as percentage of price (for volatility cap)
            regime: Current market regime

        Returns:
            PositionSize with all details
        """
        # 1. Kelly-based size
        kelly_fraction = self.calculate_kelly_fraction(win_prob, reward_risk_ratio)
        kelly_size = self.account_value * kelly_fraction

        # 2. Volatility-targeted size
        if atr_pct > 0:
            vol_cap = (self.account_value * self.TARGET_DAILY_VOL) / atr_pct
        else:
            vol_cap = kelly_size

        # 3. Use more conservative of Kelly vs Vol
        base_size = min(kelly_size, vol_cap)

        # 4. Apply regime adjustment
        regime_mult = self.REGIME_SIZE_MULT.get(regime, 1.0)
        adjusted_size = base_size * regime_mult
        regime_adjusted = regime_mult != 1.0

        # 5. Calculate final position size
        position_dollars = max(0, adjusted_size)
        position_pct = (position_dollars / self.account_value) * 100 if self.account_value > 0 else 0

        # 6. Calculate shares
        shares = int(position_dollars / current_price) if current_price and current_price > 0 else 0

        # 7. Transaction cost filter
        if position_dollars > 0:
            min_move_pct = (self.MIN_PROFIT_THRESHOLD / position_dollars) * 100
        else:
            min_move_pct = float('inf')

        fee_feasible = min_move_pct < 1.0  # Must not need >1% just for fees

        # 8. Build notes
        notes = []
        if not fee_feasible:
            notes.append(f"Position too small: need {min_move_pct:.1f}% move for profit")
        if position_dollars < self.MIN_POSITION_DOLLARS:
            notes.append(f"Below minimum position size (${self.MIN_POSITION_DOLLARS})")
        if regime_adjusted:
            notes.append(f"Size reduced {(1-regime_mult)*100:.0f}% for {regime.value}")

        return PositionSize(
            size_dollars=round(position_dollars, 2),
            size_pct=round(position_pct, 2),
            kelly_fraction=round(kelly_fraction, 4),
            shares=shares,
            min_move_for_profit=round(min_move_pct, 3),
            transaction_cost=self.ROUND_TRIP_COST,
            fee_feasible=fee_feasible,
            regime_adjusted=regime_adjusted,
            notes="; ".join(notes) if notes else "OK",
        )

    def should_trade(
        self,
        expected_profit_pct: float,
        position_size: float
    ) -> tuple:
        """
        Determine if a trade is worth making after costs.

        Args:
            expected_profit_pct: Expected profit percentage
            position_size: Position size in dollars

        Returns:
            Tuple of (should_trade, net_profit, reason)
        """
        gross_profit = position_size * (expected_profit_pct / 100)
        net_profit = gross_profit - self.ROUND_TRIP_COST

        if net_profit < self.MIN_PROFIT_THRESHOLD:
            return False, net_profit, f"Net profit ${net_profit:.2f} < ${self.MIN_PROFIT_THRESHOLD} threshold"

        return True, net_profit, f"Net profit ${net_profit:.2f} (after ${self.ROUND_TRIP_COST} fees)"

    def get_max_shares(self, price: float, regime: MarketRegime = None) -> int:
        """
        Get maximum shares to buy.

        Args:
            price: Current stock price
            regime: Optional regime for adjustment

        Returns:
            Maximum number of shares
        """
        if price <= 0:
            return 0

        max_dollars = self.account_value * self.MAX_POSITION_PCT

        if regime:
            mult = self.REGIME_SIZE_MULT.get(regime, 1.0)
            max_dollars *= mult

        return int(max_dollars / price)

    def calculate_risk_reward(
        self,
        entry_price: float,
        stop_loss_price: float,
        target_price: float
    ) -> Dict:
        """
        Calculate risk/reward metrics for a trade.

        Args:
            entry_price: Planned entry price
            stop_loss_price: Stop loss price
            target_price: Target exit price

        Returns:
            Dict with risk, reward, ratio
        """
        risk_pct = abs((stop_loss_price - entry_price) / entry_price) * 100
        reward_pct = ((target_price - entry_price) / entry_price) * 100
        ratio = reward_pct / risk_pct if risk_pct > 0 else 0

        return {
            "entry_price": entry_price,
            "stop_loss_price": stop_loss_price,
            "target_price": target_price,
            "risk_pct": round(risk_pct, 2),
            "reward_pct": round(reward_pct, 2),
            "reward_risk_ratio": round(ratio, 2),
            "favorable": ratio >= 2.0,
        }

    @staticmethod
    def kelly_win_rate_needed(reward_risk_ratio: float) -> float:
        """
        Calculate minimum win rate needed for positive Kelly.

        f* = p - q/b = 0  →  p = q/b = (1-p)/b
        p × b = 1 - p  →  p × (1+b) = 1  →  p = 1/(1+b)

        Args:
            reward_risk_ratio: Reward/risk ratio

        Returns:
            Minimum win rate (as decimal)
        """
        if reward_risk_ratio <= 0:
            return 1.0
        return 1 / (1 + reward_risk_ratio)
