"""
Multi-Sector Strategy Engine
============================

Different sectors require different trading strategies.

Research shows:
- Tech: RSI mean reversion works (75-91% win rate)
- Energy: Momentum/trend following + oil correlation
- Financials: Interest rate sensitivity + relative strength
- Consumer: Sector rotation, leading indicator
- Healthcare: Event-driven, volatility breakout
- Utilities: Yield-based, inverse rate correlation
- Materials: Commodity correlation, late cycle momentum

References:
- Fidelity Sector Outlook 2025
- StockCharts Sector Rotation Analysis
- Faber's Sector Rotation Strategy
"""

from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import statistics


class Sector(Enum):
    TECHNOLOGY = "TECHNOLOGY"
    ENERGY = "ENERGY"
    FINANCIALS = "FINANCIALS"
    HEALTHCARE = "HEALTHCARE"
    CONSUMER_DISCRETIONARY = "CONSUMER_DISCRETIONARY"
    CONSUMER_STAPLES = "CONSUMER_STAPLES"
    UTILITIES = "UTILITIES"
    MATERIALS = "MATERIALS"
    INDUSTRIALS = "INDUSTRIALS"
    REAL_ESTATE = "REAL_ESTATE"
    COMMUNICATION = "COMMUNICATION"
    ETF = "ETF"
    UNKNOWN = "UNKNOWN"


class StrategyType(Enum):
    MEAN_REVERSION = "MEAN_REVERSION"  # RSI oversold bounce
    MOMENTUM = "MOMENTUM"  # Trend following
    BREAKOUT = "BREAKOUT"  # Volatility expansion
    RELATIVE_STRENGTH = "RELATIVE_STRENGTH"  # Outperformer
    SECTOR_ROTATION = "SECTOR_ROTATION"  # Business cycle
    DIVIDEND_YIELD = "DIVIDEND_YIELD"  # Income focused


@dataclass
class SectorSignal:
    """Signal from sector-specific strategy"""
    ticker: str
    sector: Sector
    strategy: StrategyType
    signal: str  # BUY, SELL, HOLD
    score: float  # 0-100
    confidence: float  # 0-100
    factors: List[str]
    entry_price: float = None
    stop_loss: float = None
    target_price: float = None


