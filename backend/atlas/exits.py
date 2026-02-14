"""
ATLAS Exit System Module
=========================

Adaptive exit strategies based on market regime.
Ported from adaptive_exits_v26.py with enhancements.

Exit Strategies by Regime:

TRENDING (BULL):
    - Stop: -8% from entry
    - Trailing: -10% from peak (after +5%)
    - Target 1: +10% (partial exit)
    - Target 2: +20% (full exit)
    - Let winners run

CHOPPY (SIDEWAYS):
    - Stop: -5% from entry
    - RSI(14) > 70 → EXIT
    - RSI(2) > 85 → EXIT
    - Target: +5%
    - Capture small gains quickly

BEAR:
    - Stop: -4% (very tight)
    - Any profit > 3% → EXIT
    - Quick exits

HIGH_VOL:
    - Stop: -4%
    - Target: +4%
    - Quick in and out

Validated Finding: RSI(2)>80 exit only 34% accurate.
Use mechanical exits (profit targets) instead.
"""

from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from enum import Enum

from .indicators import Indicators
from .regime import RegimeDetector, MarketRegime


class ExitAction(Enum):
    """Exit action types"""
    HOLD = "HOLD"
    EXIT_FULL = "EXIT_FULL"
    EXIT_PARTIAL = "EXIT_PARTIAL"  # Sell 50%
    TIGHTEN_STOP = "TIGHTEN_STOP"


class ExitStrategy(Enum):
    """Exit strategy types"""
    MECHANICAL = "MECHANICAL"  # Stop + trailing + targets
    QUICK_SELL = "QUICK_SELL"  # RSI-based quick exits


@dataclass
class ExitSignal:
    """Exit signal output"""
    action: ExitAction
    reason: str
    regime: MarketRegime
    strategy: ExitStrategy
    stop_loss: float
    profit_target: float
    confidence: float
    pnl_pct: float
    days_held: int


