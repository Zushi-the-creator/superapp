"""
Walk-Forward Validator Module
=============================

Based on research:
- QuantInsti: Walk-forward optimization methodology
- Interactive Brokers: "Gold standard" in strategy validation
- Unger Academy: Proper walk-forward implementation
- arXiv 2024: Rigorous validation framework

Walk-Forward Method:
[TRAIN 180d][TEST 30d] → slide → [TRAIN 180d][TEST 30d] → ...

Key Metrics:
- In-Sample Win Rate: Performance during training
- Out-of-Sample Win Rate: TRUE predictive power
- Overfitting Ratio: IS/OOS (must be < 1.5)
- Walk-Forward Efficiency (WFE): OOS/IS (must be > 50%)

Rule: If WFE < 50% or Overfitting Ratio > 1.5, REJECT the strategy.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Callable, Tuple
import statistics

from .entry import EntryEngine, SignalType
from .exit import ExitEngine
from .regime import RegimeDetector


@dataclass
class ValidationWindow:
    """Result of a single validation window"""
    window_num: int
    is_start_idx: int
    is_end_idx: int
    oos_start_idx: int
    oos_end_idx: int
    is_trades: int
    is_wins: int
    is_win_rate: float
    oos_trades: int
    oos_wins: int
    oos_win_rate: float


@dataclass
class WalkForwardResult:
    """Complete walk-forward validation result"""
    ticker: str
    windows_tested: int
    in_sample_win_rate: float
    out_of_sample_win_rate: float
    overfitting_ratio: float
    walk_forward_efficiency: float
    is_valid: bool
    recommendation: str
    windows: List[ValidationWindow] = field(default_factory=list)
    total_is_trades: int = 0
    total_oos_trades: int = 0


class WalkForwardValidator:
    """
    Walk-forward validation to prevent overfitting.

    This is the "gold standard" for strategy validation.

    Process:
    1. Split data into rolling windows
    2. Train on in-sample (IS) period
    3. Test on out-of-sample (OOS) period
    4. Slide window and repeat
    5. Compare IS vs OOS performance

    Rejection Criteria:
    - Overfitting Ratio > 1.5 (IS much better than OOS)
    - WFE < 50% (OOS performance too low)
    - OOS Win Rate < 55% (below profitable threshold)
    """

    # Configuration
    IN_SAMPLE_DAYS = 180  # 6 months training
    OUT_OF_SAMPLE_DAYS = 30  # 1 month testing
    FORWARD_RETURN_DAYS = 30  # V2.6: Fixed 30-day hold (was 7)
    FEE_PCT = 0.30  # $3 round-trip on $1K
    MIN_HISTORY = 50  # Need 50 days for indicators

    # Thresholds
    OVERFITTING_CAUTION = 1.3  # Caution threshold
    OVERFITTING_REJECT = 1.5  # Reject threshold
    MIN_WFE = 50  # Minimum walk-forward efficiency
    MIN_OOS_WIN_RATE = 55  # Minimum OOS win rate

    def __init__(self):
        self.entry_engine = EntryEngine()
        self.exit_engine = ExitEngine()

    def validate(
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
        total_days = len(history)
        window_size = self.IN_SAMPLE_DAYS + self.OUT_OF_SAMPLE_DAYS

        # Check minimum data
        if total_days < window_size + self.MIN_HISTORY + self.FORWARD_RETURN_DAYS:
            return WalkForwardResult(
                ticker=ticker,
                windows_tested=0,
                in_sample_win_rate=0,
                out_of_sample_win_rate=0,
                overfitting_ratio=1.0,
                walk_forward_efficiency=0,
                is_valid=False,
                recommendation="INSUFFICIENT DATA: Need at least 260 days of history"
            )

        windows = []
        all_is_results = []
        all_oos_results = []

        # Slide window through data
        window_start = self.MIN_HISTORY
        step_size = self.OUT_OF_SAMPLE_DAYS  # Step by OOS period

        window_num = 1
        while window_start + window_size + self.FORWARD_RETURN_DAYS <= total_days:
            # Define periods
            is_start = window_start
            is_end = window_start + self.IN_SAMPLE_DAYS
            oos_start = is_end
            oos_end = oos_start + self.OUT_OF_SAMPLE_DAYS

            # Run backtest on in-sample
            is_results = self._run_backtest(history, is_start, is_end)
            all_is_results.extend(is_results)

            # Run backtest on out-of-sample
            oos_results = self._run_backtest(history, oos_start, oos_end)
            all_oos_results.extend(oos_results)

            # Calculate window metrics
            is_wins = sum(1 for r in is_results if r['win'])
            oos_wins = sum(1 for r in oos_results if r['win'])

            is_win_rate = (is_wins / len(is_results) * 100) if is_results else 0
            oos_win_rate = (oos_wins / len(oos_results) * 100) if oos_results else 0

            windows.append(ValidationWindow(
                window_num=window_num,
                is_start_idx=is_start,
                is_end_idx=is_end,
                oos_start_idx=oos_start,
                oos_end_idx=oos_end,
                is_trades=len(is_results),
                is_wins=is_wins,
                is_win_rate=is_win_rate,
                oos_trades=len(oos_results),
                oos_wins=oos_wins,
                oos_win_rate=oos_win_rate
            ))

            window_start += step_size
            window_num += 1

        # Calculate aggregate metrics
        total_is_trades = len(all_is_results)
        total_oos_trades = len(all_oos_results)

        is_wins = sum(1 for r in all_is_results if r['win'])
        oos_wins = sum(1 for r in all_oos_results if r['win'])

        is_win_rate = (is_wins / total_is_trades * 100) if total_is_trades > 0 else 0
        oos_win_rate = (oos_wins / total_oos_trades * 100) if total_oos_trades > 0 else 0

        # Calculate overfitting ratio (IS/OOS)
        if oos_win_rate > 0:
            overfitting_ratio = is_win_rate / oos_win_rate
        else:
            overfitting_ratio = float('inf') if is_win_rate > 0 else 1.0

        # Calculate walk-forward efficiency (OOS/IS)
        if is_win_rate > 0:
            wfe = (oos_win_rate / is_win_rate) * 100
        else:
            wfe = 0

        # Determine validity
        is_valid, recommendation = self._evaluate_result(
            oos_win_rate, overfitting_ratio, wfe, total_oos_trades
        )

        return WalkForwardResult(
            ticker=ticker,
            windows_tested=len(windows),
            in_sample_win_rate=round(is_win_rate, 1),
            out_of_sample_win_rate=round(oos_win_rate, 1),
            overfitting_ratio=round(overfitting_ratio, 2),
            walk_forward_efficiency=round(wfe, 1),
            is_valid=is_valid,
            recommendation=recommendation,
            windows=windows,
            total_is_trades=total_is_trades,
            total_oos_trades=total_oos_trades
        )

    def _run_backtest(
        self,
        history: List[Dict],
        start_idx: int,
        end_idx: int
    ) -> List[Dict]:
        """
        Run backtest on a specific window.
        V2.6: RSI(2) < 10 (universal), next-day open entry, Fixed30d, fee-adjusted, non-overlapping.

        Args:
            history: Full price history
            start_idx: Start index
            end_idx: End index

        Returns:
            List of trade results
        """
        results = []
        last_exit_idx = -1  # Prevent overlapping trades

        for i in range(start_idx, min(end_idx, len(history) - self.FORWARD_RETURN_DAYS - 1)):
            # Need enough history for indicators
            if i < self.MIN_HISTORY:
                continue

            # Non-overlapping: skip if still in a previous trade
            if i <= last_exit_idx:
                continue

            # Extract data up to this point
            closes = [h['close'] for h in history[:i+1]]

            # V2.6: Direct RSI(2) < 10 + price > SMA50 check (not regime-dependent)
            rsi2 = self.entry_engine.calc_rsi(closes, 2)
            sma50 = self.entry_engine.calc_sma(closes, 50)
            if rsi2 >= 10 or closes[-1] <= sma50:
                continue

            # Next-day open entry (eliminates look-ahead bias)
            entry_price = history[i + 1].get('open', history[i + 1]['close'])
            if entry_price <= 0:
                entry_price = history[i + 1]['close']
            # Fixed 30-day hold exit
            exit_idx = i + 1 + self.FORWARD_RETURN_DAYS
            if exit_idx >= len(history):
                continue
            exit_price = history[exit_idx]['close']
            return_pct = ((exit_price - entry_price) / entry_price) * 100 - self.FEE_PCT

            results.append({
                'date': history[i].get('date', f'day_{i}'),
                'entry_price': entry_price,
                'exit_price': exit_price,
                'return_pct': return_pct,
                'win': return_pct > 0,
                'rsi2': rsi2,
                'score': 0
            })
            last_exit_idx = exit_idx

        return results

    def _evaluate_result(
        self,
        oos_win_rate: float,
        overfitting_ratio: float,
        wfe: float,
        oos_trades: int
    ) -> Tuple[bool, str]:
        """
        Evaluate validation result and generate recommendation.

        Args:
            oos_win_rate: Out-of-sample win rate
            overfitting_ratio: IS/OOS ratio
            wfe: Walk-forward efficiency
            oos_trades: Number of OOS trades

        Returns:
            Tuple of (is_valid, recommendation)
        """
        issues = []

        # Check sample size
        if oos_trades < 10:
            return False, f"INSUFFICIENT TRADES: Only {oos_trades} OOS trades (need 10+)"

        # Check overfitting ratio
        if overfitting_ratio >= self.OVERFITTING_REJECT:
            issues.append(f"SEVERE OVERFITTING: Ratio {overfitting_ratio:.2f} >= {self.OVERFITTING_REJECT}")
        elif overfitting_ratio >= self.OVERFITTING_CAUTION:
            issues.append(f"MODERATE OVERFITTING: Ratio {overfitting_ratio:.2f} >= {self.OVERFITTING_CAUTION}")

        # Check WFE
        if wfe < self.MIN_WFE:
            issues.append(f"LOW WFE: {wfe:.1f}% < {self.MIN_WFE}% threshold")

        # Check OOS win rate
        if oos_win_rate < self.MIN_OOS_WIN_RATE:
            issues.append(f"LOW OOS WIN RATE: {oos_win_rate:.1f}% < {self.MIN_OOS_WIN_RATE}% threshold")

        # Determine validity
        if any("SEVERE" in i for i in issues):
            is_valid = False
            recommendation = f"REJECT: {'; '.join(issues)}"
        elif any("LOW OOS WIN RATE" in i for i in issues):
            is_valid = False
            recommendation = f"REJECT: {'; '.join(issues)}"
        elif issues:
            is_valid = False
            recommendation = f"CAUTION: {'; '.join(issues)}"
        else:
            is_valid = True
            recommendation = f"VALID: OOS Win Rate {oos_win_rate:.1f}%, WFE {wfe:.1f}%, Overfitting Ratio {overfitting_ratio:.2f}"

        return is_valid, recommendation

    def compare_strategies(
        self,
        history: List[Dict],
        strategy_a_func: Callable,
        strategy_b_func: Callable,
        ticker: str = "UNKNOWN"
    ) -> Dict:
        """
        Compare two strategies using walk-forward validation.

        Args:
            history: Price history
            strategy_a_func: Function(closes, volumes) -> (signal, confidence)
            strategy_b_func: Function(closes, volumes) -> (signal, confidence)
            ticker: Stock symbol

        Returns:
            Comparison results
        """
        # Validate both strategies
        # This is a simplified comparison - in production you'd use the actual strategy functions

        result_a = self.validate(history, f"{ticker}_A")
        result_b = self.validate(history, f"{ticker}_B")

        winner = "A" if result_a.out_of_sample_win_rate > result_b.out_of_sample_win_rate else "B"
        improvement = abs(result_a.out_of_sample_win_rate - result_b.out_of_sample_win_rate)

        return {
            "ticker": ticker,
            "strategy_a": {
                "oos_win_rate": result_a.out_of_sample_win_rate,
                "wfe": result_a.walk_forward_efficiency,
                "is_valid": result_a.is_valid,
            },
            "strategy_b": {
                "oos_win_rate": result_b.out_of_sample_win_rate,
                "wfe": result_b.walk_forward_efficiency,
                "is_valid": result_b.is_valid,
            },
            "winner": winner,
            "improvement": improvement,
        }