# Sector classification for common stocks
SECTOR_MAP = {
    # Technology
    'AAPL': Sector.TECHNOLOGY, 'MSFT': Sector.TECHNOLOGY, 'GOOGL': Sector.TECHNOLOGY,
    'GOOG': Sector.TECHNOLOGY, 'META': Sector.TECHNOLOGY, 'NVDA': Sector.TECHNOLOGY,
    'AMD': Sector.TECHNOLOGY, 'INTC': Sector.TECHNOLOGY, 'MU': Sector.TECHNOLOGY,
    'AVGO': Sector.TECHNOLOGY, 'QCOM': Sector.TECHNOLOGY, 'TXN': Sector.TECHNOLOGY,
    'CRM': Sector.TECHNOLOGY, 'ADBE': Sector.TECHNOLOGY, 'NOW': Sector.TECHNOLOGY,
    'ORCL': Sector.TECHNOLOGY, 'IBM': Sector.TECHNOLOGY, 'CSCO': Sector.TECHNOLOGY,

    # Energy
    'XOM': Sector.ENERGY, 'CVX': Sector.ENERGY, 'SLB': Sector.ENERGY,
    'COP': Sector.ENERGY, 'EOG': Sector.ENERGY, 'DVN': Sector.ENERGY,
    'MPC': Sector.ENERGY, 'VLO': Sector.ENERGY, 'PSX': Sector.ENERGY,
    'OXY': Sector.ENERGY, 'HAL': Sector.ENERGY, 'BKR': Sector.ENERGY,

    # Financials
    'JPM': Sector.FINANCIALS, 'BAC': Sector.FINANCIALS, 'WFC': Sector.FINANCIALS,
    'GS': Sector.FINANCIALS, 'MS': Sector.FINANCIALS, 'C': Sector.FINANCIALS,
    'BLK': Sector.FINANCIALS, 'SCHW': Sector.FINANCIALS, 'AXP': Sector.FINANCIALS,
    'V': Sector.FINANCIALS, 'MA': Sector.FINANCIALS, 'PYPL': Sector.FINANCIALS,

    # Healthcare
    'JNJ': Sector.HEALTHCARE, 'UNH': Sector.HEALTHCARE, 'PFE': Sector.HEALTHCARE,
    'ABBV': Sector.HEALTHCARE, 'MRK': Sector.HEALTHCARE, 'LLY': Sector.HEALTHCARE,
    'TMO': Sector.HEALTHCARE, 'ABT': Sector.HEALTHCARE, 'DHR': Sector.HEALTHCARE,
    'BMY': Sector.HEALTHCARE, 'AMGN': Sector.HEALTHCARE, 'GILD': Sector.HEALTHCARE,

    # Consumer Discretionary
    'AMZN': Sector.CONSUMER_DISCRETIONARY, 'TSLA': Sector.CONSUMER_DISCRETIONARY,
    'HD': Sector.CONSUMER_DISCRETIONARY, 'MCD': Sector.CONSUMER_DISCRETIONARY,
    'NKE': Sector.CONSUMER_DISCRETIONARY, 'SBUX': Sector.CONSUMER_DISCRETIONARY,
    'LOW': Sector.CONSUMER_DISCRETIONARY, 'TJX': Sector.CONSUMER_DISCRETIONARY,
    'BKNG': Sector.CONSUMER_DISCRETIONARY, 'MAR': Sector.CONSUMER_DISCRETIONARY,

    # Consumer Staples
    'PG': Sector.CONSUMER_STAPLES, 'KO': Sector.CONSUMER_STAPLES,
    'PEP': Sector.CONSUMER_STAPLES, 'COST': Sector.CONSUMER_STAPLES,
    'WMT': Sector.CONSUMER_STAPLES, 'PM': Sector.CONSUMER_STAPLES,
    'MO': Sector.CONSUMER_STAPLES, 'CL': Sector.CONSUMER_STAPLES,

    # Utilities
    'NEE': Sector.UTILITIES, 'DUK': Sector.UTILITIES, 'SO': Sector.UTILITIES,
    'D': Sector.UTILITIES, 'AEP': Sector.UTILITIES, 'EXC': Sector.UTILITIES,
    'SRE': Sector.UTILITIES, 'XEL': Sector.UTILITIES, 'CEG': Sector.UTILITIES,

    # Materials
    'LIN': Sector.MATERIALS, 'APD': Sector.MATERIALS, 'SHW': Sector.MATERIALS,
    'FCX': Sector.MATERIALS, 'NEM': Sector.MATERIALS, 'NUE': Sector.MATERIALS,
    'DD': Sector.MATERIALS, 'DOW': Sector.MATERIALS, 'ECL': Sector.MATERIALS,

    # Industrials
    'CAT': Sector.INDUSTRIALS, 'BA': Sector.INDUSTRIALS, 'HON': Sector.INDUSTRIALS,
    'UPS': Sector.INDUSTRIALS, 'RTX': Sector.INDUSTRIALS, 'DE': Sector.INDUSTRIALS,
    'LMT': Sector.INDUSTRIALS, 'GE': Sector.INDUSTRIALS, 'MMM': Sector.INDUSTRIALS,

    # Communication
    'DIS': Sector.COMMUNICATION, 'NFLX': Sector.COMMUNICATION,
    'CMCSA': Sector.COMMUNICATION, 'T': Sector.COMMUNICATION,
    'VZ': Sector.COMMUNICATION, 'TMUS': Sector.COMMUNICATION,

    # Real Estate
    'AMT': Sector.REAL_ESTATE, 'PLD': Sector.REAL_ESTATE,
    'CCI': Sector.REAL_ESTATE, 'EQIX': Sector.REAL_ESTATE,
    'PSA': Sector.REAL_ESTATE, 'SPG': Sector.REAL_ESTATE,

    # ETFs
    'QQQ': Sector.ETF, 'SPY': Sector.ETF, 'IWM': Sector.ETF,
    'XLK': Sector.ETF, 'XLE': Sector.ETF, 'XLF': Sector.ETF,
    'XLV': Sector.ETF, 'XLY': Sector.ETF, 'XLP': Sector.ETF,

    # Crypto-related
    'COIN': Sector.FINANCIALS, 'MARA': Sector.FINANCIALS, 'RIOT': Sector.FINANCIALS,
}


