"""
ATLAS V2.0 Main Model
=====================

Unified trading model based on 2024-2025 academic research.

Key Components:
1. Regime Detection - Adapt to market conditions
2. Multi-Factor Entry - RSI(2) + Trend + Volume + RSI(14)
3. Research-Backed Exit - Time-based > Trailing stops
4. Thompson Sampling - Continuous parameter optimization
5. Walk-Forward Validation - Prevent overfitting

Usage:
    from atlas_v2 import ATLASV2Model

    model = ATLASV2Model()

    # Analyze a stock
    result = model.analyze("NVDA", closes, volumes)

    # Check exit for existing position
    exit_signal = model.check_exit(entry_price=180, current_price=190, days_held=3, closes=closes)

    # Record trade outcome for learning
    model.record_trade_outcome(...)

    # Get learned parameters
    params = model.get_learned_params("BULL")
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from .regime import RegimeDetector, MarketRegime, RegimeInfo
from .entry import EntryEngine, EntrySignal, SignalType
from .exit import ExitEngine, ExitSignal, ExitAction
from .learner import ThompsonSamplingLearner, TradeOutcome
from .validator import WalkForwardValidator, WalkForwardResult


@dataclass
class AnalysisResult:
    """Complete analysis output with warnings"""
    ticker: str
    timestamp: str
    regime: RegimeInfo
    entry_signal: EntrySignal
    exit_params: dict
    position_size_multiplier: float
    recommendation: str
    factors: List[str]

    # NEW: Validation fields
    backtest_win_rate: float = None  # Actual backtest WR
    backtest_trades: int = 0  # Number of trades in backtest
    is_valid_signal: bool = True  # False if backtest WR < 55%
    validation_notes: List[str] = None  # Validation warnings

    def has_warnings(self) -> bool:
        """Check if signal has any warnings"""
        return self.entry_signal.has_warnings()

    def has_critical_warnings(self) -> bool:
        """Check if signal has critical warnings"""
        return self.entry_signal.has_critical_warnings()

    def get_signal_quality(self) -> str:
        """Get overall signal quality assessment"""
        if self.has_critical_warnings():
            return "POOR - Critical issues detected"
        if not self.is_valid_signal:
            return "INVALID - Below minimum win rate"
        if self.entry_signal.signal_strength.value == "STRONG":
            return "EXCELLENT - High confidence signal"
        if self.entry_signal.signal_strength.value == "MODERATE":
            return "GOOD - Acceptable signal"
        return "WEAK - Proceed with caution"

    def get_summary(self) -> str:
        """Get human-readable summary"""
        lines = [
            f"=== {self.ticker} Analysis ===",
            f"Signal: {self.entry_signal.signal.value}",
            f"Strength: {self.entry_signal.signal_strength.value}",
            f"Quality: {self.get_signal_quality()}",
            f"RSI(2): {self.entry_signal.rsi2:.1f}",
            f"Regime: {self.regime.regime.value}",
            f"Expected Hold: {self.entry_signal.expected_hold_days} days",
            f"RSI Flip Risk: {self.entry_signal.rsi_flip_risk}",
        ]
        if self.backtest_win_rate:
            lines.append(f"Backtest WR: {self.backtest_win_rate:.1f}% ({self.backtest_trades} trades)")
        if self.entry_signal.warnings:
            lines.append("Warnings:")
            for w in self.entry_signal.warnings:
                lines.append(f"  - {w}")
        return "\n".join(lines)


class ATLASV2Model:
    """
    ATLAS V2.0: Adaptive Trading Learning and Signal System

    Research-backed unified model that:
    - Detects market regime (BULL/BEAR/SIDEWAYS/HIGH_VOL)
    - Uses multi-factor entry (RSI + Trend + Volume)
    - Applies time-based exits (outperform trailing stops)
    - Learns continuously via Thompson Sampling
    - Validates with walk-forward to prevent overfitting

    Academic References:
    - Jha et al. (2025): RL with triple-indicator, 85.4% accuracy
    - QuantifiedStrategies: RSI(2) mean reversion, 91% win rate
    - arXiv 2024: Thompson Sampling with ε-greedy
    - QuantInsti: Walk-forward validation (WFE > 50%)
    """

    def __init__(self, db_path: str = None):
        """
        Initialize ATLAS V2.0 model.

        Args:
            db_path: Path to learning database (default: atlas_v2_learning.db)
        """
        self.entry_engine = EntryEngine()
        self.exit_engine = ExitEngine()
        self.learner = ThompsonSamplingLearner(db_path)
        self.validator = WalkForwardValidator()

    def analyze(
        self,
        ticker: str,
        closes: List[float],
        volumes: List[float] = None,
        highs: List[float] = None,
        lows: List[float] = None,
        days_to_earnings: int = None,
        sentiment_score: float = 0
    ) -> AnalysisResult:
        """
        Complete analysis for a stock.

        Args:
            ticker: Stock symbol
            closes: List of closing prices (50+ recommended)
            volumes: Optional volume data
            highs: Optional high prices
            lows: Optional low prices
            days_to_earnings: Days until next earnings
            sentiment_score: -1 (negative) to +1 (positive)

        Returns:
            AnalysisResult with signal and sizing
        """
        # Detect regime
        regime_info = RegimeDetector.detect(closes, highs, lows, volumes)

        # Get learned parameters for this regime
        learned_params = self.learner.get_learned_params(regime_info.regime.value)

        # Generate entry signal
        entry_signal = self.entry_engine.generate_signal(
            closes=closes,
            volumes=volumes,
            highs=highs,
            lows=lows,
            days_to_earnings=days_to_earnings,
            sentiment_score=sentiment_score,
            learned_params=learned_params
        )

        # Get exit parameters
        regime_params = RegimeDetector.get_regime_params(regime_info.regime)
        exit_params = {
            'profit_target_pct': learned_params.get('profit_target_pct', regime_params['profit_target_pct']),
            'stop_loss_pct': learned_params.get('stop_loss_pct', regime_params['stop_loss_pct']),
            'max_days': int(learned_params.get('max_days', regime_params['exit_days'])),
        }

        # Calculate position size multiplier
        position_multiplier = regime_params['position_multiplier']
        if regime_info.volatility_ratio > 1.5:
            position_multiplier *= 0.7  # Reduce in high volatility

        # Build recommendation
        if entry_signal.signal == SignalType.BUY:
            recommendation = f"BUY with {position_multiplier*100:.0f}% position size"
        elif entry_signal.signal == SignalType.WAIT:
            recommendation = f"WAIT - good setup but vetoed: {entry_signal.veto_reason}"
        else:
            recommendation = f"HOLD - no entry signal"

        return AnalysisResult(
            ticker=ticker,
            timestamp=datetime.now().isoformat(),
            regime=regime_info,
            entry_signal=entry_signal,
            exit_params=exit_params,
            position_size_multiplier=position_multiplier,
            recommendation=recommendation,
            factors=entry_signal.factors,
            validation_notes=[]
        )

    def analyze_with_validation(
        self,
        ticker: str,
        closes: List[float],
        volumes: List[float] = None,
        highs: List[float] = None,
        lows: List[float] = None,
        days_to_earnings: int = None,
        sentiment_score: float = 0,
        min_win_rate: float = 60.0
    ) -> AnalysisResult:
        """
        Complete analysis WITH automatic backtest validation.

        This method:
        1. Runs backtest on historical data
        2. Validates signal against backtest win rate
        3. Flags weak signals (WR < 60%) and invalid signals (WR < 55%)
        4. Adds all warnings to the result

        Args:
            ticker: Stock symbol
            closes: List of closing prices (200+ recommended for backtest)
            volumes: Optional volume data
            highs: Optional high prices
            lows: Optional low prices
            days_to_earnings: Days until next earnings
            sentiment_score: -1 (negative) to +1 (positive)
            min_win_rate: Minimum required win rate (default 60%)

        Returns:
            AnalysisResult with validation data and warnings
        """
        validation_notes = []

        # First, run backtest to get actual win rate
        backtest_result = None
        backtest_wr = None
        backtest_trades = 0

        if len(closes) >= 60:
            # Build history for backtest
            history = []
            for i, close in enumerate(closes):
                history.append({
                    'date': f'day_{i}',
                    'close': close,
                    'open': close,
                    'high': highs[i] if highs and i < len(highs) else close,
                    'low': lows[i] if lows and i < len(lows) else close,
                    'volume': volumes[i] if volumes and i < len(volumes) else 0
                })

            backtest_result = self.backtest(history, ticker)
            backtest_wr = backtest_result.get('win_rate', 0)
            backtest_trades = backtest_result.get('trades', 0)

            if backtest_trades < 10:
                validation_notes.append(f"⚠️ Only {backtest_trades} backtest trades - insufficient sample")
            elif backtest_wr < 55:
                validation_notes.append(f"❌ CRITICAL: Backtest WR {backtest_wr:.1f}% < 55% - INVALID SIGNAL")
            elif backtest_wr < min_win_rate:
                validation_notes.append(f"⚠️ Backtest WR {backtest_wr:.1f}% < {min_win_rate:.0f}% target")
            else:
                validation_notes.append(f"✓ Backtest WR {backtest_wr:.1f}% meets threshold")
        else:
            validation_notes.append("⚠️ Insufficient data for backtest (need 60+ days)")

        # Detect regime
        regime_info = RegimeDetector.detect(closes, highs, lows, volumes)

        # Get learned parameters for this regime
        learned_params = self.learner.get_learned_params(regime_info.regime.value)

        # Generate entry signal WITH backtest validation
        entry_signal = self.entry_engine.generate_signal(
            closes=closes,
            volumes=volumes,
            highs=highs,
            lows=lows,
            days_to_earnings=days_to_earnings,
            sentiment_score=sentiment_score,
            learned_params=learned_params,
            backtest_win_rate=backtest_wr,
            min_required_win_rate=min_win_rate
        )

        # Get exit parameters
        regime_params = RegimeDetector.get_regime_params(regime_info.regime)
        exit_params = {
            'profit_target_pct': learned_params.get('profit_target_pct', regime_params['profit_target_pct']),
            'stop_loss_pct': learned_params.get('stop_loss_pct', regime_params['stop_loss_pct']),
            'max_days': int(learned_params.get('max_days', regime_params['exit_days'])),
        }

        # Calculate position size multiplier
        position_multiplier = regime_params['position_multiplier']
        if regime_info.volatility_ratio > 1.5:
            position_multiplier *= 0.7

        # Determine if signal is valid
        is_valid = True
        invalid_reason = ""
        if backtest_wr is not None and backtest_wr < 55:
            is_valid = False
            invalid_reason = f"backtest WR {backtest_wr:.1f}% < 55% minimum"
        if backtest_trades < 10:
            is_valid = False
            if not invalid_reason:
                invalid_reason = f"only {backtest_trades} trades (need 10+)"
            else:
                invalid_reason += f", only {backtest_trades} trades"

        # Build recommendation with validation context
        if not is_valid:
            recommendation = f"⛔ INVALID SIGNAL - {invalid_reason}"
        elif entry_signal.signal == SignalType.BUY:
            if entry_signal.signal_strength.value == "WEAK":
                recommendation = f"⚠️ WEAK BUY - proceed with caution ({position_multiplier*100:.0f}% size)"
            elif entry_signal.signal_strength.value == "MODERATE":
                recommendation = f"BUY with {position_multiplier*100:.0f}% position size"
            else:
                recommendation = f"✓ STRONG BUY with {position_multiplier*100:.0f}% position size"
        elif entry_signal.signal == SignalType.WAIT:
            recommendation = f"WAIT - good setup but vetoed: {entry_signal.veto_reason}"
        else:
            recommendation = f"HOLD - no entry signal"

        return AnalysisResult(
            ticker=ticker,
            timestamp=datetime.now().isoformat(),
            regime=regime_info,
            entry_signal=entry_signal,
            exit_params=exit_params,
            position_size_multiplier=position_multiplier,
            recommendation=recommendation,
            factors=entry_signal.factors,
            backtest_win_rate=backtest_wr,
            backtest_trades=backtest_trades,
            is_valid_signal=is_valid,
            validation_notes=validation_notes
        )

    def check_exit(
        self,
        entry_price: float,
        current_price: float,
        days_held: int,
        closes: List[float],
        highs: List[float] = None,
        lows: List[float] = None
    ) -> ExitSignal:
        """
        Check if position should be exited.

        Args:
            entry_price: Original entry price
            current_price: Current price
            days_held: Days since entry
            closes: Recent closes for regime detection
            highs: High prices
            lows: Low prices

        Returns:
            ExitSignal with action and reason
        """
        # Get current regime
        regime_info = RegimeDetector.detect(closes, highs, lows)

        # Get learned parameters
        learned_params = self.learner.get_learned_params(regime_info.regime.value)

        return self.exit_engine.get_exit_signal(
            entry_price=entry_price,
            current_price=current_price,
            days_held=days_held,
            closes=closes,
            highs=highs,
            lows=lows,
            learned_params=learned_params
        )

    def record_trade_outcome(
        self,
        ticker: str,
        regime: str,
        entry_date: str,
        entry_price: float,
        exit_date: str,
        exit_price: float,
        days_held: int,
        rsi2_at_entry: float,
        exit_reason: str
    ) -> int:
        """
        Record a completed trade for learning.

        This triggers Thompson Sampling parameter updates.

        Args:
            ticker: Stock symbol
            regime: Market regime at entry
            entry_date: Entry date (ISO format)
            entry_price: Entry price
            exit_date: Exit date (ISO format)
            exit_price: Exit price
            days_held: Days held
            rsi2_at_entry: RSI(2) at entry
            exit_reason: Reason for exit

        Returns:
            Trade ID
        """
        return_pct = ((exit_price - entry_price) / entry_price) * 100
        win = return_pct > 0

        outcome = TradeOutcome(
            ticker=ticker,
            regime=regime,
            entry_date=entry_date,
            entry_price=entry_price,
            exit_date=exit_date,
            exit_price=exit_price,
            return_pct=return_pct,
            win=win,
            days_held=days_held,
            rsi2_at_entry=rsi2_at_entry,
            exit_reason=exit_reason
        )

        return self.learner.record_trade(outcome)

    def validate_on_history(
        self,
        history: List[Dict],
        ticker: str = "UNKNOWN"
    ) -> WalkForwardResult:
        """
        Run walk-forward validation on historical data.

        Args:
            history: List of dicts with 'date', 'open', 'high', 'low', 'close', 'volume'
            ticker: Stock symbol

        Returns:
            WalkForwardResult with validation metrics
        """
        return self.validator.validate(history, ticker)

    def get_learned_params(self, regime: str) -> dict:
        """
        Get current learned parameters for a regime.

        Args:
            regime: Market regime (BULL, BEAR, SIDEWAYS, HIGH_VOL)

        Returns:
            dict of parameter name to value
        """
        return self.learner.get_learned_params(regime)

    def get_learning_summary(self) -> dict:
        """
        Get summary of learning state across all regimes.

        Returns:
            dict with stats per regime
        """
        return self.learner.get_learning_summary()

    def backtest(
        self,
        history: List[Dict],
        ticker: str = "UNKNOWN"
    ) -> Dict:
        """
        Run backtest on historical data.
        V2.6: RSI(2) < 10, next-day open entry, Fixed30d hold, 0.30% fee, non-overlapping.

        Args:
            history: List of dicts with 'date', 'open', 'high', 'low', 'close', 'volume'
            ticker: Stock symbol

        Returns:
            Backtest results
        """
        if len(history) < 60:
            return {
                'ticker': ticker,
                'error': 'Insufficient data (need 60+ days)'
            }

        _HOLD_DAYS = 30
        _FEE_PCT = 0.30  # $3 round-trip on $1K

        results = []
        last_exit_idx = -1  # Prevent overlapping trades

        for i in range(50, len(history) - _HOLD_DAYS - 1):
            # Non-overlapping: skip if still in a previous trade
            if i <= last_exit_idx:
                continue

            closes = [h['close'] for h in history[:i+1]]
            volumes = [h.get('volume', 0) for h in history[:i+1]]
            highs = [h.get('high', h['close']) for h in history[:i+1]]
            lows = [h.get('low', h['close']) for h in history[:i+1]]

            # V2.6: RSI(2) < 10 + price > SMA50 (direct check, bypass regime-dependent thresholds)
            rsi2 = self.entry_engine.calc_rsi(closes, 2)
            sma50 = self.entry_engine.calc_sma(closes, 50)
            if rsi2 >= 10 or closes[-1] <= sma50:
                continue

            # Next-day open entry (eliminates look-ahead bias)
            entry_price = history[i + 1].get('open', history[i + 1]['close'])
            if entry_price <= 0:
                entry_price = history[i + 1]['close']
            # Fixed 30-day hold exit
            exit_price = history[i + 1 + _HOLD_DAYS]['close']
            return_pct = ((exit_price - entry_price) / entry_price) * 100 - _FEE_PCT

            # Get regime for classification
            regime_info = RegimeDetector.detect(closes, highs, lows, volumes)

            results.append({
                'date': history[i].get('date', f'day_{i}'),
                'entry_price': entry_price,
                'exit_price': exit_price,
                'return_pct': return_pct,
                'win': return_pct > 0,
                'regime': regime_info.regime.value,
                'rsi2': rsi2,
                'score': 0
            })
            last_exit_idx = i + 1 + _HOLD_DAYS

        if not results:
            return {
                'ticker': ticker,
                'trades': 0,
                'win_rate': 0,
                'avg_return': 0,
                'total_return': 0
            }

        wins = sum(1 for r in results if r['win'])
        returns = [r['return_pct'] for r in results]

        return {
            'ticker': ticker,
            'trades': len(results),
            'wins': wins,
            'losses': len(results) - wins,
            'win_rate': round(wins / len(results) * 100, 1),
            'avg_return': round(sum(returns) / len(returns), 2),
            'total_return': round(sum(returns), 2),
            'best_trade': round(max(returns), 2),
            'worst_trade': round(min(returns), 2),
            'regime_distribution': self._count_regimes(results),
            'sample_trades': results[:10]  # First 10 for review
        }

    def _count_regimes(self, results: List[Dict]) -> Dict[str, int]:
        """Count trades by regime"""
        counts = {}
        for r in results:
            regime = r.get('regime', 'UNKNOWN')
            counts[regime] = counts.get(regime, 0) + 1
        return counts

    def get_model_info(self) -> Dict:
        """
        Get information about the model.

        Returns:
            dict with model details
        """
        return {
            'name': 'ATLAS V2.0',
            'version': '2.0.0',
            'description': 'Adaptive Trading Learning and Signal System',
            'components': {
                'regime_detector': 'BULL/BEAR/SIDEWAYS/HIGH_VOL classification',
                'entry_engine': 'Multi-factor: RSI(2) + Trend + Volume + RSI(14)',
                'exit_engine': 'Time-based exits (research shows better than trailing stops)',
                'learner': 'Thompson Sampling with ε-greedy (10% exploration)',
                'validator': 'Walk-forward validation (WFE > 50% required)'
            },
            'research_basis': [
                'Jha et al. (2025): RL triple-indicator, 85.4% accuracy',
                'QuantifiedStrategies: RSI(2) mean reversion, 91% win rate',
                'arXiv 2024: Thompson Sampling optimization',
                'QuantInsti: Walk-forward validation methodology'
            ],
            'rejection_criteria': [
                'Overfitting Ratio > 1.5',
                'Walk-Forward Efficiency < 50%',
                'OOS Win Rate < 55%'
            ]
        }
