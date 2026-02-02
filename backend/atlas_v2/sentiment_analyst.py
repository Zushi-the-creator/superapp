"""
Sentiment & Analyst Integration Module
======================================

Integrates:
- News Sentiment (10% weight) - VETO function
- Analyst Targets (5% weight) - EXIT price targets

Based on V26.0 Evidence-Based Weights:
- Technical: 85% (entry signals)
- Sentiment: 10% (VETO only - block if negative)
- Analyst: 5% (exit targets only)

Research shows:
- Pure technical achieved 66% win rate
- Adding sentiment/analyst when overweighted REDUCED accuracy
- Sentiment best used as VETO, not positive signal
- Analyst targets best for EXIT, not entry
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import re


@dataclass
class SentimentResult:
    """Sentiment analysis result"""
    ticker: str
    score: float  # -1 (negative) to +1 (positive)
    label: str  # POSITIVE, NEUTRAL, NEGATIVE
    news_count: int
    veto: bool
    veto_reason: str
    headlines: List[str]


@dataclass
class AnalystData:
    """Analyst consensus data"""
    ticker: str
    target_low: float
    target_avg: float
    target_high: float
    consensus: str  # Strong Buy, Buy, Hold, Sell
    analyst_count: int
    upside_pct: float


@dataclass
class CombinedScore:
    """Combined score with all factors"""
    ticker: str
    technical_score: float  # 0-100
    sentiment_score: float  # -1 to +1
    analyst_score: float  # 0-100
    combined_score: float  # Weighted combination
    signal: str  # BUY, HOLD, SELL, WAIT
    vetoed: bool
    veto_reason: str
    exit_target: float
    factors: List[str]


# Known earnings dates (should be updated regularly)
EARNINGS_CALENDAR = {
    'NVDA': '2026-02-26',
    'MU': '2026-03-20',
    'AAPL': '2026-01-30',
    'GOOGL': '2026-02-04',
    'AMZN': '2026-02-06',
    'META': '2026-02-05',
    'MSFT': '2026-01-29',
    'TSLA': '2026-01-29',
}

# Analyst targets cache (should be fetched from API in production)
ANALYST_TARGETS = {
    'MU': {'low': 107, 'avg': 320, 'high': 500, 'consensus': 'Strong Buy', 'count': 28},
    'NVDA': {'low': 200, 'avg': 256, 'high': 352, 'consensus': 'Strong Buy', 'count': 39},
    'QQQ': {'low': 571, 'avg': 754, 'high': 908, 'consensus': 'Buy', 'count': 101},
    'SLB': {'low': 45, 'avg': 62, 'high': 75, 'consensus': 'Buy', 'count': 22},
    'AMD': {'low': 120, 'avg': 180, 'high': 250, 'consensus': 'Buy', 'count': 35},
    'GOOGL': {'low': 180, 'avg': 220, 'high': 280, 'consensus': 'Strong Buy', 'count': 45},
    'AAPL': {'low': 180, 'avg': 245, 'high': 300, 'consensus': 'Buy', 'count': 40},
    'TSLA': {'low': 150, 'avg': 320, 'high': 500, 'consensus': 'Hold', 'count': 35},
    'AMZN': {'low': 200, 'avg': 260, 'high': 320, 'consensus': 'Strong Buy', 'count': 42},
    'META': {'low': 500, 'avg': 700, 'high': 850, 'consensus': 'Strong Buy', 'count': 38},
    'JPM': {'low': 200, 'avg': 250, 'high': 300, 'consensus': 'Buy', 'count': 25},
    'XOM': {'low': 100, 'avg': 125, 'high': 150, 'consensus': 'Hold', 'count': 20},
    'CVX': {'low': 150, 'avg': 175, 'high': 200, 'consensus': 'Buy', 'count': 22},
}


class SentimentAnalyzer:
    """
    Sentiment analysis for trading signals.

    Used as VETO function (10% weight):
    - Strong negative sentiment → VETO (don't buy)
    - Earnings within 7 days → VETO (binary event risk)
    - Neutral/Positive → No veto, proceed with technical
    """

    # Negative keywords that trigger caution
    NEGATIVE_KEYWORDS = [
        'lawsuit', 'sued', 'fraud', 'investigation', 'sec probe',
        'downgrade', 'miss', 'disappoints', 'warning', 'cuts guidance',
        'layoffs', 'restructuring', 'default', 'bankruptcy', 'recall',
        'hack', 'breach', 'scandal', 'resign', 'fired', 'crash'
    ]

    # Positive keywords (less weight - we don't use for entry)
    POSITIVE_KEYWORDS = [
        'upgrade', 'beat', 'exceeds', 'raises guidance', 'record',
        'breakthrough', 'partnership', 'contract', 'approval', 'launch'
    ]

    def analyze(
        self,
        ticker: str,
        headlines: List[str] = None,
        days_to_earnings: int = None
    ) -> SentimentResult:
        """
        Analyze sentiment for a ticker.

        Args:
            ticker: Stock symbol
            headlines: List of recent news headlines
            days_to_earnings: Days until next earnings

        Returns:
            SentimentResult with veto decision
        """
        veto = False
        veto_reason = ""

        # Check earnings calendar
        if days_to_earnings is None:
            days_to_earnings = self._get_days_to_earnings(ticker)

        if days_to_earnings is not None and days_to_earnings <= 7:
            veto = True
            veto_reason = f"Earnings in {days_to_earnings} days - binary event risk"

        # Analyze headlines if provided
        score = 0
        if headlines:
            positive_count = 0
            negative_count = 0

            for headline in headlines:
                headline_lower = headline.lower()

                for keyword in self.NEGATIVE_KEYWORDS:
                    if keyword in headline_lower:
                        negative_count += 1
                        break

                for keyword in self.POSITIVE_KEYWORDS:
                    if keyword in headline_lower:
                        positive_count += 1
                        break

            # Calculate score
            total = positive_count + negative_count
            if total > 0:
                score = (positive_count - negative_count) / total

            # Strong negative sentiment triggers veto
            if negative_count > positive_count and negative_count >= 2:
                veto = True
                veto_reason = f"Strong negative sentiment ({negative_count} negative vs {positive_count} positive)"

        # Determine label
        if score > 0.1:
            label = "POSITIVE"
        elif score < -0.1:
            label = "NEGATIVE"
        else:
            label = "NEUTRAL"

        return SentimentResult(
            ticker=ticker,
            score=score,
            label=label,
            news_count=len(headlines) if headlines else 0,
            veto=veto,
            veto_reason=veto_reason,
            headlines=headlines[:5] if headlines else []
        )

    def _get_days_to_earnings(self, ticker: str) -> Optional[int]:
        """Get days until next earnings from calendar"""
        earnings_date_str = EARNINGS_CALENDAR.get(ticker.upper())
        if not earnings_date_str:
            return None

        try:
            earnings_date = datetime.strptime(earnings_date_str, '%Y-%m-%d')
            today = datetime.now()
            days = (earnings_date - today).days
            return max(0, days)
        except:
            return None


class AnalystIntegration:
    """
    Analyst data integration for exit targets.

    Used for EXIT prices only (5% weight):
    - Average target → Primary exit target
    - Consensus rating → Confidence adjustment
    - NOT used for entry decisions
    """

    CONSENSUS_MULTIPLIER = {
        'Strong Buy': 1.0,
        'Buy': 0.9,
        'Hold': 0.7,
        'Sell': 0.5,
        'Strong Sell': 0.3
    }

    def get_analyst_data(self, ticker: str, current_price: float) -> AnalystData:
        """
        Get analyst consensus data for a ticker.

        Args:
            ticker: Stock symbol
            current_price: Current stock price

        Returns:
            AnalystData with targets and consensus
        """
        data = ANALYST_TARGETS.get(ticker.upper())

        if not data:
            # Default: 10% upside target
            return AnalystData(
                ticker=ticker,
                target_low=current_price * 0.9,
                target_avg=current_price * 1.10,
                target_high=current_price * 1.20,
                consensus='Hold',
                analyst_count=0,
                upside_pct=10.0
            )

        upside = ((data['avg'] - current_price) / current_price) * 100

        return AnalystData(
            ticker=ticker,
            target_low=data['low'],
            target_avg=data['avg'],
            target_high=data['high'],
            consensus=data['consensus'],
            analyst_count=data['count'],
            upside_pct=round(upside, 1)
        )

    def get_exit_target(self, ticker: str, current_price: float, entry_price: float) -> float:
        """
        Calculate exit target using analyst data.

        Uses conservative approach:
        - If analyst target > entry + 10%, use analyst target
        - Otherwise, use entry + 10% as minimum

        Args:
            ticker: Stock symbol
            current_price: Current price
            entry_price: Entry price

        Returns:
            Exit target price
        """
        analyst = self.get_analyst_data(ticker, current_price)

        min_target = entry_price * 1.10  # 10% minimum

        # Use analyst target if it's reasonable
        if analyst.target_avg > min_target:
            # Use average target, capped at 30% gain
            max_target = entry_price * 1.30
            return min(analyst.target_avg, max_target)

        return min_target


class CombinedScorer:
    """
    Combines Technical (85%) + Sentiment (10%) + Analyst (5%).

    Based on V26.0 research:
    - Technical generates the signal
    - Sentiment can VETO (block buy)
    - Analyst sets EXIT target
    """

    WEIGHTS = {
        'technical': 0.85,
        'sentiment': 0.10,
        'analyst': 0.05
    }

    def __init__(self):
        self.sentiment_analyzer = SentimentAnalyzer()
        self.analyst_integration = AnalystIntegration()

    def calculate_combined_score(
        self,
        ticker: str,
        technical_score: float,
        technical_signal: str,
        current_price: float,
        entry_price: float = None,
        headlines: List[str] = None,
        days_to_earnings: int = None
    ) -> CombinedScore:
        """
        Calculate combined score with all factors.

        Args:
            ticker: Stock symbol
            technical_score: Score from technical analysis (0-100)
            technical_signal: Signal from technical (BUY, HOLD, SELL)
            current_price: Current stock price
            entry_price: Entry price (for exit target calculation)
            headlines: Recent news headlines
            days_to_earnings: Days until earnings

        Returns:
            CombinedScore with final recommendation
        """
        factors = []

        # 1. Technical (85%)
        tech_contribution = technical_score * self.WEIGHTS['technical']
        factors.append(f"Technical: {technical_score:.0f} × 85% = {tech_contribution:.1f}")

        # 2. Sentiment (10%) - VETO function
        sentiment = self.sentiment_analyzer.analyze(ticker, headlines, days_to_earnings)

        # Convert sentiment score (-1 to 1) to (0 to 100)
        sentiment_normalized = (sentiment.score + 1) * 50
        sentiment_contribution = sentiment_normalized * self.WEIGHTS['sentiment']
        factors.append(f"Sentiment: {sentiment.label} ({sentiment.score:+.2f}) × 10% = {sentiment_contribution:.1f}")

        # 3. Analyst (5%) - Exit target
        analyst = self.analyst_integration.get_analyst_data(ticker, current_price)

        # Convert analyst consensus to score
        analyst_multiplier = AnalystIntegration.CONSENSUS_MULTIPLIER.get(analyst.consensus, 0.7)
        analyst_score = min(100, analyst.upside_pct * 2) * analyst_multiplier
        analyst_contribution = analyst_score * self.WEIGHTS['analyst']
        factors.append(f"Analyst: {analyst.consensus} ({analyst.upside_pct:+.1f}% upside) × 5% = {analyst_contribution:.1f}")

        # Combined score
        combined = tech_contribution + sentiment_contribution + analyst_contribution

        # Determine final signal
        if sentiment.veto:
            signal = "WAIT"
            factors.append(f"⚠️ VETO: {sentiment.veto_reason}")
        elif technical_signal == "BUY" and combined >= 50:
            signal = "BUY"
        elif technical_signal == "SELL":
            signal = "SELL"
        else:
            signal = "HOLD"

        # Calculate exit target
        if entry_price is None:
            entry_price = current_price
        exit_target = self.analyst_integration.get_exit_target(ticker, current_price, entry_price)

        factors.append(f"Exit Target: ${exit_target:.2f} (Analyst avg: ${analyst.target_avg:.2f})")

        return CombinedScore(
            ticker=ticker,
            technical_score=technical_score,
            sentiment_score=sentiment.score,
            analyst_score=analyst_score,
            combined_score=combined,
            signal=signal,
            vetoed=sentiment.veto,
            veto_reason=sentiment.veto_reason,
            exit_target=exit_target,
            factors=factors
        )