# Best strategy for each sector based on research
SECTOR_STRATEGY_MAP = {
    Sector.TECHNOLOGY: {
        'primary': StrategyType.MEAN_REVERSION,
        'secondary': StrategyType.MOMENTUM,
        'indicators': ['RSI(2)', 'SMA(50)', 'Volume'],
        'rsi_threshold': 20,
        'trend_filter': True,
        'notes': 'RSI mean reversion works best (75-91% win rate)'
    },
    Sector.ENERGY: {
        'primary': StrategyType.MOMENTUM,
        'secondary': StrategyType.BREAKOUT,
        'indicators': ['SMA(50/200)', 'RSI(14)', 'Oil Price'],
        'rsi_threshold': 30,  # Less extreme
        'trend_filter': True,
        'notes': 'Follows oil prices, use trend following not mean reversion'
    },
    Sector.FINANCIALS: {
        'primary': StrategyType.RELATIVE_STRENGTH,
        'secondary': StrategyType.MOMENTUM,
        'indicators': ['RS vs SPY', 'Interest Rates', 'RSI(14)'],
        'rsi_threshold': 30,
        'trend_filter': True,
        'notes': 'Correlates with interest rates, use relative strength'
    },
    Sector.HEALTHCARE: {
        'primary': StrategyType.BREAKOUT,
        'secondary': StrategyType.MEAN_REVERSION,
        'indicators': ['Volatility', 'RSI(14)', 'Event Calendar'],
        'rsi_threshold': 25,
        'trend_filter': False,  # Event-driven
        'notes': 'Event-driven (FDA, earnings), volatility breakouts'
    },
    Sector.CONSUMER_DISCRETIONARY: {
        'primary': StrategyType.SECTOR_ROTATION,
        'secondary': StrategyType.MOMENTUM,
        'indicators': ['Business Cycle', 'Consumer Sentiment', 'RSI(14)'],
        'rsi_threshold': 25,
        'trend_filter': True,
        'notes': 'Leading indicator, early cycle outperformer'
    },
    Sector.CONSUMER_STAPLES: {
        'primary': StrategyType.DIVIDEND_YIELD,
        'secondary': StrategyType.RELATIVE_STRENGTH,
        'indicators': ['Dividend Yield', 'RSI(14)', 'Defensive Score'],
        'rsi_threshold': 30,
        'trend_filter': False,
        'notes': 'Defensive, outperforms in late cycle'
    },
    Sector.UTILITIES: {
        'primary': StrategyType.DIVIDEND_YIELD,
        'secondary': StrategyType.MEAN_REVERSION,
        'indicators': ['Yield', 'Interest Rates (inverse)', 'RSI(14)'],
        'rsi_threshold': 30,
        'trend_filter': False,
        'notes': 'Inverse correlation with interest rates'
    },
    Sector.MATERIALS: {
        'primary': StrategyType.MOMENTUM,
        'secondary': StrategyType.SECTOR_ROTATION,
        'indicators': ['Commodity Prices', 'RSI(14)', 'Business Cycle'],
        'rsi_threshold': 30,
        'trend_filter': True,
        'notes': 'Late cycle, follows commodity prices'
    },
    Sector.INDUSTRIALS: {
        'primary': StrategyType.MOMENTUM,
        'secondary': StrategyType.RELATIVE_STRENGTH,
        'indicators': ['PMI', 'RSI(14)', 'Economic Data'],
        'rsi_threshold': 25,
        'trend_filter': True,
        'notes': 'Cyclical, correlates with economic growth'
    },
    Sector.COMMUNICATION: {
        'primary': StrategyType.MEAN_REVERSION,
        'secondary': StrategyType.MOMENTUM,
        'indicators': ['RSI(2)', 'SMA(50)', 'Subscriber Growth'],
        'rsi_threshold': 20,
        'trend_filter': True,
        'notes': 'Similar to tech, RSI mean reversion works'
    },
    Sector.REAL_ESTATE: {
        'primary': StrategyType.DIVIDEND_YIELD,
        'secondary': StrategyType.RELATIVE_STRENGTH,
        'indicators': ['FFO Yield', 'Interest Rates', 'RSI(14)'],
        'rsi_threshold': 30,
        'trend_filter': False,
        'notes': 'Rate sensitive, yield focused'
    },
    Sector.ETF: {
        'primary': StrategyType.MEAN_REVERSION,
        'secondary': StrategyType.MOMENTUM,
        'indicators': ['RSI(2)', 'SMA(50)', 'Breadth'],
        'rsi_threshold': 15,  # Tighter for ETFs
        'trend_filter': True,
        'notes': 'ETFs work well with RSI mean reversion'
    },
}


