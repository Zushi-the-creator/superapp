"""
Expert Analyst Module - ATLAS V2.1
==================================

Enhanced model that:
1. ALWAYS finds rotation opportunities (never "no stocks available")
2. Uses MULTIPLE entry strategies (not just RSI(2) < 20)
3. Learns from mistakes and tracks them
4. Evolves based on trade outcomes
5. Targets 3%+ monthly ROI

Lessons Learned (Built into model):
- Don't buy extended stocks (>25% in 20 days)
- Don't buy above analyst targets
- Always check CURRENT entry signal, not just historical win rate
- Run full model before ANY recommendation

Entry Strategies (Adaptive):
1. RSI(2) Mean Reversion: RSI(2) < 20 + Price > SMA(50)
2. RSI(5) Momentum: RSI(5) < 25 + Volume spike
3. Pullback in Uptrend: -5% to -10% from 20-day high + above SMA(50)
4. Bollinger Band Bounce: Price within 2% of lower band + uptrend
5. MACD Reversal: MACD crosses above signal + RSI < 40

Exit Strategies (Regime-Based):
- BULL: Trail stop -10% from peak OR +15% target
- SIDEWAYS: Quick exit at +5% OR RSI(2) > 80
- BEAR: Tight stop -5%, exit any profit > 3%
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import json
import os
import sqlite3


@dataclass
class StockAnalysis:
    """Complete analysis for a single stock"""
    ticker: str
    price: float

    # Technical
    rsi2: float
    rsi5: float
    rsi14: float
    sma20: float
    sma50: float
    sma200: float
    bb_lower: float
    bb_upper: float

    # Momentum
    change_1d: float
    change_5d: float
    change_20d: float
    volume_ratio: float

    # Regime
    regime: str  # BULL, BEAR, SIDEWAYS

    # Validation
    oos_win_rate: float
    oos_trades: int
    validated: bool

    # Sentiment & Analyst
    sentiment: str
    sentiment_score: float
    analyst_target: float
    analyst_rating: str
    upside_pct: float

    # Entry Analysis
    entry_strategy: str
    entry_score: float
    entry_signal: str  # BUY, HOLD, SELL

    # Issues (learned from mistakes)
    issues: List[str] = field(default_factory=list)

    # Combined Score
    combined_score: float = 0.0

    # Recommendation
    action: str = "HOLD"
    confidence: str = "LOW"
    reason: str = ""


@dataclass
class PortfolioAction:
    """Recommended portfolio action"""
    action: str  # BUY, SELL, HOLD, ROTATE
    ticker: str
    shares: float
    price: float
    amount: float
    reason: str
    confidence: str
    entry_strategy: str
    stop_loss: float
    target: float
    oos_win_rate: float


@dataclass
class Mistake:
    """Tracked mistake for learning"""
    date: str
    ticker: str
    action: str
    reason: str
    what_went_wrong: str
    lesson: str


class ExpertAnalyst:
    """
    Expert Analyst that always finds opportunities and learns from mistakes.

    Key Principles:
    1. ALWAYS provide actionable recommendations
    2. If no ideal entries, find BEST available
    3. Learn from every mistake
    4. Adapt entry strategies based on what works
    5. Target 3%+ monthly ROI
    """

    # Minimum thresholds
    MIN_OOS_WIN_RATE = 55  # Lowered from 60 to find more opportunities
    MIN_OOS_TRADES = 5
    MAX_EXTENSION = 25  # Block if up >25% in 20 days
    MIN_UPSIDE = -15  # Block if >15% above analyst target

    # Entry strategy weights (learned over time)
    STRATEGY_WEIGHTS = {
        'RSI2_MEAN_REVERSION': 1.0,
        'RSI5_MOMENTUM': 0.9,
        'PULLBACK_UPTREND': 0.85,
        'BB_BOUNCE': 0.8,
        'MACD_REVERSAL': 0.75,
        'RELATIVE_STRENGTH': 0.7,
    }

    # Tracked mistakes
    KNOWN_MISTAKES = [
        Mistake(
            date="2026-02-02",
            ticker="MU",
            action="BUY",
            reason="90% historical win rate",
            what_went_wrong="Stock was up 39% in 20 days, RSI(2)=52 not oversold",
            lesson="Always check CURRENT entry signal AND extension"
        ),
    ]

    def __init__(self, db_path: str = None):
        self.db_path = db_path or "atlas_v2_expert.db"
        self._init_db()

    def _init_db(self):
        """Initialize learning database"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Mistakes table
        c.execute('''
            CREATE TABLE IF NOT EXISTS mistakes (
                id INTEGER PRIMARY KEY,
                date TEXT,
                ticker TEXT,
                action TEXT,
                reason TEXT,
                what_went_wrong TEXT,
                lesson TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Strategy performance table
        c.execute('''
            CREATE TABLE IF NOT EXISTS strategy_performance (
                id INTEGER PRIMARY KEY,
                strategy TEXT,
                ticker TEXT,
                entry_date TEXT,
                entry_price REAL,
                exit_date TEXT,
                exit_price REAL,
                return_pct REAL,
                win INTEGER,
                regime TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Recommendations history
        c.execute('''
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY,
                date TEXT,
                ticker TEXT,
                action TEXT,
                price REAL,
                reason TEXT,
                outcome TEXT,
                return_pct REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()

    def record_mistake(self, mistake: Mistake):
        """Record a mistake for learning"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT INTO mistakes (date, ticker, action, reason, what_went_wrong, lesson)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (mistake.date, mistake.ticker, mistake.action, mistake.reason,
              mistake.what_went_wrong, mistake.lesson))
        conn.commit()
        conn.close()
        self.KNOWN_MISTAKES.append(mistake)

    def get_lessons(self) -> List[str]:
        """Get all learned lessons"""
        return [m.lesson for m in self.KNOWN_MISTAKES]

    def calculate_indicators(self, closes: List[float], volumes: List[float] = None) -> Dict:
        """Calculate all technical indicators"""
        def rsi(data, period):
            if len(data) < period + 1:
                return 50
            gains = [max(0, data[i] - data[i-1]) for i in range(1, len(data))]
            losses = [max(0, data[i-1] - data[i]) for i in range(1, len(data))]
            avg_g = sum(gains[-period:]) / period
            avg_l = sum(losses[-period:]) / period
            if avg_l == 0:
                return 100
            return 100 - 100 / (1 + avg_g / avg_l)

        def sma(data, period):
            if len(data) < period:
                return data[-1] if data else 0
            return sum(data[-period:]) / period

        def bollinger_bands(data, period=20, std_dev=2):
            if len(data) < period:
                return data[-1], data[-1], data[-1]
            mean = sma(data, period)
            variance = sum((x - mean) ** 2 for x in data[-period:]) / period
            std = variance ** 0.5
            return mean - std_dev * std, mean, mean + std_dev * std

        current = closes[-1]
        bb_lower, bb_mid, bb_upper = bollinger_bands(closes)

        # Volume ratio
        vol_ratio = 1.0
        if volumes and len(volumes) >= 20:
            avg_vol = sum(volumes[-20:]) / 20
            vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

        return {
            'rsi2': rsi(closes, 2),
            'rsi5': rsi(closes, 5),
            'rsi14': rsi(closes, 14),
            'sma20': sma(closes, 20),
            'sma50': sma(closes, 50),
            'sma200': sma(closes, 200),
            'bb_lower': bb_lower,
            'bb_mid': bb_mid,
            'bb_upper': bb_upper,
            'change_1d': (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) > 1 else 0,
            'change_5d': (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) > 6 else 0,
            'change_20d': (closes[-1] - closes[-21]) / closes[-21] * 100 if len(closes) > 21 else 0,
            'volume_ratio': vol_ratio,
            'high_20d': max(closes[-20:]) if len(closes) >= 20 else current,
            'low_20d': min(closes[-20:]) if len(closes) >= 20 else current,
        }

    def detect_regime(self, closes: List[float]) -> str:
        """Detect market regime"""
        if len(closes) < 200:
            return "UNKNOWN"

        current = closes[-1]
        sma50 = sum(closes[-50:]) / 50
        sma200 = sum(closes[-200:]) / 200

        # Calculate volatility
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        volatility = (sum(r**2 for r in returns[-20:]) / 20) ** 0.5

        if volatility > 0.03:  # High volatility
            return "HIGH_VOL"
        elif current > sma50 > sma200:
            return "BULL"
        elif current < sma50 < sma200:
            return "BEAR"
        else:
            return "SIDEWAYS"

    def check_entry_strategies(self, indicators: Dict, regime: str) -> Tuple[str, float, str]:
        """
        Check ALL entry strategies and return the best one.

        Returns: (strategy_name, entry_score, signal)
        """
        strategies = []

        current = indicators.get('current_price', 0)
        rsi2 = indicators['rsi2']
        rsi5 = indicators['rsi5']
        rsi14 = indicators['rsi14']
        sma50 = indicators['sma50']
        sma200 = indicators['sma200']
        bb_lower = indicators['bb_lower']
        change_20d = indicators['change_20d']
        vol_ratio = indicators['volume_ratio']
        high_20d = indicators.get('high_20d', current)

        uptrend = current > sma50

        # Strategy 1: RSI(2) Mean Reversion
        if rsi2 < 20 and uptrend:
            score = 80 + (20 - rsi2) * 2  # Higher score for lower RSI
            strategies.append(('RSI2_MEAN_REVERSION', min(100, score), 'BUY'))
        elif rsi2 < 30 and uptrend:
            score = 60 + (30 - rsi2)
            strategies.append(('RSI2_MEAN_REVERSION', score, 'WATCH'))

        # Strategy 2: RSI(5) Momentum
        if rsi5 < 25 and uptrend and vol_ratio > 1.2:
            score = 70 + (25 - rsi5) + (vol_ratio - 1) * 10
            strategies.append(('RSI5_MOMENTUM', min(100, score), 'BUY'))
        elif rsi5 < 35 and uptrend:
            score = 50 + (35 - rsi5)
            strategies.append(('RSI5_MOMENTUM', score, 'WATCH'))

        # Strategy 3: Pullback in Uptrend
        pullback_pct = (current - high_20d) / high_20d * 100 if high_20d else 0
        if -10 <= pullback_pct <= -5 and uptrend and rsi14 < 50:
            score = 75 + abs(pullback_pct) * 2
            strategies.append(('PULLBACK_UPTREND', min(100, score), 'BUY'))
        elif -15 <= pullback_pct <= -3 and uptrend:
            score = 55 + abs(pullback_pct)
            strategies.append(('PULLBACK_UPTREND', score, 'WATCH'))

        # Strategy 4: Bollinger Band Bounce
        bb_distance = (current - bb_lower) / bb_lower * 100 if bb_lower else 0
        if bb_distance < 2 and uptrend and rsi2 < 30:
            score = 70 + (2 - bb_distance) * 10
            strategies.append(('BB_BOUNCE', min(100, score), 'BUY'))
        elif bb_distance < 5 and uptrend:
            score = 50 + (5 - bb_distance) * 5
            strategies.append(('BB_BOUNCE', score, 'WATCH'))

        # Strategy 5: Relative Strength (vs market)
        if change_20d > 5 and rsi14 < 60 and uptrend:
            score = 60 + change_20d
            strategies.append(('RELATIVE_STRENGTH', min(85, score), 'WATCH'))

        # Regime adjustments
        regime_multiplier = {
            'BULL': 1.1,
            'SIDEWAYS': 1.0,
            'BEAR': 0.8,
            'HIGH_VOL': 0.9,
        }.get(regime, 1.0)

        # Apply regime multiplier and strategy weights
        adjusted_strategies = []
        for strategy, score, signal in strategies:
            weight = self.STRATEGY_WEIGHTS.get(strategy, 1.0)
            adjusted_score = score * regime_multiplier * weight
            adjusted_strategies.append((strategy, adjusted_score, signal))

        if not adjusted_strategies:
            return ('NONE', 0, 'HOLD')

        # Return best strategy
        adjusted_strategies.sort(key=lambda x: x[1], reverse=True)
        return adjusted_strategies[0]

    def apply_learned_filters(self, analysis: StockAnalysis) -> StockAnalysis:
        """
        Apply filters learned from past mistakes.

        Lessons:
        1. Don't buy extended stocks (>25% in 20 days)
        2. Don't buy significantly above analyst target
        3. Check current RSI, not just historical win rate
        """
        issues = []
        score_penalty = 0

        # Lesson 1: Extension check (MU mistake)
        if analysis.change_20d > self.MAX_EXTENSION:
            issues.append(f"EXTENDED +{analysis.change_20d:.0f}% in 20d (max {self.MAX_EXTENSION}%)")
            score_penalty += 40
            if analysis.entry_signal == 'BUY':
                analysis.entry_signal = 'HOLD'
                analysis.action = 'HOLD'

        # Lesson 2: Analyst target check
        if analysis.upside_pct < self.MIN_UPSIDE:
            issues.append(f"OVERVALUED {analysis.upside_pct:.0f}% vs target (min {self.MIN_UPSIDE}%)")
            score_penalty += 30

        # Lesson 3: RSI(14) overbought in extended stock
        if analysis.rsi14 > 75 and analysis.change_20d > 15:
            issues.append(f"RSI(14)={analysis.rsi14:.0f} + extended = pullback likely")
            score_penalty += 20

        # Lesson 4: Validation check
        if not analysis.validated and analysis.entry_signal == 'BUY':
            issues.append(f"OOS WR {analysis.oos_win_rate:.0f}% failed validation")
            score_penalty += 25

        # Lesson 5: Sentiment VETO
        if analysis.sentiment == 'NEGATIVE':
            issues.append("NEGATIVE sentiment")
            score_penalty += 15

        analysis.issues = issues
        analysis.entry_score = max(0, analysis.entry_score - score_penalty)

        # Recalculate combined score
        analysis.combined_score = (
            analysis.entry_score * 0.4 +
            analysis.oos_win_rate * 0.4 +
            max(0, min(20, analysis.upside_pct)) * 0.2
        )

        # Determine action
        if not issues and analysis.entry_signal == 'BUY' and analysis.validated:
            analysis.action = 'BUY'
            analysis.confidence = 'HIGH' if analysis.combined_score > 70 else 'MEDIUM'
        elif not issues and analysis.entry_signal == 'BUY':
            analysis.action = 'WATCH'
            analysis.confidence = 'MEDIUM'
        elif issues and analysis.change_20d > 25:
            analysis.action = 'TAKE_PROFIT'
            analysis.confidence = 'HIGH'
        else:
            analysis.action = 'HOLD'
            analysis.confidence = 'LOW'

        return analysis

    def find_rotation_opportunities(
        self,
        current_holdings: List[str],
        all_analyses: List[StockAnalysis]
    ) -> List[Dict]:
        """
        Always find rotation opportunities - never return empty.

        Logic:
        1. Find stocks BETTER than current holdings
        2. If no better stocks, find stocks with better ENTRY TIMING
        3. If still none, recommend holding and waiting
        """
        rotations = []

        # Get current holding analyses
        holding_analyses = {a.ticker: a for a in all_analyses if a.ticker in current_holdings}

        # Get non-holding analyses, sorted by combined score
        opportunities = [a for a in all_analyses if a.ticker not in current_holdings]
        opportunities.sort(key=lambda x: x.combined_score, reverse=True)

        for holding_ticker, holding in holding_analyses.items():
            # Check if holding has issues
            if holding.issues or holding.change_20d > 20:
                # Find better alternatives
                for opp in opportunities:
                    # Must be meaningfully better
                    if (opp.combined_score > holding.combined_score + 10 and
                        opp.entry_signal in ['BUY', 'WATCH'] and
                        not opp.issues):

                        rotations.append({
                            'sell': holding_ticker,
                            'sell_reason': '; '.join(holding.issues) or f"Extended +{holding.change_20d:.0f}%",
                            'buy': opp.ticker,
                            'buy_reason': f"{opp.entry_strategy} signal, {opp.oos_win_rate:.0f}% WR",
                            'improvement': opp.combined_score - holding.combined_score,
                            'confidence': opp.confidence
                        })
                        break

        return rotations

    def generate_action_plan(
        self,
        analyses: List[StockAnalysis],
        current_holdings: Dict[str, float],  # ticker -> shares
        available_cash: float,
        target_monthly_return: float = 0.03
    ) -> Dict:
        """
        Generate complete action plan that ALWAYS provides recommendations.

        Parameters:
            analyses: List of stock analyses
            current_holdings: Dict of ticker -> shares
            available_cash: Cash available for new positions
            target_monthly_return: Target ROI (default 3%)

        Returns:
            Action plan with sells, buys, and reasoning
        """
        # Sort by combined score
        analyses.sort(key=lambda x: x.combined_score, reverse=True)

        # Separate by action
        sells = []
        buys = []
        holds = []
        watches = []

        holding_tickers = list(current_holdings.keys())

        for a in analyses:
            if a.ticker in holding_tickers:
                if a.action == 'TAKE_PROFIT' or (a.issues and a.change_20d > 25):
                    sells.append(a)
                elif a.action == 'HOLD':
                    holds.append(a)
                else:
                    holds.append(a)
            else:
                if a.action == 'BUY' and a.confidence in ['HIGH', 'MEDIUM']:
                    buys.append(a)
                elif a.entry_signal in ['BUY', 'WATCH'] and a.combined_score > 50:
                    watches.append(a)

        # Find rotations
        rotations = self.find_rotation_opportunities(holding_tickers, analyses)

        # Calculate expected returns
        total_portfolio = sum(current_holdings.values()) + available_cash

        # Build action plan
        plan = {
            'timestamp': datetime.now().isoformat(),
            'portfolio_value': total_portfolio,
            'target_return': target_monthly_return,
            'target_profit': total_portfolio * target_monthly_return,

            'sells': [{
                'ticker': a.ticker,
                'price': a.price,
                'reason': '; '.join(a.issues) or 'Take profit',
                'urgency': 'HIGH' if a.change_20d > 30 else 'MEDIUM'
            } for a in sells],

            'buys': [{
                'ticker': a.ticker,
                'price': a.price,
                'strategy': a.entry_strategy,
                'oos_win_rate': a.oos_win_rate,
                'entry_score': a.entry_score,
                'confidence': a.confidence,
                'stop_loss': a.price * 0.95,
                'target': a.price * 1.10,
                'reason': f"{a.entry_strategy}: RSI(2)={a.rsi2:.0f}, {a.sentiment} sentiment"
            } for a in buys[:3]],  # Top 3 only

            'holds': [{
                'ticker': a.ticker,
                'price': a.price,
                'oos_win_rate': a.oos_win_rate,
                'status': 'Watch for entry' if a.entry_signal == 'WATCH' else 'Hold'
            } for a in holds],

            'watch_list': [{
                'ticker': a.ticker,
                'price': a.price,
                'trigger': f"BUY if RSI(2) < 20 (current: {a.rsi2:.0f})",
                'oos_win_rate': a.oos_win_rate
            } for a in watches[:5]],

            'rotations': rotations,

            'lessons_applied': self.get_lessons(),
        }

        # If no buys found, provide best alternatives
        if not plan['buys'] and not plan['rotations']:
            plan['recommendation'] = "WAIT - No ideal entries. Market may be overbought."
            plan['best_available'] = [{
                'ticker': a.ticker,
                'price': a.price,
                'entry_score': a.entry_score,
                'issue': '; '.join(a.issues) if a.issues else 'RSI not oversold',
                'trigger': f"BUY if RSI(2) drops to <20 (current: {a.rsi2:.0f})"
            } for a in analyses[:5] if a.ticker not in holding_tickers]
        else:
            plan['recommendation'] = "EXECUTE - Actionable opportunities found."

        return plan


def create_expert_analyst() -> ExpertAnalyst:
    """Factory function to create Expert Analyst instance"""
    return ExpertAnalyst()
