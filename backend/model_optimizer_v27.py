"""
V27.0 Self-Improving Model Optimizer

Goal: Achieve 75%+ win rate on all portfolio positions

Features:
1. Parameter optimization per stock
2. Regime-adaptive thresholds
3. Continuous learning from backtests
4. Stock scanner with win rate filter
5. Model persistence and improvement tracking

Author: Claude Trading Assistant
Created: 2026-01-23
"""

import json
import os
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from enum import Enum


class Regime(Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    HIGH_VOL = "HIGH_VOL"


@dataclass
class ModelParams:
    """Optimizable model parameters"""
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    rsi2_period: int = 2
    rsi2_extreme_low: float = 5.0
    rsi2_extreme_high: float = 95.0
    sma_short: int = 20
    sma_long: int = 50
    bb_period: int = 20
    bb_std: float = 2.0
    min_confidence: float = 60.0
    regime_filter: bool = True


@dataclass
class BacktestResult:
    """Result from backtesting a parameter set"""
    ticker: str
    params: ModelParams
    total_signals: int
    buy_signals: int
    buy_wins: int
    buy_win_rate: float
    sell_signals: int
    sell_wins: int
    sell_win_rate: float
    total_win_rate: float
    avg_return: float
    max_drawdown: float
    sharpe_ratio: float
    regime: str


@dataclass
class StockProfile:
    """Learned profile for a stock"""
    ticker: str
    best_params: ModelParams
    best_win_rate: float
    regime: str
    volatility: float
    last_updated: str
    backtest_history: List[Dict]


class TechnicalIndicators:
    """Technical indicator calculations"""

    @staticmethod
    def calc_rsi(closes: List[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        gains, losses = [], []
        for i in range(1, period + 1):
            diff = closes[-i] - closes[-(i+1)]
            gains.append(max(0, diff))
            losses.append(max(0, -diff))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calc_sma(closes: List[float], period: int) -> float:
        if len(closes) < period:
            return closes[-1] if closes else 0
        return sum(closes[-period:]) / period

    @staticmethod
    def calc_ema(closes: List[float], period: int) -> float:
        if len(closes) < period:
            return closes[-1] if closes else 0
        multiplier = 2 / (period + 1)
        ema = sum(closes[:period]) / period
        for price in closes[period:]:
            ema = (price - ema) * multiplier + ema
        return ema

    @staticmethod
    def calc_bollinger(closes: List[float], period: int = 20, std_mult: float = 2.0) -> Tuple[float, float, float]:
        if len(closes) < period:
            return closes[-1], closes[-1], closes[-1]
        sma = sum(closes[-period:]) / period
        variance = sum((x - sma) ** 2 for x in closes[-period:]) / period
        std = variance ** 0.5
        return sma + std_mult * std, sma, sma - std_mult * std

    @staticmethod
    def calc_volatility(closes: List[float], period: int = 20) -> float:
        if len(closes) < period + 1:
            return 0.3
        returns = [(closes[i] - closes[i-1]) / closes[i-1]
                   for i in range(len(closes) - period, len(closes))]
        return statistics.stdev(returns) * (252 ** 0.5)

    @staticmethod
    def detect_regime(closes: List[float]) -> Tuple[Regime, Dict]:
        if len(closes) < 50:
            return Regime.SIDEWAYS, {}

        price = closes[-1]
        sma20 = TechnicalIndicators.calc_sma(closes, 20)
        sma50 = TechnicalIndicators.calc_sma(closes, 50)
        volatility = TechnicalIndicators.calc_volatility(closes, 20)

        # Check for high volatility first
        if volatility > 0.50:
            return Regime.HIGH_VOL, {"volatility": volatility}

        # Trend detection
        above_sma20 = price > sma20
        above_sma50 = price > sma50

        if above_sma20 and above_sma50:
            return Regime.BULL, {"volatility": volatility}
        elif not above_sma20 and not above_sma50:
            return Regime.BEAR, {"volatility": volatility}
        else:
            return Regime.SIDEWAYS, {"volatility": volatility}


class AdaptiveModel:
    """
    Self-improving trading model with parameter optimization
    """

    def __init__(self, params: ModelParams = None):
        self.params = params or ModelParams()
        self.indicators = TechnicalIndicators()

    def generate_signal(self, closes: List[float], volumes: List[float] = None) -> Tuple[str, float, str]:
        """Generate BUY/SELL/HOLD signal with confidence"""
        if len(closes) < max(self.params.sma_long, self.params.bb_period) + 10:
            return "HOLD", 50.0, "Insufficient data"

        price = closes[-1]

        # Calculate indicators with optimized parameters
        rsi = self.indicators.calc_rsi(closes, self.params.rsi_period)
        rsi2 = self.indicators.calc_rsi(closes, self.params.rsi2_period)
        sma_short = self.indicators.calc_sma(closes, self.params.sma_short)
        sma_long = self.indicators.calc_sma(closes, self.params.sma_long)
        bb_upper, bb_mid, bb_lower = self.indicators.calc_bollinger(
            closes, self.params.bb_period, self.params.bb_std
        )

        # Detect regime
        regime, _ = self.indicators.detect_regime(closes)

        # Score-based signal generation
        buy_score = 0
        sell_score = 0
        reasons = []

        # RSI signals
        if rsi < self.params.rsi_oversold:
            buy_score += 25
            reasons.append(f"RSI({self.params.rsi_period})={rsi:.0f} oversold")
        elif rsi > self.params.rsi_overbought:
            sell_score += 25
            reasons.append(f"RSI({self.params.rsi_period})={rsi:.0f} overbought")

        # RSI(2) extreme signals
        if rsi2 < self.params.rsi2_extreme_low:
            buy_score += 35
            reasons.append(f"RSI(2)={rsi2:.0f} extreme")
        elif rsi2 > self.params.rsi2_extreme_high:
            sell_score += 35
            reasons.append(f"RSI(2)={rsi2:.0f} extreme")

        # Bollinger Band signals
        if price <= bb_lower * 1.02:
            buy_score += 20
            reasons.append("Near BB lower")
        elif price >= bb_upper * 0.98:
            sell_score += 20
            reasons.append("Near BB upper")

        # Trend signals
        if price > sma_short > sma_long:
            buy_score += 10
            reasons.append("Uptrend")
        elif price < sma_short < sma_long:
            sell_score += 10
            reasons.append("Downtrend")

        # Regime filter
        if self.params.regime_filter:
            if regime == Regime.BULL:
                sell_score = int(sell_score * 0.3)
                if sell_score > 0:
                    reasons.append("(BULL: SELL suppressed)")
            elif regime == Regime.BEAR:
                buy_score = int(buy_score * 0.3)
                if buy_score > 0:
                    reasons.append("(BEAR: BUY suppressed)")
            elif regime == Regime.HIGH_VOL:
                buy_score = int(buy_score * 0.5)
                sell_score = int(sell_score * 0.5)

        # Determine signal
        if buy_score >= 50 and buy_score > sell_score:
            confidence = min(95, 50 + buy_score)
            return "BUY", confidence, " + ".join(reasons)
        elif sell_score >= 50 and sell_score > buy_score:
            confidence = min(95, 50 + sell_score)
            return "SELL", confidence, " + ".join(reasons)
        else:
            return "HOLD", 50.0, f"No strong signal (BUY:{buy_score}, SELL:{sell_score})"


class ModelOptimizer:
    """
    Optimizes model parameters for each stock to achieve 75%+ win rate
    """

    TARGET_WIN_RATE = 75.0

    def __init__(self, db_path: str = "data/model_learning.json"):
        self.db_path = db_path
        self.stock_profiles: Dict[str, StockProfile] = {}
        self.indicators = TechnicalIndicators()
        self._load_profiles()

    def _load_profiles(self):
        """Load learned stock profiles from disk"""
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, 'r') as f:
                    data = json.load(f)
                    for ticker, profile_data in data.get('profiles', {}).items():
                        params = ModelParams(**profile_data.get('best_params', {}))
                        self.stock_profiles[ticker] = StockProfile(
                            ticker=ticker,
                            best_params=params,
                            best_win_rate=profile_data.get('best_win_rate', 0),
                            regime=profile_data.get('regime', 'UNKNOWN'),
                            volatility=profile_data.get('volatility', 0),
                            last_updated=profile_data.get('last_updated', ''),
                            backtest_history=profile_data.get('backtest_history', [])
                        )
            except Exception as e:
                print(f"Error loading profiles: {e}")

    def _save_profiles(self):
        """Save learned stock profiles to disk"""
        data = {
            'last_updated': datetime.now().isoformat(),
            'profiles': {}
        }
        for ticker, profile in self.stock_profiles.items():
            data['profiles'][ticker] = {
                'best_params': asdict(profile.best_params),
                'best_win_rate': profile.best_win_rate,
                'regime': profile.regime,
                'volatility': profile.volatility,
                'last_updated': profile.last_updated,
                'backtest_history': profile.backtest_history[-10:]  # Keep last 10
            }

        os.makedirs(os.path.dirname(self.db_path) or '.', exist_ok=True)
        with open(self.db_path, 'w') as f:
            json.dump(data, f, indent=2)

    def _generate_param_grid(self, regime: Regime) -> List[ModelParams]:
        """Generate parameter combinations to test based on regime"""

        # Base parameter ranges
        if regime == Regime.BULL:
            # In bull market: more aggressive buys, conservative sells
            rsi_oversold_range = [25, 30, 35]
            rsi_overbought_range = [80, 85, 90]
            rsi2_low_range = [5, 10, 15]
            rsi2_high_range = [90, 95, 98]
        elif regime == Regime.BEAR:
            # In bear market: conservative buys, aggressive sells
            rsi_oversold_range = [15, 20, 25]
            rsi_overbought_range = [65, 70, 75]
            rsi2_low_range = [3, 5, 8]
            rsi2_high_range = [85, 90, 95]
        elif regime == Regime.HIGH_VOL:
            # High volatility: tighter thresholds
            rsi_oversold_range = [20, 25]
            rsi_overbought_range = [75, 80]
            rsi2_low_range = [3, 5]
            rsi2_high_range = [95, 98]
        else:  # SIDEWAYS
            # Sideways: standard mean reversion
            rsi_oversold_range = [25, 30, 35]
            rsi_overbought_range = [65, 70, 75]
            rsi2_low_range = [5, 10]
            rsi2_high_range = [90, 95]

        params_list = []
        for rsi_os in rsi_oversold_range:
            for rsi_ob in rsi_overbought_range:
                for rsi2_low in rsi2_low_range:
                    for rsi2_high in rsi2_high_range:
                        params_list.append(ModelParams(
                            rsi_oversold=rsi_os,
                            rsi_overbought=rsi_ob,
                            rsi2_extreme_low=rsi2_low,
                            rsi2_extreme_high=rsi2_high,
                            regime_filter=True
                        ))

        return params_list

    def backtest_params(
        self,
        ticker: str,
        closes: List[float],
        volumes: List[float],
        params: ModelParams,
        forward_days: int = 7
    ) -> BacktestResult:
        """Backtest a specific parameter set"""

        model = AdaptiveModel(params)
        regime, regime_details = self.indicators.detect_regime(closes)

        buy_signals = 0
        buy_wins = 0
        sell_signals = 0
        sell_wins = 0
        returns = []

        min_lookback = max(params.sma_long, params.bb_period) + 20

        for i in range(min_lookback, len(closes) - forward_days):
            hist_closes = closes[:i+1]
            hist_volumes = volumes[:i+1] if volumes else []

            signal, confidence, _ = model.generate_signal(hist_closes, hist_volumes)

            if confidence < params.min_confidence:
                continue

            entry_price = closes[i]
            exit_price = closes[i + forward_days]
            ret = (exit_price - entry_price) / entry_price * 100

            if signal == "BUY":
                buy_signals += 1
                returns.append(ret)
                if ret > 0:
                    buy_wins += 1
            elif signal == "SELL":
                sell_signals += 1
                returns.append(-ret)  # For SELL, profit is negative return
                if ret < 0:
                    sell_wins += 1

        total_signals = buy_signals + sell_signals
        buy_win_rate = (buy_wins / buy_signals * 100) if buy_signals > 0 else 0
        sell_win_rate = (sell_wins / sell_signals * 100) if sell_signals > 0 else 0
        total_wins = buy_wins + sell_wins
        total_win_rate = (total_wins / total_signals * 100) if total_signals > 0 else 0

        avg_return = statistics.mean(returns) if returns else 0
        max_drawdown = min(returns) if returns else 0

        # Calculate Sharpe-like ratio
        if returns and len(returns) > 1:
            ret_std = statistics.stdev(returns)
            sharpe = (avg_return / ret_std) if ret_std > 0 else 0
        else:
            sharpe = 0

        return BacktestResult(
            ticker=ticker,
            params=params,
            total_signals=total_signals,
            buy_signals=buy_signals,
            buy_wins=buy_wins,
            buy_win_rate=buy_win_rate,
            sell_signals=sell_signals,
            sell_wins=sell_wins,
            sell_win_rate=sell_win_rate,
            total_win_rate=total_win_rate,
            avg_return=avg_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            regime=regime.value
        )

    def optimize_for_stock(
        self,
        ticker: str,
        closes: List[float],
        volumes: List[float] = None,
        min_signals: int = 5
    ) -> Tuple[ModelParams, float, BacktestResult]:
        """
        Find optimal parameters for a stock to achieve 75%+ win rate

        Returns:
            (best_params, best_win_rate, best_result)
        """
        if volumes is None:
            volumes = [0] * len(closes)

        # Detect regime
        regime, _ = self.indicators.detect_regime(closes)

        # Generate parameter grid
        param_grid = self._generate_param_grid(regime)

        best_params = None
        best_win_rate = 0
        best_result = None

        print(f"\nOptimizing {ticker} ({regime.value} regime)...")
        print(f"Testing {len(param_grid)} parameter combinations...")

        for params in param_grid:
            result = self.backtest_params(ticker, closes, volumes, params)

            # Require minimum signals for validity
            if result.total_signals < min_signals:
                continue

            # Prioritize BUY win rate (we mostly want to find good entries)
            effective_win_rate = result.buy_win_rate if result.buy_signals >= 3 else result.total_win_rate

            if effective_win_rate > best_win_rate:
                best_win_rate = effective_win_rate
                best_params = params
                best_result = result

        # Update stock profile
        if best_params and best_result:
            volatility = self.indicators.calc_volatility(closes)
            self.stock_profiles[ticker] = StockProfile(
                ticker=ticker,
                best_params=best_params,
                best_win_rate=best_win_rate,
                regime=regime.value,
                volatility=volatility,
                last_updated=datetime.now().isoformat(),
                backtest_history=[asdict(best_result)]
            )
            self._save_profiles()

        return best_params, best_win_rate, best_result

    def get_signal(
        self,
        ticker: str,
        closes: List[float],
        volumes: List[float] = None,
        auto_optimize: bool = True
    ) -> Tuple[str, float, str, float]:
        """
        Get trading signal using optimized parameters

        Returns:
            (signal, confidence, reason, model_win_rate)
        """
        # Check if we have optimized params
        if ticker in self.stock_profiles:
            profile = self.stock_profiles[ticker]
            model = AdaptiveModel(profile.best_params)
            signal, confidence, reason = model.generate_signal(closes, volumes)
            return signal, confidence, reason, profile.best_win_rate

        # Auto-optimize if requested
        if auto_optimize and len(closes) >= 80:
            best_params, win_rate, _ = self.optimize_for_stock(ticker, closes, volumes)
            if best_params:
                model = AdaptiveModel(best_params)
                signal, confidence, reason = model.generate_signal(closes, volumes)
                return signal, confidence, reason, win_rate

        # Fallback to default params
        model = AdaptiveModel()
        signal, confidence, reason = model.generate_signal(closes, volumes)
        return signal, confidence, reason, 50.0


class StockScanner:
    """
    Scans stocks to find those with 75%+ model win rate
    """

    MIN_WIN_RATE = 75.0

    def __init__(self):
        self.optimizer = ModelOptimizer()

    def scan_stocks(
        self,
        stock_data: Dict[str, Dict],
        min_win_rate: float = None
    ) -> List[Dict]:
        """
        Scan multiple stocks and return those meeting win rate threshold

        Args:
            stock_data: Dict of {ticker: {closes: [], volumes: []}}
            min_win_rate: Minimum win rate threshold (default 75%)

        Returns:
            List of qualifying stocks with details
        """
        if min_win_rate is None:
            min_win_rate = self.MIN_WIN_RATE

        results = []

        for ticker, data in stock_data.items():
            closes = data.get('closes', [])
            volumes = data.get('volumes', [])

            if len(closes) < 80:
                print(f"{ticker}: Insufficient data ({len(closes)} days)")
                continue

            # Optimize and get best win rate
            best_params, win_rate, backtest = self.optimizer.optimize_for_stock(
                ticker, closes, volumes
            )

            if win_rate >= min_win_rate and backtest:
                # Get current signal
                signal, confidence, reason, _ = self.optimizer.get_signal(
                    ticker, closes, volumes, auto_optimize=False
                )

                results.append({
                    'ticker': ticker,
                    'win_rate': win_rate,
                    'buy_win_rate': backtest.buy_win_rate,
                    'sell_win_rate': backtest.sell_win_rate,
                    'total_signals': backtest.total_signals,
                    'regime': backtest.regime,
                    'current_signal': signal,
                    'confidence': confidence,
                    'reason': reason,
                    'avg_return': backtest.avg_return,
                    'params': asdict(best_params)
                })

                print(f"✅ {ticker}: {win_rate:.1f}% win rate | Signal: {signal}")
            else:
                print(f"❌ {ticker}: {win_rate:.1f}% win rate (below {min_win_rate}% threshold)")

        # Sort by win rate
        results.sort(key=lambda x: x['win_rate'], reverse=True)

        return results


def run_full_scan():
    """Run full stock scan and optimization"""

    # Load available data
    data_path = 'data/historical_backtest.json'
    if not os.path.exists(data_path):
        print("No historical data found")
        return

    with open(data_path, 'r') as f:
        all_data = json.load(f)

    scanner = StockScanner()

    print("=" * 70)
    print("V27.0 MODEL OPTIMIZER - SCANNING FOR 75%+ WIN RATE STOCKS")
    print("=" * 70)

    # Convert data format
    stock_data = {}
    for ticker, data in all_data.items():
        if isinstance(data, dict) and 'closes' in data:
            stock_data[ticker] = data

    # Scan all stocks
    results = scanner.scan_stocks(stock_data, min_win_rate=75.0)

    # Print results
    print("\n" + "=" * 70)
    print("STOCKS MEETING 75% WIN RATE THRESHOLD")
    print("=" * 70)

    if results:
        print(f"\n{'Ticker':<8} {'Win Rate':<10} {'BUY WR':<10} {'Signal':<8} {'Regime':<12}")
        print("-" * 70)
        for r in results:
            print(f"{r['ticker']:<8} {r['win_rate']:.1f}%     {r['buy_win_rate']:.1f}%     {r['current_signal']:<8} {r['regime']:<12}")
    else:
        print("\nNo stocks found meeting 75% threshold with current data.")
        print("Consider:")
        print("1. Adding more historical data (365+ days)")
        print("2. Scanning more stocks")
        print("3. Adjusting the threshold")

    # Save results
    output_path = 'data/v27_scan_results.json'
    with open(output_path, 'w') as f:
        json.dump({
            'scan_date': datetime.now().isoformat(),
            'threshold': 75.0,
            'results': results
        }, f, indent=2)

    print(f"\nResults saved to {output_path}")

    return results


if __name__ == "__main__":
    run_full_scan()