class SectorStrategyEngine:
    """
    Multi-sector adaptive strategy engine.

    Automatically selects the best strategy based on stock sector.
    """

    @staticmethod
    def get_sector(ticker: str) -> Sector:
        """Get sector for a ticker"""
        return SECTOR_MAP.get(ticker.upper(), Sector.UNKNOWN)

    @staticmethod
    def get_strategy_config(sector: Sector) -> dict:
        """Get strategy configuration for a sector"""
        return SECTOR_STRATEGY_MAP.get(sector, SECTOR_STRATEGY_MAP[Sector.TECHNOLOGY])

    @staticmethod
    def calc_rsi(closes: List[float], period: int) -> float:
        """Calculate RSI"""
        if len(closes) < period + 1:
            return 50
        gains, losses = [], []
        for i in range(1, len(closes)):
            diff = closes[i] - closes[i-1]
            gains.append(max(0, diff))
            losses.append(max(0, -diff))
        if len(gains) < period:
            return 50
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def calc_sma(prices: List[float], period: int) -> float:
        """Calculate SMA"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        return sum(prices[-period:]) / period

    @staticmethod
    def calc_momentum(closes: List[float], period: int = 20) -> float:
        """Calculate momentum (rate of change)"""
        if len(closes) < period:
            return 0
        return ((closes[-1] - closes[-period]) / closes[-period]) * 100

    @staticmethod
    def calc_relative_strength(closes: List[float], benchmark_closes: List[float], period: int = 20) -> float:
        """Calculate relative strength vs benchmark"""
        if len(closes) < period or len(benchmark_closes) < period:
            return 0
        stock_return = ((closes[-1] - closes[-period]) / closes[-period]) * 100
        bench_return = ((benchmark_closes[-1] - benchmark_closes[-period]) / benchmark_closes[-period]) * 100
        return stock_return - bench_return

    @staticmethod
    def calc_volatility(closes: List[float], period: int = 20) -> float:
        """Calculate volatility (standard deviation of returns)"""
        if len(closes) < period + 1:
            return 0
        returns = [(closes[i] - closes[i-1]) / closes[i-1] * 100 for i in range(1, len(closes))]
        if len(returns) < period:
            return 0
        return statistics.stdev(returns[-period:])

    def generate_signal(
        self,
        ticker: str,
        closes: List[float],
        volumes: List[float] = None,
        highs: List[float] = None,
        lows: List[float] = None,
        benchmark_closes: List[float] = None  # SPY for relative strength
    ) -> SectorSignal:
        """
        Generate signal using sector-appropriate strategy.

        Args:
            ticker: Stock symbol
            closes: Price history
            volumes: Volume history
            highs: High prices
            lows: Low prices
            benchmark_closes: SPY closes for relative strength

        Returns:
            SectorSignal with recommendation
        """
        sector = self.get_sector(ticker)
        config = self.get_strategy_config(sector)
        strategy = config['primary']

        price = closes[-1]
        sma50 = self.calc_sma(closes, 50)
        sma200 = self.calc_sma(closes, 200)

        # Route to appropriate strategy
        if strategy == StrategyType.MEAN_REVERSION:
            return self._mean_reversion_signal(ticker, closes, volumes, sector, config)
        elif strategy == StrategyType.MOMENTUM:
            return self._momentum_signal(ticker, closes, volumes, sector, config)
        elif strategy == StrategyType.RELATIVE_STRENGTH:
            return self._relative_strength_signal(ticker, closes, benchmark_closes, sector, config)
        elif strategy == StrategyType.BREAKOUT:
            return self._breakout_signal(ticker, closes, highs, lows, sector, config)
        elif strategy == StrategyType.SECTOR_ROTATION:
            return self._sector_rotation_signal(ticker, closes, benchmark_closes, sector, config)
        elif strategy == StrategyType.DIVIDEND_YIELD:
            return self._dividend_yield_signal(ticker, closes, sector, config)
        else:
            # Default to mean reversion
            return self._mean_reversion_signal(ticker, closes, volumes, sector, config)

    def _mean_reversion_signal(
        self,
        ticker: str,
        closes: List[float],
        volumes: List[float],
        sector: Sector,
        config: dict
    ) -> SectorSignal:
        """RSI(2) mean reversion strategy (best for Tech, ETFs)"""
        price = closes[-1]
        rsi2 = self.calc_rsi(closes, 2)
        rsi14 = self.calc_rsi(closes, 14)
        sma50 = self.calc_sma(closes, 50)
        sma200 = self.calc_sma(closes, 200)

        factors = []
        score = 0

        # Trend filter
        if config['trend_filter'] and price <= sma50:
            return SectorSignal(
                ticker=ticker,
                sector=sector,
                strategy=StrategyType.MEAN_REVERSION,
                signal="HOLD",
                score=0,
                confidence=0,
                factors=["Price below SMA(50) - no uptrend"],
            )

        factors.append(f"Price ${price:.2f} > SMA50 ${sma50:.2f}")
        score += 20

        # RSI scoring
        threshold = config['rsi_threshold']
        if rsi2 < 5:
            score += 40
            factors.append(f"RSI(2)={rsi2:.1f} EXTREME oversold")
        elif rsi2 < 10:
            score += 30
            factors.append(f"RSI(2)={rsi2:.1f} very oversold")
        elif rsi2 < threshold:
            score += 20
            factors.append(f"RSI(2)={rsi2:.1f} oversold (<{threshold})")
        else:
            return SectorSignal(
                ticker=ticker,
                sector=sector,
                strategy=StrategyType.MEAN_REVERSION,
                signal="HOLD",
                score=score,
                confidence=0,
                factors=[f"RSI(2)={rsi2:.1f} not oversold (need <{threshold})"],
            )

        # Additional factors
        if price > sma200:
            score += 10
            factors.append(f"Price > SMA200 (strong uptrend)")

        if rsi14 < 40:
            score += 10
            factors.append(f"RSI(14)={rsi14:.1f} < 40 (confirmation)")

        # Determine signal
        signal = "BUY" if score >= 60 else "HOLD"
        confidence = min(100, score * 1.2)

        # Calculate levels
        stop_loss = price * 0.92  # 8% stop
        target = price * 1.10  # 10% target

        return SectorSignal(
            ticker=ticker,
            sector=sector,
            strategy=StrategyType.MEAN_REVERSION,
            signal=signal,
            score=score,
            confidence=confidence,
            factors=factors,
            entry_price=price,
            stop_loss=stop_loss,
            target_price=target
        )

    def _momentum_signal(
        self,
        ticker: str,
        closes: List[float],
        volumes: List[float],
        sector: Sector,
        config: dict
    ) -> SectorSignal:
        """Momentum/trend following strategy (best for Energy, Materials)"""
        price = closes[-1]
        sma50 = self.calc_sma(closes, 50)
        sma200 = self.calc_sma(closes, 200)
        rsi14 = self.calc_rsi(closes, 14)
        momentum_20 = self.calc_momentum(closes, 20)
        momentum_50 = self.calc_momentum(closes, 50)

        factors = []
        score = 0

        # Trend alignment (Golden Cross)
        if sma50 > sma200:
            score += 25
            factors.append("SMA50 > SMA200 (Golden Cross - Uptrend)")
        else:
            factors.append("SMA50 < SMA200 (Death Cross - Downtrend)")

        # Price above moving averages
        if price > sma50:
            score += 20
            factors.append(f"Price > SMA50 ${sma50:.2f}")

        if price > sma200:
            score += 10
            factors.append(f"Price > SMA200 ${sma200:.2f}")

        # Momentum
        if momentum_20 > 5:
            score += 20
            factors.append(f"20-day momentum +{momentum_20:.1f}% (strong)")
        elif momentum_20 > 0:
            score += 10
            factors.append(f"20-day momentum +{momentum_20:.1f}%")
        else:
            factors.append(f"20-day momentum {momentum_20:.1f}% (weak)")

        if momentum_50 > 10:
            score += 15
            factors.append(f"50-day momentum +{momentum_50:.1f}%")

        # RSI not overbought
        if rsi14 < 70:
            score += 10
            factors.append(f"RSI(14)={rsi14:.1f} not overbought")
        else:
            score -= 10
            factors.append(f"WARNING: RSI(14)={rsi14:.1f} overbought")

        # Signal
        signal = "BUY" if score >= 60 and momentum_20 > 0 else "HOLD"
        confidence = min(100, score)

        # Wider stops for momentum (trend following)
        stop_loss = price * 0.90  # 10% stop
        target = price * 1.15  # 15% target

        return SectorSignal(
            ticker=ticker,
            sector=sector,
            strategy=StrategyType.MOMENTUM,
            signal=signal,
            score=score,
            confidence=confidence,
            factors=factors,
            entry_price=price,
            stop_loss=stop_loss,
            target_price=target
        )

    def _relative_strength_signal(
        self,
        ticker: str,
        closes: List[float],
        benchmark_closes: List[float],
        sector: Sector,
        config: dict
    ) -> SectorSignal:
        """Relative strength strategy (best for Financials)"""
        price = closes[-1]
        sma50 = self.calc_sma(closes, 50)
        rsi14 = self.calc_rsi(closes, 14)

        factors = []
        score = 0

        # Relative strength vs benchmark
        if benchmark_closes and len(benchmark_closes) >= 20:
            rs = self.calc_relative_strength(closes, benchmark_closes, 20)
            if rs > 5:
                score += 30
                factors.append(f"Outperforming SPY by {rs:.1f}% (strong)")
            elif rs > 0:
                score += 15
                factors.append(f"Outperforming SPY by {rs:.1f}%")
            else:
                factors.append(f"Underperforming SPY by {abs(rs):.1f}%")
        else:
            factors.append("No benchmark data for RS calculation")

        # Price trend
        if price > sma50:
            score += 20
            factors.append(f"Price > SMA50")

        # RSI in good range
        if 40 < rsi14 < 70:
            score += 15
            factors.append(f"RSI(14)={rsi14:.1f} in healthy range")
        elif rsi14 <= 40:
            score += 20
            factors.append(f"RSI(14)={rsi14:.1f} oversold - opportunity")

        # Momentum
        momentum = self.calc_momentum(closes, 20)
        if momentum > 3:
            score += 15
            factors.append(f"Positive momentum +{momentum:.1f}%")

        signal = "BUY" if score >= 50 else "HOLD"
        confidence = min(100, score * 1.3)

        stop_loss = price * 0.93  # 7% stop
        target = price * 1.12  # 12% target

        return SectorSignal(
            ticker=ticker,
            sector=sector,
            strategy=StrategyType.RELATIVE_STRENGTH,
            signal=signal,
            score=score,
            confidence=confidence,
            factors=factors,
            entry_price=price,
            stop_loss=stop_loss,
            target_price=target
        )

    def _breakout_signal(
        self,
        ticker: str,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        sector: Sector,
        config: dict
    ) -> SectorSignal:
        """Volatility breakout strategy (best for Healthcare)"""
        price = closes[-1]

        if highs is None:
            highs = closes
        if lows is None:
            lows = closes

        # Calculate 20-day high/low
        high_20 = max(highs[-20:]) if len(highs) >= 20 else price
        low_20 = min(lows[-20:]) if len(lows) >= 20 else price
        range_20 = high_20 - low_20

        # Volatility
        volatility = self.calc_volatility(closes, 20)
        avg_volatility = self.calc_volatility(closes, 60) if len(closes) >= 60 else volatility

        factors = []
        score = 0

        # Breakout detection
        distance_from_high = (high_20 - price) / high_20 * 100
        if distance_from_high < 2:
            score += 30
            factors.append(f"Near 20-day high (within {distance_from_high:.1f}%)")
        elif distance_from_high < 5:
            score += 15
            factors.append(f"Approaching 20-day high ({distance_from_high:.1f}% away)")

        # Volatility expansion
        if volatility > avg_volatility * 1.2:
            score += 20
            factors.append(f"Volatility expanding ({volatility:.2f}% vs avg {avg_volatility:.2f}%)")

        # Range position
        range_position = (price - low_20) / range_20 * 100 if range_20 > 0 else 50
        if range_position > 80:
            score += 15
            factors.append(f"Price in upper 20% of range")

        # RSI momentum
        rsi14 = self.calc_rsi(closes, 14)
        if 50 < rsi14 < 70:
            score += 15
            factors.append(f"RSI(14)={rsi14:.1f} showing momentum")

        signal = "BUY" if score >= 50 and distance_from_high < 3 else "HOLD"
        confidence = min(100, score)

        stop_loss = low_20 * 0.98  # Below recent low
        target = price * 1.15  # 15% target

        return SectorSignal(
            ticker=ticker,
            sector=sector,
            strategy=StrategyType.BREAKOUT,
            signal=signal,
            score=score,
            confidence=confidence,
            factors=factors,
            entry_price=price,
            stop_loss=stop_loss,
            target_price=target
        )

    def _sector_rotation_signal(
        self,
        ticker: str,
        closes: List[float],
        benchmark_closes: List[float],
        sector: Sector,
        config: dict
    ) -> SectorSignal:
        """Sector rotation strategy (best for Consumer Discretionary)"""
        # Similar to relative strength but with business cycle awareness
        return self._relative_strength_signal(ticker, closes, benchmark_closes, sector, config)

    def _dividend_yield_signal(
        self,
        ticker: str,
        closes: List[float],
        sector: Sector,
        config: dict
    ) -> SectorSignal:
        """Dividend yield strategy (best for Utilities, Staples, REITs)"""
        price = closes[-1]
        sma50 = self.calc_sma(closes, 50)
        sma200 = self.calc_sma(closes, 200)
        rsi14 = self.calc_rsi(closes, 14)

        factors = []
        score = 0

        # For yield stocks, we want price near support
        distance_from_sma200 = (price - sma200) / sma200 * 100

        if distance_from_sma200 < 5:
            score += 25
            factors.append(f"Price near SMA200 support (within {distance_from_sma200:.1f}%)")
        elif distance_from_sma200 < 10:
            score += 15
            factors.append(f"Price {distance_from_sma200:.1f}% above SMA200")

        # RSI oversold is good for yield stocks
        if rsi14 < 40:
            score += 25
            factors.append(f"RSI(14)={rsi14:.1f} oversold - good entry for yield")
        elif rsi14 < 50:
            score += 15
            factors.append(f"RSI(14)={rsi14:.1f} neutral")

        # Long-term trend
        if sma50 > sma200:
            score += 15
            factors.append("Long-term uptrend intact")

        # Stability (low volatility preferred)
        volatility = self.calc_volatility(closes, 20)
        if volatility < 2:
            score += 15
            factors.append(f"Low volatility {volatility:.2f}% (stable)")

        signal = "BUY" if score >= 50 else "HOLD"
        confidence = min(100, score * 1.2)

        stop_loss = price * 0.95  # 5% stop (tighter for yield)
        target = price * 1.08  # 8% target (plus dividend)

        return SectorSignal(
            ticker=ticker,
            sector=sector,
            strategy=StrategyType.DIVIDEND_YIELD,
            signal=signal,
            score=score,
            confidence=confidence,
            factors=factors,
            entry_price=price,
            stop_loss=stop_loss,
            target_price=target
        )
