"""
ATLAS Core Model
=================

Main unified model tying all components together.
Single entry point for all ATLAS trading operations.

Usage:
    from atlas import ATLASModel

    model = ATLASModel(account_value=3700)

    # Analyze a stock
    analysis = model.analyze("NVDA", closes, volumes)

    if analysis.entry_signal.signal == SignalType.BUY:
        size = model.get_position_size(analysis)
        print(f"BUY {size.shares} shares")

    # Check exit for existing position
    exit_signal = model.check_exit(
        entry_price=180.0,
        current_price=190.0,
        highest_price=195.0,
        closes=closes
    )
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from .database import ATLASDatabase, TradeRecord
from .indicators import Indicators, IndicatorSnapshot
from .regime import RegimeDetector, MarketRegime, RegimeInfo
from .entry import EntryEngine, EntrySignal, SignalType, check_sentiment_veto
from .exits import ExitSystem, ExitSignal, ExitAction
from .sizing import PositionSizer, PositionSize
from .learning import LearningEngine
from .backtest import BacktestEngine, BacktestResult, WalkForwardResult


@dataclass
class ATLASAnalysis:
    """Complete analysis output"""
    ticker: str
    timestamp: str
    regime: RegimeInfo
    entry_signal: EntrySignal
    indicators: IndicatorSnapshot
    position_size: Optional[PositionSize] = None
    notes: List[str] = None


@dataclass
class ATLASPosition:
    """Active position being tracked"""
    ticker: str
    trade_id: int
    entry_date: str
    entry_price: float
    shares: float
    highest_price: float
    regime_at_entry: MarketRegime


class ATLASModel:
    """
    ATLAS: Adaptive Trading Learning and Signal System

    Unified trading model that:
    - Uses ONE entry rule (RSI(2) mean reversion in uptrend)
    - Adapts via regime detection (BULL/BEAR/SIDEWAYS/HIGH_VOL)
    - Uses mechanical exits (regime-aware)
    - Sizes positions via Kelly Criterion
    - Learns from every trade (Thompson Sampling)

    This replaces 30+ individual models with one adaptive system.
    """

    def __init__(
        self,
        account_value: float = 3700,
        db_path: str = None
    ):
        """
        Initialize ATLAS model.

        Args:
            account_value: Total account value in dollars
            db_path: Path to database (uses default if None)
        """
        # Initialize components
        self.db = ATLASDatabase(db_path)
        self.entry_engine = EntryEngine(self.db)
        self.exit_system = ExitSystem(self.db)
        self.sizer = PositionSizer(account_value)
        self.learning = LearningEngine(self.db)
        self.backtest = BacktestEngine()

        # Track active positions
        self.positions: Dict[str, ATLASPosition] = {}

        # Account value
        self.account_value = account_value

    def update_account_value(self, value: float):
        """Update account value for position sizing"""
        self.account_value = value
        self.sizer.update_account_value(value)

    # ==================== ANALYSIS ====================

    def analyze(
        self,
        ticker: str,
        closes: List[float],
        volumes: List[float] = None,
        highs: List[float] = None,
        lows: List[float] = None,
        days_to_earnings: int = None,
        negative_news: int = 0,
        positive_news: int = 0,
        current_price: float = None
    ) -> ATLASAnalysis:
        """
        Complete analysis for a stock.

        Args:
            ticker: Stock symbol
            closes: List of closing prices (50+ recommended)
            volumes: Optional volume data
            highs: Optional high prices
            lows: Optional low prices
            days_to_earnings: Days until next earnings
            negative_news: Count of negative news articles
            positive_news: Count of positive news articles
            current_price: Current price (uses last close if None)

        Returns:
            ATLASAnalysis with entry signal and sizing
        """
        # Check sentiment veto
        veto, veto_reason = check_sentiment_veto(
            ticker, days_to_earnings, negative_news, positive_news
        )

        # Get regime analysis
        regime_info = RegimeDetector.get_full_analysis(closes, highs, lows)

        # Get indicator snapshot
        indicators = Indicators.get_snapshot(closes, highs, lows, volumes)

        # Generate entry signal
        entry_signal = self.entry_engine.generate_signal(
            closes, volumes, highs, lows,
            sentiment_veto=veto,
            veto_reason=veto_reason
        )

        # Calculate position size if BUY signal
        position_size = None
        if entry_signal.signal == SignalType.BUY:
            price = current_price or closes[-1]
            win_rate = self.learning.get_regime_win_rate(regime_info.regime.value)

            # Get risk/reward from regime params
            params = RegimeDetector.get_params(regime_info.regime)
            stop_pct = params.get("stop_pct", 5.0)
            target_pct = params.get("target_pct", 10.0)
            reward_risk = target_pct / stop_pct if stop_pct > 0 else 2.0

            position_size = self.sizer.calculate_position_size(
                win_prob=win_rate / 100,
                reward_risk_ratio=reward_risk,
                current_price=price,
                atr_pct=indicators.atr14 / price if price > 0 else 0.02,
                regime=regime_info.regime
            )

        # Build notes
        notes = entry_signal.reasons.copy()
        if veto:
            notes.append(f"VETOED: {veto_reason}")
        if position_size and not position_size.fee_feasible:
            notes.append("WARNING: Position too small for fees")

        return ATLASAnalysis(
            ticker=ticker,
            timestamp=datetime.now().isoformat(),
            regime=regime_info,
            entry_signal=entry_signal,
            indicators=indicators,
            position_size=position_size,
            notes=notes,
        )

    def quick_signal(
        self,
        closes: List[float],
        volumes: List[float] = None
    ) -> Tuple[str, float, str]:
        """
        Quick signal check (for scanning).

        Args:
            closes: List of closing prices
            volumes: Optional volumes

        Returns:
            Tuple of (signal, confidence, regime)
        """
        signal = self.entry_engine.generate_signal(closes, volumes)
        return signal.signal.value, signal.confidence, signal.regime.value

    # ==================== EXITS ====================

    def check_exit(
        self,
        entry_price: float,
        current_price: float,
        highest_price: float,
        closes: List[float],
        days_held: int = 0,
        ticker: str = None
    ) -> ExitSignal:
        """
        Check if position should be exited.

        Args:
            entry_price: Entry price
            current_price: Current price
            highest_price: Highest since entry
            closes: Recent closes for regime
            days_held: Days held
            ticker: Optional ticker

        Returns:
            ExitSignal with recommendation
        """
        return self.exit_system.get_exit_signal(
            entry_price=entry_price,
            current_price=current_price,
            highest_price=highest_price,
            closes=closes,
            days_held=days_held,
            ticker=ticker
        )

    def check_all_positions(
        self,
        current_prices: Dict[str, float],
        closes_by_ticker: Dict[str, List[float]]
    ) -> Dict[str, ExitSignal]:
        """
        Check exits for all tracked positions.

        Args:
            current_prices: Dict of ticker -> current price
            closes_by_ticker: Dict of ticker -> closes list

        Returns:
            Dict of ticker -> ExitSignal
        """
        signals = {}

        for ticker, position in self.positions.items():
            if ticker not in current_prices or ticker not in closes_by_ticker:
                continue

            current = current_prices[ticker]
            closes = closes_by_ticker[ticker]

            # Update highest price
            if current > position.highest_price:
                position.highest_price = current

            # Calculate days held
            try:
                entry_dt = datetime.fromisoformat(position.entry_date.split("T")[0])
                days_held = (datetime.now() - entry_dt).days
            except:
                days_held = 0

            signals[ticker] = self.check_exit(
                entry_price=position.entry_price,
                current_price=current,
                highest_price=position.highest_price,
                closes=closes,
                days_held=days_held,
                ticker=ticker
            )

        return signals

    # ==================== POSITION TRACKING ====================

    def open_position(
        self,
        ticker: str,
        entry_price: float,
        shares: float,
        regime: MarketRegime = None,
        closes: List[float] = None
    ) -> int:
        """
        Open and track a new position.

        Args:
            ticker: Stock symbol
            entry_price: Entry price
            shares: Number of shares
            regime: Market regime (detected if None)
            closes: Closes for regime detection

        Returns:
            Trade ID
        """
        if regime is None and closes:
            regime = RegimeDetector.detect(closes)
        elif regime is None:
            regime = MarketRegime.SIDEWAYS

        # Get indicators for recording
        rsi2 = None
        rsi14 = None
        vol_ratio = None

        if closes:
            rsi2 = Indicators.calc_rsi(closes, 2)
            rsi14 = Indicators.calc_rsi(closes, 14)

        # Create trade record
        trade = TradeRecord(
            ticker=ticker,
            signal="BUY",
            entry_date=datetime.now().isoformat(),
            entry_price=entry_price,
            regime=regime.value,
            rsi2_at_entry=rsi2,
            rsi14_at_entry=rsi14,
            volume_ratio=vol_ratio,
            position_size=entry_price * shares,
        )

        trade_id = self.learning.record_trade(trade)

        # Track position
        self.positions[ticker] = ATLASPosition(
            ticker=ticker,
            trade_id=trade_id,
            entry_date=datetime.now().isoformat(),
            entry_price=entry_price,
            shares=shares,
            highest_price=entry_price,
            regime_at_entry=regime,
        )

        return trade_id

    def close_position(
        self,
        ticker: str,
        exit_price: float,
        exit_reason: str = None
    ) -> Dict:
        """
        Close a tracked position.

        Args:
            ticker: Stock symbol
            exit_price: Exit price
            exit_reason: Reason for exit

        Returns:
            Trade summary
        """
        if ticker not in self.positions:
            return {"error": f"No position for {ticker}"}

        position = self.positions[ticker]

        # Close trade in database
        self.learning.close_trade(
            trade_id=position.trade_id,
            exit_date=datetime.now().isoformat(),
            exit_price=exit_price,
            exit_reason=exit_reason
        )

        # Calculate return
        return_pct = ((exit_price - position.entry_price) / position.entry_price) * 100
        profit = (exit_price - position.entry_price) * position.shares

        # Remove from tracking
        del self.positions[ticker]

        return {
            "ticker": ticker,
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "shares": position.shares,
            "return_pct": round(return_pct, 2),
            "profit": round(profit, 2),
            "exit_reason": exit_reason,
            "regime": position.regime_at_entry.value,
        }

    # ==================== LEARNING ====================

    def run_learning_cycle(self) -> Dict:
        """
        Run learning cycle to update parameters.

        Returns:
            Dict with updates made
        """
        return self.learning.run_learning_cycle()

    def get_learning_summary(self) -> Dict:
        """
        Get summary of learning state.

        Returns:
            Learning summary by regime
        """
        return self.learning.get_learning_summary()

    # ==================== BACKTESTING ====================

    def backtest_stock(
        self,
        history: List[Dict],
        ticker: str = "UNKNOWN"
    ) -> BacktestResult:
        """
        Backtest ATLAS on a stock.

        Args:
            history: Price history (list of dicts with OHLCV)
            ticker: Stock symbol

        Returns:
            BacktestResult
        """
        return self.backtest.run_backtest(history, ticker)

    def validate_model(
        self,
        history: List[Dict],
        ticker: str = "UNKNOWN"
    ) -> WalkForwardResult:
        """
        Run walk-forward validation.

        Args:
            history: Price history
            ticker: Stock symbol

        Returns:
            WalkForwardResult with overfitting check
        """
        return self.backtest.walk_forward_validate(history, ticker)

    # ==================== UTILITIES ====================

    def get_stats(self) -> Dict:
        """Get overall performance statistics"""
        return self.db.get_all_stats()

    def get_regime_stats(self, regime: str) -> Dict:
        """Get stats for a specific regime"""
        return self.db.get_regime_stats(regime)

    def get_open_positions(self) -> Dict[str, ATLASPosition]:
        """Get all tracked positions"""
        return self.positions.copy()

    def export_data(self, output_path: str = None) -> Dict:
        """Export all data to JSON"""
        return self.db.export_to_json(output_path)

    def get_signal_summary(
        self,
        ticker: str,
        closes: List[float],
        volumes: List[float] = None
    ) -> str:
        """
        Get human-readable signal summary.

        Returns:
            Formatted string summary
        """
        analysis = self.analyze(ticker, closes, volumes)

        lines = [
            f"=== ATLAS Analysis: {ticker} ===",
            f"Regime: {analysis.regime.regime.value}",
            f"Signal: {analysis.entry_signal.signal.value} ({analysis.entry_signal.confidence:.0f}%)",
            "",
            "Indicators:",
            f"  RSI(2): {analysis.indicators.rsi2:.0f}",
            f"  RSI(14): {analysis.indicators.rsi14:.0f}",
            f"  Price: ${analysis.indicators.price:.2f}",
            f"  SMA(50): ${analysis.indicators.sma50:.2f}",
            f"  Volume Ratio: {analysis.indicators.volume_ratio:.1f}x",
            "",
            "Reasons:",
        ]

        for reason in analysis.entry_signal.reasons:
            lines.append(f"  - {reason}")

        if analysis.position_size:
            lines.extend([
                "",
                "Position Sizing:",
                f"  Size: ${analysis.position_size.size_dollars:.2f} ({analysis.position_size.size_pct:.1f}%)",
                f"  Shares: {analysis.position_size.shares}",
                f"  Kelly: {analysis.position_size.kelly_fraction:.3f}",
                f"  Notes: {analysis.position_size.notes}",
            ])

        return "\n".join(lines)
