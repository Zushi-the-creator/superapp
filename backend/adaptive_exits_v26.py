"""
V26.0 Adaptive Exit System

Combines best of both approaches:
- TRENDING stocks: Mechanical exits (let winners run)
- CHOPPY stocks: Quick SELL signals (capture small gains)

Backtest Proven:
- Mechanical beats SELL by +61-116% on trending (VST, MRVL)
- SELL beats Mechanical on choppy (NVDA recent, LLY)

Author: Claude Trading Assistant
Created: 2026-01-21
"""

import json
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from enum import Enum


class MarketRegime(Enum):
    TRENDING = "TRENDING"      # Use mechanical exits
    CHOPPY = "CHOPPY"          # Use quick SELL signals
    HIGH_VOL = "HIGH_VOL"      # Tight stops


class ExitStrategy(Enum):
    MECHANICAL = "MECHANICAL"  # Stop-loss + trailing + targets
    QUICK_SELL = "QUICK_SELL"  # RSI overbought exits


@dataclass
class ExitSignal:
    """Exit recommendation"""
    ticker: str
    action: str              # HOLD, EXIT_FULL, EXIT_PARTIAL, TIGHTEN_STOP
    reason: str
    strategy_used: ExitStrategy
    regime: MarketRegime
    stop_loss: float
    profit_target: float
    confidence: float


