"""
ATLAS Backtest Engine Module
==============================

Walk-forward validation with overfitting detection.

Walk-Forward Validation:
    [TRAIN 180d][TEST 30d] → [TRAIN 180d][TEST 30d] → ...

Key Metrics:
- In-Sample Win Rate: Performance during training
- Out-of-Sample Win Rate: TRUE predictive power
- Overfitting Ratio: IS/OOS (must be < 1.5)

Academic References:
- Akşehir & Kılıç (2024): Walk-forward validation methodology
- QuantInsti: Walk-forward optimization
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
import statistics

from .indicators import Indicators
from .regime import RegimeDetector, MarketRegime
from .entry import EntryEngine, SignalType
from .exits import ExitSystem, ExitAction


@dataclass
class BacktestResult:
    """Result of a backtest run"""
    ticker: str
    period_days: int
    total_signals: int
    wins: int
    losses: int
    win_rate: float
    avg_return: float
    total_return: float
    max_drawdown: float
    sharpe_ratio: float
    regime_distribution: Dict[str, int]
    trades: List[Dict] = field(default_factory=list)


@dataclass
class WalkForwardResult:
    """Result of walk-forward validation"""
    ticker: str
    windows_tested: int
    in_sample_win_rate: float
    out_of_sample_win_rate: float
    overfitting_ratio: float
    is_valid: bool
    recommendation: str
    details: List[Dict] = field(default_factory=list)


class BacktestEngine:
    """
    Backtesting engine with walk-forward validation.

    Features:
    - Simple point-in-time backtesting
    - Walk-forward validation
    - Overfitting detection
    - Regime-aware analysis
    """

    # Walk-forward configuration
    IN_SAMPLE_DAYS = 180  # Training period
    OUT_OF_SAMPLE_DAYS = 30  # Testing period
    FORWARD_RETURN_DAYS = 7  # Days to hold after signal

    # Overfitting thresholds
    OVERFITTING_CAUTION = 1.5
    OVERFITTING_REJECT = 2.0

    def __init__(self):
        """Initialize backtest engine"""
        self.entry_engine = EntryEngine()
        self.exit_system = ExitSystem()

    def run_backtest(
        self,
        history: List[Dict],
        ticker: str = "UNKNOWN",
        forward_days: int = 7,
        period_days: int = 180
    ) -> BacktestResult:
        """
        Run simple backtest on historical data.

        Args:
            history: List of dicts with 'date', 'open', 'high', 'low', 'close', 'volume'
            ticker: Stock symbol
            forward_days: Days to measure forward return
            period_days: Days of history to test

        Returns:
            BacktestResult with performance metrics
        """
        if len(history) < 200:
            return BacktestResult(
                ticker=ticker,
                period_days=0,
                total_signals=0,
                wins=0,
                losses=0,
                win_rate=0,
                avg_return=0,
                total_return=0,
                max_drawdown=0,
                sharpe_ratio=0,
                regime_distribution={},
            )

        results = []
        regime_counts = {"BULL": 0, "BEAR": 0, "SIDEWAYS": 0, "HIGH_VOL": 0}

        # Determine start point
        start_idx = max(200, len(history) - period_days)

        for i in range(start_idx, len(history) - forward_days):
            day = history[i]

            # Get data up to this point
            closes = [h['close'] for h in history[:i+1]]
            volumes = [h.get('volume', 0) for h in history[:i+1]]
            highs = [h.get('high', h['close']) for h in history[:i+1]]
            lows = [h.get('low', h['close']) for h in history[:i+1]]

            # Generate entry signal
            signal = self.entry_engine.generate_signal(closes, volumes, highs, lows)

            # Track regime
            regime_counts[signal.regime.value] = regime_counts.get(signal.regime.value, 0) + 1

            if signal.signal != SignalType.BUY:
                continue

            # Calculate forward return
            current_price = day['close']
            future_price = history[i + forward_days]['close']
            forward_return = ((future_price - current_price) / current_price) * 100

            # BUY is correct if price goes up
            correct = forward_return > 0

            results.append({
                'date': day.get('date', f'day_{i}'),
                'signal': signal.signal.value,
                'confidence': signal.confidence,
                'regime': signal.regime.value,
                'entry_price': current_price,
                'exit_price': future_price,
                'forward_return': forward_return,
                'correct': correct,
                'reasons': signal.reasons,
            })

        # Calculate statistics
        total = len(results)
        wins = sum(1 for r in results if r['correct'])
        losses = total - wins

        returns = [r['forward_return'] for r in results]
        avg_return = statistics.mean(returns) if returns else 0
        total_return = sum(returns)

        # Calculate drawdown
        max_drawdown = self._calculate_max_drawdown(returns)

        # Calculate Sharpe ratio (simplified)
        if returns and len(returns) > 1:
            std_dev = statistics.stdev(returns)
            sharpe = (avg_return / std_dev) if std_dev > 0 else 0
        else:
            sharpe = 0

        return BacktestResult(
            ticker=ticker,
            period_days=period_days,
            total_signals=total,
            wins=wins,
            losses=losses,
            win_rate=(wins / total * 100) if total > 0 else 0,
            avg_return=avg_return,
            total_return=total_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            regime_distribution=regime_counts,
            trades=results[:50],  # Keep first 50 for review
        )

    def walk_forward_validate(
        self,
        history: List[Dict],
        ticker: str = "UNKNOWN"
    ) -> WalkForwardResult:
        """
        Run walk-forward validation to detect overfitting.

        Walk-Forward Method:
        [TRAIN 180d][TEST 30d] → slide window → repeat

        Args:
            history: List of price dicts
            ticker: Stock symbol

        Returns:
            WalkForwardResult with validation metrics
        """
        total_days = len(history)
        window_size = self.IN_SAMPLE_DAYS + self.OUT_OF_SAMPLE_DAYS

        if total_days < window_size + 50:
            return WalkForwardResult(
                ticker=ticker,
                windows_tested=0,
                in_sample_win_rate=0,
                out_of_sample_win_rate=0,
                overfitting_ratio=1.0,
                is_valid=False,
                recommendation="Insufficient data for walk-forward validation",
            )

        in_sample_results = []
        out_of_sample_results = []
        window_details = []

        # Slide window through data
        window_start = 200  # Need history for indicators
        step_size = self.OUT_OF_SAMPLE_DAYS

        while window_start + window_size <= total_days - self.FORWARD_RETURN_DAYS:
            # In-sample period
            is_start = window_start
            is_end = window_start + self.IN_SAMPLE_DAYS

            # Out-of-sample period
            oos_start = is_end
            oos_end = oos_start + self.OUT_OF_SAMPLE_DAYS

            # Run backtest on in-sample
            is_history = history[:is_end]
            is_result = self._run_window_backtest(is_history, is_start, is_end)
            in_sample_results.extend(is_result)

            # Run backtest on out-of-sample
            oos_history = history[:oos_end]
            oos_result = self._run_window_backtest(oos_history, oos_start, oos_end)
            out_of_sample_results.extend(oos_result)

            window_details.append({
                "window": len(window_details) + 1,
                "is_trades": len(is_result),
                "is_wins": sum(1 for r in is_result if r['correct']),
                "oos_trades": len(oos_result),
                "oos_wins": sum(1 for r in oos_result if r['correct']),
            })

            window_start += step_size

        # Calculate aggregate metrics
        is_wins = sum(1 for r in in_sample_results if r['correct'])
        is_total = len(in_sample_results)
        is_win_rate = (is_wins / is_total * 100) if is_total > 0 else 0

        oos_wins = sum(1 for r in out_of_sample_results if r['correct'])
        oos_total = len(out_of_sample_results)
        oos_win_rate = (oos_wins / oos_total * 100) if oos_total > 0 else 0

        # Calculate overfitting ratio
        if oos_win_rate > 0:
            overfitting_ratio = is_win_rate / oos_win_rate
        else:
            overfitting_ratio = float('inf') if is_win_rate > 0 else 1.0

        # Determine validity
        if overfitting_ratio >= self.OVERFITTING_REJECT:
            is_valid = False
            recommendation = f"REJECT: Severe overfitting (ratio {overfitting_ratio:.2f} >= {self.OVERFITTING_REJECT})"
        elif overfitting_ratio >= self.OVERFITTING_CAUTION:
            is_valid = False
            recommendation = f"CAUTION: Moderate overfitting (ratio {overfitting_ratio:.2f} >= {self.OVERFITTING_CAUTION})"
        elif oos_win_rate < 50:
            is_valid = False
            recommendation = f"REJECT: OOS win rate {oos_win_rate:.1f}% < 50%"
        else:
            is_valid = True
            recommendation = f"VALID: OOS win rate {oos_win_rate:.1f}%, ratio {overfitting_ratio:.2f}"

        return WalkForwardResult(
            ticker=ticker,
            windows_tested=len(window_details),
            in_sample_win_rate=is_win_rate,
            out_of_sample_win_rate=oos_win_rate,
            overfitting_ratio=overfitting_ratio,
            is_valid=is_valid,
            recommendation=recommendation,
            details=window_details,
        )

    def _run_window_backtest(
        self,
        history: List[Dict],
        start_idx: int,
        end_idx: int
    ) -> List[Dict]:
        """Run backtest on a specific window"""
        results = []

        for i in range(start_idx, min(end_idx, len(history) - self.FORWARD_RETURN_DAYS)):
            day = history[i]

            closes = [h['close'] for h in history[:i+1]]
            volumes = [h.get('volume', 0) for h in history[:i+1]]

            if len(closes) < 50:
                continue

            signal = self.entry_engine.generate_signal(closes, volumes)

            if signal.signal != SignalType.BUY:
                continue

            current_price = day['close']
            future_price = history[i + self.FORWARD_RETURN_DAYS]['close']
            forward_return = ((future_price - current_price) / current_price) * 100

            results.append({
                'date': day.get('date', f'day_{i}'),
                'correct': forward_return > 0,
                'return': forward_return,
            })

        return results

    def _calculate_max_drawdown(self, returns: List[float]) -> float:
        """Calculate maximum drawdown from returns series"""
        if not returns:
            return 0

        cumulative = 0
        peak = 0
        max_dd = 0

        for ret in returns:
            cumulative += ret
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def compare_models(
        self,
        history: List[Dict],
        model_a_func: Callable,
        model_b_func: Callable,
        ticker: str = "UNKNOWN"
    ) -> Dict:
        """
        Compare two model functions.

        Args:
            history: Price history
            model_a_func: Function(closes, volumes) -> (signal, confidence)
            model_b_func: Function(closes, volumes) -> (signal, confidence)
            ticker: Stock symbol

        Returns:
            Comparison results
        """
        results_a = []
        results_b = []

        start_idx = max(200, len(history) - 180)

        for i in range(start_idx, len(history) - 7):
            day = history[i]
            closes = [h['close'] for h in history[:i+1]]
            volumes = [h.get('volume', 0) for h in history[:i+1]]

            # Model A
            sig_a, conf_a = model_a_func(closes, volumes)
            if sig_a == "BUY":
                ret = ((history[i+7]['close'] - day['close']) / day['close']) * 100
                results_a.append({'correct': ret > 0, 'return': ret})

            # Model B
            sig_b, conf_b = model_b_func(closes, volumes)
            if sig_b == "BUY":
                ret = ((history[i+7]['close'] - day['close']) / day['close']) * 100
                results_b.append({'correct': ret > 0, 'return': ret})

        # Calculate stats
        def calc_stats(results):
            if not results:
                return {"trades": 0, "win_rate": 0, "avg_return": 0}
            wins = sum(1 for r in results if r['correct'])
            return {
                "trades": len(results),
                "win_rate": wins / len(results) * 100,
                "avg_return": sum(r['return'] for r in results) / len(results),
            }

        stats_a = calc_stats(results_a)
        stats_b = calc_stats(results_b)

        winner = "A" if stats_a["win_rate"] > stats_b["win_rate"] else "B"
        improvement = abs(stats_a["win_rate"] - stats_b["win_rate"])

        return {
            "ticker": ticker,
            "model_a": stats_a,
            "model_b": stats_b,
            "winner": winner,
            "improvement": improvement,
        }