class ExitSystem:
    """
    Adaptive exit system - strategy varies by regime.

    Key insight from backtesting:
    - TRENDING markets: Mechanical exits beat RSI sells by 61-116%
    - CHOPPY markets: RSI sells beat mechanical (capture small gains)
    """

    # Mechanical exit parameters (TRENDING)
    MECH_STOP_LOSS_PCT = 8.0
    MECH_TRAILING_ACTIVATION = 5.0  # Activate after +5%
    MECH_TRAILING_PCT = 10.0        # 10% from peak
    MECH_TARGET_1_PCT = 10.0        # First target
    MECH_TARGET_2_PCT = 20.0        # Full exit

    # Quick sell parameters (CHOPPY)
    QUICK_STOP_LOSS_PCT = 5.0
    QUICK_RSI14_SELL = 70
    QUICK_RSI2_SELL = 85
    QUICK_TARGET_PCT = 5.0

    # Bear market parameters
    BEAR_STOP_LOSS_PCT = 4.0
    BEAR_TARGET_PCT = 3.0

    # High volatility parameters
    HIGHVOL_STOP_LOSS_PCT = 4.0
    HIGHVOL_TARGET_PCT = 4.0

    # Time-based exit
    MAX_HOLD_DAYS = 14

    def __init__(self, db=None):
        """
        Initialize exit system.

        Args:
            db: Optional ATLASDatabase for learned parameters
        """
        self.db = db

    def get_exit_signal(
        self,
        entry_price: float,
        current_price: float,
        highest_price: float,
        closes: List[float],
        days_held: int = 0,
        ticker: str = None
    ) -> ExitSignal:
        """
        Get exit signal based on current position state.

        Args:
            entry_price: Original entry price
            current_price: Current market price
            highest_price: Highest price since entry
            closes: Recent closing prices for regime detection
            days_held: Days position has been held
            ticker: Optional ticker for context

        Returns:
            ExitSignal with recommendation
        """
        # Detect regime
        regime = RegimeDetector.detect(closes)

        # Calculate P&L
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        drawdown_pct = ((highest_price - current_price) / highest_price) * 100 if highest_price > 0 else 0

        # Calculate RSI
        rsi14 = Indicators.calc_rsi(closes, 14)
        rsi2 = Indicators.calc_rsi(closes, 2)

        # Time-based exit
        if days_held >= self.MAX_HOLD_DAYS:
            return ExitSignal(
                action=ExitAction.EXIT_FULL,
                reason=f"Max hold time ({self.MAX_HOLD_DAYS} days) reached",
                regime=regime,
                strategy=ExitStrategy.MECHANICAL,
                stop_loss=entry_price * 0.95,
                profit_target=current_price,
                confidence=85.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # Route to regime-specific exit
        if regime == MarketRegime.BULL:
            return self._mechanical_exit(
                entry_price, current_price, highest_price,
                pnl_pct, drawdown_pct, regime, days_held
            )
        elif regime == MarketRegime.BEAR:
            return self._bear_exit(
                entry_price, current_price, pnl_pct,
                rsi2, rsi14, regime, days_held
            )
        elif regime == MarketRegime.HIGH_VOL:
            return self._highvol_exit(
                entry_price, current_price, pnl_pct,
                rsi2, rsi14, regime, days_held
            )
        else:  # SIDEWAYS
            return self._quick_sell_exit(
                entry_price, current_price, pnl_pct,
                rsi2, rsi14, regime, days_held
            )

    def _mechanical_exit(
        self,
        entry_price: float,
        current_price: float,
        highest_price: float,
        pnl_pct: float,
        drawdown_pct: float,
        regime: MarketRegime,
        days_held: int
    ) -> ExitSignal:
        """
        Mechanical exit for BULL/TRENDING markets.
        Let winners run with trailing stops.
        """
        stop_loss = entry_price * (1 - self.MECH_STOP_LOSS_PCT / 100)
        target_1 = entry_price * (1 + self.MECH_TARGET_1_PCT / 100)
        target_2 = entry_price * (1 + self.MECH_TARGET_2_PCT / 100)

        # Stop-loss hit
        if pnl_pct <= -self.MECH_STOP_LOSS_PCT:
            return ExitSignal(
                action=ExitAction.EXIT_FULL,
                reason=f"STOP-LOSS: {pnl_pct:.1f}% (limit: -{self.MECH_STOP_LOSS_PCT}%)",
                regime=regime,
                strategy=ExitStrategy.MECHANICAL,
                stop_loss=stop_loss,
                profit_target=target_1,
                confidence=95.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # Trailing stop (after activation)
        if pnl_pct >= self.MECH_TRAILING_ACTIVATION and drawdown_pct >= self.MECH_TRAILING_PCT:
            trailing_stop = highest_price * (1 - self.MECH_TRAILING_PCT / 100)
            return ExitSignal(
                action=ExitAction.EXIT_FULL,
                reason=f"TRAILING STOP: {drawdown_pct:.1f}% from peak ${highest_price:.2f}",
                regime=regime,
                strategy=ExitStrategy.MECHANICAL,
                stop_loss=trailing_stop,
                profit_target=target_2,
                confidence=90.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # Profit target 2 (full exit)
        if pnl_pct >= self.MECH_TARGET_2_PCT:
            return ExitSignal(
                action=ExitAction.EXIT_FULL,
                reason=f"PROFIT TARGET 2: +{pnl_pct:.1f}% (full exit)",
                regime=regime,
                strategy=ExitStrategy.MECHANICAL,
                stop_loss=entry_price,
                profit_target=target_2,
                confidence=90.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # Profit target 1 (partial exit)
        if pnl_pct >= self.MECH_TARGET_1_PCT:
            return ExitSignal(
                action=ExitAction.EXIT_PARTIAL,
                reason=f"PROFIT TARGET 1: +{pnl_pct:.1f}% (sell 50%, trail rest)",
                regime=regime,
                strategy=ExitStrategy.MECHANICAL,
                stop_loss=entry_price,  # Move stop to breakeven
                profit_target=target_2,
                confidence=85.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # Hold - trending, let it run
        active_stop = stop_loss
        if pnl_pct >= self.MECH_TRAILING_ACTIVATION:
            active_stop = highest_price * (1 - self.MECH_TRAILING_PCT / 100)

        return ExitSignal(
            action=ExitAction.HOLD,
            reason=f"BULL regime: Hold with trailing. P&L: {pnl_pct:+.1f}%",
            regime=regime,
            strategy=ExitStrategy.MECHANICAL,
            stop_loss=active_stop,
            profit_target=target_1 if pnl_pct < self.MECH_TARGET_1_PCT else target_2,
            confidence=70.0,
            pnl_pct=pnl_pct,
            days_held=days_held,
        )

    def _quick_sell_exit(
        self,
        entry_price: float,
        current_price: float,
        pnl_pct: float,
        rsi2: float,
        rsi14: float,
        regime: MarketRegime,
        days_held: int
    ) -> ExitSignal:
        """
        Quick sell exit for SIDEWAYS/CHOPPY markets.
        Capture small gains, don't let them reverse.
        """
        stop_loss = entry_price * (1 - self.QUICK_STOP_LOSS_PCT / 100)
        target = entry_price * (1 + self.QUICK_TARGET_PCT / 100)

        # Tight stop-loss
        if pnl_pct <= -self.QUICK_STOP_LOSS_PCT:
            return ExitSignal(
                action=ExitAction.EXIT_FULL,
                reason=f"STOP-LOSS (CHOPPY): {pnl_pct:.1f}% (tight: -{self.QUICK_STOP_LOSS_PCT}%)",
                regime=regime,
                strategy=ExitStrategy.QUICK_SELL,
                stop_loss=stop_loss,
                profit_target=target,
                confidence=95.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # RSI(14) overbought - quick exit
        if rsi14 > self.QUICK_RSI14_SELL:
            return ExitSignal(
                action=ExitAction.EXIT_FULL,
                reason=f"RSI(14)={rsi14:.0f} > {self.QUICK_RSI14_SELL}: Take profit in choppy",
                regime=regime,
                strategy=ExitStrategy.QUICK_SELL,
                stop_loss=stop_loss,
                profit_target=current_price,
                confidence=85.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # RSI(2) extreme - quick exit
        if rsi2 > self.QUICK_RSI2_SELL:
            return ExitSignal(
                action=ExitAction.EXIT_FULL,
                reason=f"RSI(2)={rsi2:.0f} > {self.QUICK_RSI2_SELL}: Quick exit in choppy",
                regime=regime,
                strategy=ExitStrategy.QUICK_SELL,
                stop_loss=stop_loss,
                profit_target=current_price,
                confidence=80.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # Profit target
        if pnl_pct >= self.QUICK_TARGET_PCT:
            return ExitSignal(
                action=ExitAction.EXIT_PARTIAL,
                reason=f"CHOPPY PROFIT: +{pnl_pct:.1f}% (take some profit)",
                regime=regime,
                strategy=ExitStrategy.QUICK_SELL,
                stop_loss=entry_price,
                profit_target=target,
                confidence=75.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # Hold with tight stop
        return ExitSignal(
            action=ExitAction.HOLD,
            reason=f"SIDEWAYS: Hold with {self.QUICK_STOP_LOSS_PCT}% stop. RSI(14)={rsi14:.0f}",
            regime=regime,
            strategy=ExitStrategy.QUICK_SELL,
            stop_loss=stop_loss,
            profit_target=target,
            confidence=60.0,
            pnl_pct=pnl_pct,
            days_held=days_held,
        )

    def _bear_exit(
        self,
        entry_price: float,
        current_price: float,
        pnl_pct: float,
        rsi2: float,
        rsi14: float,
        regime: MarketRegime,
        days_held: int
    ) -> ExitSignal:
        """
        Bear market exit - very tight stops, take any profit.
        """
        stop_loss = entry_price * (1 - self.BEAR_STOP_LOSS_PCT / 100)
        target = entry_price * (1 + self.BEAR_TARGET_PCT / 100)

        # Very tight stop
        if pnl_pct <= -self.BEAR_STOP_LOSS_PCT:
            return ExitSignal(
                action=ExitAction.EXIT_FULL,
                reason=f"BEAR STOP: {pnl_pct:.1f}% (limit: -{self.BEAR_STOP_LOSS_PCT}%)",
                regime=regime,
                strategy=ExitStrategy.QUICK_SELL,
                stop_loss=stop_loss,
                profit_target=target,
                confidence=95.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # Take any profit
        if pnl_pct >= self.BEAR_TARGET_PCT:
            return ExitSignal(
                action=ExitAction.EXIT_FULL,
                reason=f"BEAR PROFIT: +{pnl_pct:.1f}% (exit quickly)",
                regime=regime,
                strategy=ExitStrategy.QUICK_SELL,
                stop_loss=stop_loss,
                profit_target=target,
                confidence=85.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # RSI mean reversion complete
        if rsi2 > 70:
            return ExitSignal(
                action=ExitAction.EXIT_FULL,
                reason=f"BEAR RSI: RSI(2)={rsi2:.0f} normalized - exit",
                regime=regime,
                strategy=ExitStrategy.QUICK_SELL,
                stop_loss=stop_loss,
                profit_target=current_price,
                confidence=80.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # Hold with very tight stop
        return ExitSignal(
            action=ExitAction.HOLD,
            reason=f"BEAR: Hold with {self.BEAR_STOP_LOSS_PCT}% stop. Watch closely.",
            regime=regime,
            strategy=ExitStrategy.QUICK_SELL,
            stop_loss=stop_loss,
            profit_target=target,
            confidence=50.0,
            pnl_pct=pnl_pct,
            days_held=days_held,
        )

    def _highvol_exit(
        self,
        entry_price: float,
        current_price: float,
        pnl_pct: float,
        rsi2: float,
        rsi14: float,
        regime: MarketRegime,
        days_held: int
    ) -> ExitSignal:
        """
        High volatility exit - tight stops, quick profits.
        """
        stop_loss = entry_price * (1 - self.HIGHVOL_STOP_LOSS_PCT / 100)
        target = entry_price * (1 + self.HIGHVOL_TARGET_PCT / 100)

        # Very tight stop
        if pnl_pct <= -self.HIGHVOL_STOP_LOSS_PCT:
            return ExitSignal(
                action=ExitAction.EXIT_FULL,
                reason=f"HIGH VOL STOP: {pnl_pct:.1f}% (limit: -{self.HIGHVOL_STOP_LOSS_PCT}%)",
                regime=regime,
                strategy=ExitStrategy.QUICK_SELL,
                stop_loss=stop_loss,
                profit_target=target,
                confidence=95.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # Quick profit
        if pnl_pct >= self.HIGHVOL_TARGET_PCT:
            return ExitSignal(
                action=ExitAction.EXIT_FULL,
                reason=f"HIGH VOL PROFIT: +{pnl_pct:.1f}% (exit quickly)",
                regime=regime,
                strategy=ExitStrategy.QUICK_SELL,
                stop_loss=stop_loss,
                profit_target=target,
                confidence=85.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # RSI extreme - exit immediately
        if rsi2 > 90 or rsi2 < 10:
            return ExitSignal(
                action=ExitAction.EXIT_FULL,
                reason=f"HIGH VOL RSI EXTREME: RSI(2)={rsi2:.0f} - exit volatile position",
                regime=regime,
                strategy=ExitStrategy.QUICK_SELL,
                stop_loss=stop_loss,
                profit_target=current_price,
                confidence=80.0,
                pnl_pct=pnl_pct,
                days_held=days_held,
            )

        # Hold with very tight stop
        return ExitSignal(
            action=ExitAction.HOLD,
            reason=f"HIGH VOL: Hold with {self.HIGHVOL_STOP_LOSS_PCT}% stop",
            regime=regime,
            strategy=ExitStrategy.QUICK_SELL,
            stop_loss=stop_loss,
            profit_target=target,
            confidence=50.0,
            pnl_pct=pnl_pct,
            days_held=days_held,
        )