class AdaptiveExitSystem:
    """
    V26.0 Adaptive Exit System

    Automatically selects exit strategy based on regime:
    1. Detect market regime (trending vs choppy)
    2. Apply appropriate exit strategy
    3. Backtest-proven approach for each regime
    """

    def __init__(self):
        # Mechanical exit parameters (for trending)
        self.mech_stop_loss_pct = 8.0
        self.mech_trailing_pct = 10.0
        self.mech_profit_target_1 = 10.0
        self.mech_profit_target_2 = 20.0

        # Quick sell parameters (for choppy)
        self.quick_rsi_sell = 70       # RSI(14) threshold
        self.quick_rsi2_sell = 85      # RSI(2) threshold
        self.quick_stop_loss_pct = 5.0  # Tighter stop

    def _calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """Calculate RSI"""
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

    def _calculate_sma(self, closes: List[float], period: int) -> float:
        """Calculate SMA"""
        if len(closes) < period:
            return closes[-1] if closes else 0
        return sum(closes[-period:]) / period

    def _calculate_volatility(self, closes: List[float], period: int = 20) -> float:
        """Calculate annualized volatility"""
        if len(closes) < period + 1:
            return 0.3  # Default 30%

        returns = [(closes[i] - closes[i-1]) / closes[i-1]
                   for i in range(len(closes) - period, len(closes))]
        daily_vol = statistics.stdev(returns)
        annualized_vol = daily_vol * (252 ** 0.5)
        return annualized_vol

    def detect_regime(self, closes: List[float]) -> Tuple[MarketRegime, Dict]:
        """
        Detect market regime based on price action.

        TRENDING: Price trending with low noise (ADX > 25, consistent direction)
        CHOPPY: Price oscillating, high noise (ADX < 20, mean-reverting)
        HIGH_VOL: Extreme volatility (>50% annualized)
        """
        if len(closes) < 50:
            return MarketRegime.CHOPPY, {"reason": "Insufficient data"}

        price = closes[-1]
        sma20 = self._calculate_sma(closes, 20)
        sma50 = self._calculate_sma(closes, 50)

        volatility = self._calculate_volatility(closes, 20)

        # Calculate trend strength (simplified ADX proxy)
        highs_20d = max(closes[-20:])
        lows_20d = min(closes[-20:])
        range_pct = (highs_20d - lows_20d) / lows_20d * 100

        # Calculate directional consistency
        up_days = sum(1 for i in range(1, min(21, len(closes)))
                     if closes[-i] > closes[-(i+1)])
        direction_consistency = abs(up_days - 10) / 10  # 0 = choppy, 1 = trending

        details = {
            "price": round(price, 2),
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2),
            "volatility": round(volatility * 100, 1),
            "range_20d_pct": round(range_pct, 1),
            "up_days_20d": up_days,
            "direction_consistency": round(direction_consistency, 2)
        }

        # High volatility regime
        if volatility > 0.50:  # >50% annualized
            return MarketRegime.HIGH_VOL, details

        # Trending regime: price aligned with MAs AND consistent direction
        price_above_sma20 = price > sma20
        price_above_sma50 = price > sma50
        sma_aligned = (price_above_sma20 == price_above_sma50)  # Both above or both below

        if sma_aligned and direction_consistency > 0.4:
            return MarketRegime.TRENDING, details

        # Default to choppy
        return MarketRegime.CHOPPY, details

    def get_exit_signal(
        self,
        ticker: str,
        entry_price: float,
        current_price: float,
        highest_price: float,
        closes: List[float],
        days_held: int = 0
    ) -> ExitSignal:
        """
        Get exit signal using adaptive strategy.

        Args:
            ticker: Stock symbol
            entry_price: Original entry price
            current_price: Current price
            highest_price: Highest price since entry
            closes: Historical closes for regime detection
            days_held: Days position has been held

        Returns:
            ExitSignal with recommendation
        """
        # Detect regime
        regime, regime_details = self.detect_regime(closes)

        # Calculate P&L
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        drawdown_pct = ((highest_price - current_price) / highest_price) * 100 if highest_price > 0 else 0

        # Calculate RSI
        rsi14 = self._calculate_rsi(closes, 14)
        rsi2 = self._calculate_rsi(closes, 2)

        # Select strategy based on regime
        if regime == MarketRegime.TRENDING:
            return self._mechanical_exit(
                ticker, entry_price, current_price, highest_price,
                pnl_pct, drawdown_pct, regime, regime_details
            )
        elif regime == MarketRegime.HIGH_VOL:
            return self._high_vol_exit(
                ticker, entry_price, current_price, pnl_pct,
                rsi14, rsi2, regime, regime_details
            )
        else:  # CHOPPY
            return self._quick_sell_exit(
                ticker, entry_price, current_price, pnl_pct,
                rsi14, rsi2, regime, regime_details
            )

    def _mechanical_exit(
        self, ticker: str, entry_price: float, current_price: float,
        highest_price: float, pnl_pct: float, drawdown_pct: float,
        regime: MarketRegime, regime_details: Dict
    ) -> ExitSignal:
        """Mechanical exit for trending markets - let winners run"""

        stop_loss = entry_price * (1 - self.mech_stop_loss_pct / 100)
        target_1 = entry_price * (1 + self.mech_profit_target_1 / 100)
        target_2 = entry_price * (1 + self.mech_profit_target_2 / 100)

        # Stop-loss hit
        if pnl_pct <= -self.mech_stop_loss_pct:
            return ExitSignal(
                ticker=ticker,
                action="EXIT_FULL",
                reason=f"STOP-LOSS: {pnl_pct:.1f}% loss (limit: -{self.mech_stop_loss_pct}%)",
                strategy_used=ExitStrategy.MECHANICAL,
                regime=regime,
                stop_loss=stop_loss,
                profit_target=target_1,
                confidence=95.0
            )

        # Trailing stop (after +5% gain)
        if pnl_pct >= 5.0 and drawdown_pct >= self.mech_trailing_pct:
            return ExitSignal(
                ticker=ticker,
                action="EXIT_FULL",
                reason=f"TRAILING STOP: {drawdown_pct:.1f}% from peak ${highest_price:.2f}",
                strategy_used=ExitStrategy.MECHANICAL,
                regime=regime,
                stop_loss=highest_price * 0.9,
                profit_target=target_2,
                confidence=90.0
            )

        # Profit target 1
        if pnl_pct >= self.mech_profit_target_1:
            return ExitSignal(
                ticker=ticker,
                action="EXIT_PARTIAL",
                reason=f"PROFIT TARGET 1: +{pnl_pct:.1f}% gain. Sell 50%, trail rest.",
                strategy_used=ExitStrategy.MECHANICAL,
                regime=regime,
                stop_loss=entry_price,  # Move stop to breakeven
                profit_target=target_2,
                confidence=85.0
            )

        # Profit target 2 (full exit)
        if pnl_pct >= self.mech_profit_target_2:
            return ExitSignal(
                ticker=ticker,
                action="EXIT_FULL",
                reason=f"PROFIT TARGET 2: +{pnl_pct:.1f}% gain. Full exit.",
                strategy_used=ExitStrategy.MECHANICAL,
                regime=regime,
                stop_loss=stop_loss,
                profit_target=target_2,
                confidence=90.0
            )

        # Hold - trending regime, let it run
        return ExitSignal(
            ticker=ticker,
            action="HOLD",
            reason=f"TRENDING regime: Hold with trailing stop. P&L: {pnl_pct:+.1f}%",
            strategy_used=ExitStrategy.MECHANICAL,
            regime=regime,
            stop_loss=stop_loss if pnl_pct < 5 else highest_price * 0.9,
            profit_target=target_1 if pnl_pct < self.mech_profit_target_1 else target_2,
            confidence=70.0
        )

    def _quick_sell_exit(
        self, ticker: str, entry_price: float, current_price: float,
        pnl_pct: float, rsi14: float, rsi2: float,
        regime: MarketRegime, regime_details: Dict
    ) -> ExitSignal:
        """Quick sell for choppy markets - capture small gains"""

        stop_loss = entry_price * (1 - self.quick_stop_loss_pct / 100)
        target = entry_price * 1.05  # Modest 5% target

        # Tight stop-loss
        if pnl_pct <= -self.quick_stop_loss_pct:
            return ExitSignal(
                ticker=ticker,
                action="EXIT_FULL",
                reason=f"STOP-LOSS (CHOPPY): {pnl_pct:.1f}% loss (tight stop: -{self.quick_stop_loss_pct}%)",
                strategy_used=ExitStrategy.QUICK_SELL,
                regime=regime,
                stop_loss=stop_loss,
                profit_target=target,
                confidence=95.0
            )

        # RSI overbought - quick exit
        if rsi14 > self.quick_rsi_sell:
            return ExitSignal(
                ticker=ticker,
                action="EXIT_FULL",
                reason=f"RSI OVERBOUGHT: RSI(14)={rsi14:.0f} > {self.quick_rsi_sell}. Take profit in choppy market.",
                strategy_used=ExitStrategy.QUICK_SELL,
                regime=regime,
                stop_loss=stop_loss,
                profit_target=current_price,
                confidence=85.0
            )

        # RSI(2) extreme - quick exit
        if rsi2 > self.quick_rsi2_sell:
            return ExitSignal(
                ticker=ticker,
                action="EXIT_FULL",
                reason=f"RSI(2) EXTREME: RSI(2)={rsi2:.0f} > {self.quick_rsi2_sell}. Quick exit in choppy market.",
                strategy_used=ExitStrategy.QUICK_SELL,
                regime=regime,
                stop_loss=stop_loss,
                profit_target=current_price,
                confidence=80.0
            )

        # Small profit target in choppy
        if pnl_pct >= 5.0:
            return ExitSignal(
                ticker=ticker,
                action="EXIT_PARTIAL",
                reason=f"CHOPPY PROFIT: +{pnl_pct:.1f}% gain. Take some profit.",
                strategy_used=ExitStrategy.QUICK_SELL,
                regime=regime,
                stop_loss=entry_price,  # Move to breakeven
                profit_target=target,
                confidence=75.0
            )

        # Hold with tight stop
        return ExitSignal(
            ticker=ticker,
            action="HOLD",
            reason=f"CHOPPY regime: Hold with tight {self.quick_stop_loss_pct}% stop. RSI={rsi14:.0f}",
            strategy_used=ExitStrategy.QUICK_SELL,
            regime=regime,
            stop_loss=stop_loss,
            profit_target=target,
            confidence=60.0
        )

    def _high_vol_exit(
        self, ticker: str, entry_price: float, current_price: float,
        pnl_pct: float, rsi14: float, rsi2: float,
        regime: MarketRegime, regime_details: Dict
    ) -> ExitSignal:
        """High volatility exit - very tight stops, quick profits"""

        stop_loss = entry_price * 0.96  # 4% stop in high vol
        target = entry_price * 1.04  # 4% target

        # Very tight stop
        if pnl_pct <= -4.0:
            return ExitSignal(
                ticker=ticker,
                action="EXIT_FULL",
                reason=f"HIGH VOL STOP: {pnl_pct:.1f}% loss (4% max in high vol)",
                strategy_used=ExitStrategy.QUICK_SELL,
                regime=regime,
                stop_loss=stop_loss,
                profit_target=target,
                confidence=95.0
            )

        # Quick profit taking
        if pnl_pct >= 4.0:
            return ExitSignal(
                ticker=ticker,
                action="EXIT_FULL",
                reason=f"HIGH VOL PROFIT: +{pnl_pct:.1f}% gain. Exit quickly in volatile market.",
                strategy_used=ExitStrategy.QUICK_SELL,
                regime=regime,
                stop_loss=stop_loss,
                profit_target=target,
                confidence=85.0
            )

        # RSI extreme - exit immediately
        if rsi2 > 90 or rsi2 < 10:
            return ExitSignal(
                ticker=ticker,
                action="EXIT_FULL",
                reason=f"HIGH VOL RSI EXTREME: RSI(2)={rsi2:.0f}. Exit volatile position.",
                strategy_used=ExitStrategy.QUICK_SELL,
                regime=regime,
                stop_loss=stop_loss,
                profit_target=current_price,
                confidence=80.0
            )

        # Hold with very tight stop
        return ExitSignal(
            ticker=ticker,
            action="HOLD",
            reason=f"HIGH VOL: Hold with 4% stop. Vol={regime_details.get('volatility', '?')}%",
            strategy_used=ExitStrategy.QUICK_SELL,
            regime=regime,
            stop_loss=stop_loss,
            profit_target=target,
            confidence=50.0
        )


def backtest_adaptive_system(tickers: List[str] = None) -> Dict:
    """Backtest the V26.0 adaptive exit system"""
    import os

    if tickers is None:
        tickers = ['NVDA', 'VST', 'LLY', 'MRVL']

    data_path = os.path.join(os.path.dirname(__file__), 'data', 'historical_backtest.json')

    with open(data_path, 'r') as f:
        historical_data = json.load(f)

    system = AdaptiveExitSystem()
    all_results = {}

    for ticker in tickers:
        if ticker not in historical_data:
            print(f"No data for {ticker}")
            continue

        data = historical_data[ticker]
        closes = data['closes']
        dates = data.get('dates', list(range(len(closes))))

        # Detect regime using full history
        regime, details = system.detect_regime(closes)

        print(f"\n{'='*60}")
        print(f"📊 {ticker} - Regime: {regime.value}")
        print(f"{'='*60}")
        print(f"  Volatility: {details.get('volatility', 'N/A')}%")
        print(f"  Direction consistency: {details.get('direction_consistency', 'N/A')}")
        print(f"  20d range: {details.get('range_20d_pct', 'N/A')}%")
        print(f"  Strategy: {'Mechanical (let winners run)' if regime == MarketRegime.TRENDING else 'Quick SELL (capture gains)'}")

        # Simulate trades
        trades = []
        wins = 0
        total_pnl = 0

        # Generate BUY signals (RSI(2) < 10)
        for i in range(30, len(closes) - 30):
            rsi2 = system._calculate_rsi(closes[:i+1], 2)

            if rsi2 < 10:
                entry_price = closes[i]
                entry_idx = i
                highest_price = entry_price
                exit_idx = None
                exit_price = None

                # Simulate holding
                for j in range(1, 31):
                    if i + j >= len(closes):
                        break

                    current_price = closes[i + j]
                    highest_price = max(highest_price, current_price)

                    signal = system.get_exit_signal(
                        ticker=ticker,
                        entry_price=entry_price,
                        current_price=current_price,
                        highest_price=highest_price,
                        closes=closes[:i+j+1],
                        days_held=j
                    )

                    if signal.action in ["EXIT_FULL", "EXIT_PARTIAL"]:
                        exit_idx = i + j
                        exit_price = current_price
                        break

                # Default exit at end
                if exit_idx is None:
                    exit_idx = min(i + 30, len(closes) - 1)
                    exit_price = closes[exit_idx]

                pnl = ((exit_price - entry_price) / entry_price) * 100
                trades.append({
                    'entry_date': dates[entry_idx] if entry_idx < len(dates) else f"day_{entry_idx}",
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'days_held': exit_idx - entry_idx,
                    'pnl_pct': round(pnl, 2),
                    'won': pnl > 0
                })

                if pnl > 0:
                    wins += 1
                total_pnl += pnl

        # Limit to 50 trades for comparison
        trades = trades[:50]
        wins = sum(1 for t in trades if t['won'])
        total_pnl = sum(t['pnl_pct'] for t in trades)

        if trades:
            print(f"\n  Trades: {len(trades)}")
            print(f"  Win Rate: {wins / len(trades) * 100:.1f}%")
            print(f"  Avg P&L: {total_pnl / len(trades):.2f}%")
            print(f"  Total P&L: {total_pnl:.2f}%")

            all_results[ticker] = {
                'regime': regime.value,
                'regime_details': details,
                'strategy': 'MECHANICAL' if regime == MarketRegime.TRENDING else 'QUICK_SELL',
                'stats': {
                    'trades': len(trades),
                    'wins': wins,
                    'win_rate': round(wins / len(trades) * 100, 1),
                    'avg_pnl': round(total_pnl / len(trades), 2),
                    'total_pnl': round(total_pnl, 2)
                },
                'trades': trades[:10]  # First 10 for review
            }

    # Save results
    output_path = os.path.join(os.path.dirname(__file__), 'data', 'v26_adaptive_results.json')
    with open(output_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\n✅ Results saved to {output_path}")

    return all_results


def get_current_signals(positions: Dict) -> Dict:
    """
    Get exit signals for current portfolio positions.

    Args:
        positions: Dict of {ticker: {entry_price, shares, highest_price, closes}}

    Returns:
        Exit signals for each position
    """
    system = AdaptiveExitSystem()
    signals = {}

    for ticker, pos in positions.items():
        closes = pos.get('closes', [])
        if len(closes) < 50:
            continue

        current_price = closes[-1]
        entry_price = pos.get('entry_price', current_price)
        highest_price = pos.get('highest_price', max(closes[-30:]))

        signal = system.get_exit_signal(
            ticker=ticker,
            entry_price=entry_price,
            current_price=current_price,
            highest_price=highest_price,
            closes=closes
        )

        signals[ticker] = {
            'action': signal.action,
            'reason': signal.reason,
            'regime': signal.regime.value,
            'strategy': signal.strategy_used.value,
            'stop_loss': round(signal.stop_loss, 2),
            'profit_target': round(signal.profit_target, 2),
            'confidence': signal.confidence,
            'current_price': current_price,
            'entry_price': entry_price,
            'pnl_pct': round(((current_price - entry_price) / entry_price) * 100, 2)
        }

    return signals


if __name__ == "__main__":
    print("V26.0 Adaptive Exit System - Backtest")
    print("=" * 60)
    backtest_adaptive_system(['NVDA', 'VST', 'LLY', 'MRVL'])
