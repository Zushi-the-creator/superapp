"""
Israeli Market Data Fetcher & Leveraged ETF Adapter
====================================================

Provides:
1. Data fetching for Israeli stocks/ETFs via Yahoo Finance
2. Adapted ATLAS model for 3x leveraged ETFs

Leveraged ETF Adjustments:
- RSI thresholds are 3x more sensitive (moves faster)
- Shorter hold periods (decay issue)
- Tighter stops (volatility)

Supported Tickers:
- TA35.TA: TA-35 Index
- TEVA.TA: Teva Pharmaceutical
- NICE.TA: Nice Ltd
- And other .TA suffix tickers
"""

import urllib.request
import json
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta


@dataclass
class IsraeliMarketData:
    """Historical data for Israeli security"""
    ticker: str
    dates: List[str]
    opens: List[float]
    highs: List[float]
    lows: List[float]
    closes: List[float]
    volumes: List[float]
    currency: str  # ILS or USD


@dataclass
class LeveragedETFSignal:
    """Signal adapted for leveraged ETFs"""
    signal: str  # BUY, HOLD, SELL
    score: float
    rsi2: float
    rsi2_equivalent: float  # What this RSI means for 1x
    regime: str
    leverage: float
    warnings: List[str]
    max_hold_days: int
    stop_loss_pct: float
    target_pct: float
    confidence: str


def fetch_israeli_data(ticker: str, days: int = 365) -> Optional[IsraeliMarketData]:
    """
    Fetch historical data for Israeli securities from Yahoo Finance.

    Args:
        ticker: Stock/ETF ticker (e.g., 'TA35.TA', 'TEVA.TA')
        days: Number of days of history

    Returns:
        IsraeliMarketData or None if failed
    """
    # Ensure .TA suffix for TASE stocks
    if not ticker.endswith('.TA') and not ticker.startswith('^'):
        ticker = f"{ticker}.TA"

    try:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={days}d&interval=1d'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
        })

        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))

        if 'chart' not in data or 'result' not in data['chart']:
            return None

        result = data['chart']['result'][0]
        meta = result.get('meta', {})
        timestamps = result.get('timestamp', [])
        quotes = result.get('indicators', {}).get('quote', [{}])[0]

        # Convert timestamps to dates
        dates = [datetime.fromtimestamp(ts).strftime('%Y-%m-%d') for ts in timestamps]

        # Extract OHLCV, filtering None values
        opens = [o if o else 0 for o in quotes.get('open', [])]
        highs = [h if h else 0 for h in quotes.get('high', [])]
        lows = [l if l else 0 for l in quotes.get('low', [])]
        closes = [c if c else 0 for c in quotes.get('close', [])]
        volumes = [v if v else 0 for v in quotes.get('volume', [])]

        return IsraeliMarketData(
            ticker=ticker,
            dates=dates,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            volumes=volumes,
            currency=meta.get('currency', 'ILS')
        )

    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None


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


def calc_sma(prices: List[float], period: int) -> float:
    """Calculate SMA"""
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period


class LeveragedETFAdapter:
    """
    Adapts ATLAS V2.2 model for leveraged ETFs (2x, 3x).

    Key Adjustments:
    1. RSI thresholds divided by leverage (RSI moves faster)
    2. Shorter max hold (leverage decay)
    3. Tighter stops (higher volatility)
    4. Lower profit targets (decay eats gains)

    Research basis:
    - Leveraged ETFs have volatility drag (daily rebalancing)
    - Mean reversion works BETTER due to extreme moves
    - Hold periods should be 1-5 days max
    """

    # RSI thresholds for different leverage levels
    RSI_THRESHOLDS = {
        1: {'extreme': 5, 'oversold': 20, 'overbought': 80},
        2: {'extreme': 10, 'oversold': 30, 'overbought': 70},
        3: {'extreme': 15, 'oversold': 35, 'overbought': 65},
    }

    # Exit parameters by leverage (optimized from backtest)
    # Note: In BULL regime, longer holds work better for 3x
    EXIT_PARAMS = {
        1: {'max_hold': 7, 'stop': 0.08, 'target': 0.10},
        2: {'max_hold': 5, 'stop': 0.10, 'target': 0.08},
        3: {'max_hold': 5, 'stop': 0.12, 'target': 0.08},  # 5-day optimal from backtest
    }

    # Regime-adjusted hold periods for 3x ETFs
    REGIME_HOLD_DAYS = {
        'BULL': 5,      # Let winners run in uptrend
        'SIDEWAYS': 3,  # Quick exits in chop
        'BEAR': 2,      # Very quick in downtrend
    }

    def __init__(self, leverage: float = 3.0):
        """
        Initialize adapter for specific leverage.

        Args:
            leverage: ETF leverage multiplier (1, 2, or 3)
        """
        self.leverage = int(leverage)
        if self.leverage not in [1, 2, 3]:
            self.leverage = 3

        self.thresholds = self.RSI_THRESHOLDS[self.leverage]
        self.exit_params = self.EXIT_PARAMS[self.leverage]

    def analyze(self, closes: List[float], volumes: List[float] = None) -> LeveragedETFSignal:
        """
        Analyze leveraged ETF and generate signal.

        Args:
            closes: Price history (50+ days recommended)
            volumes: Volume history (optional)

        Returns:
            LeveragedETFSignal with adapted thresholds
        """
        warnings = []

        if len(closes) < 50:
            warnings.append("Insufficient data (need 50+ days)")
            return LeveragedETFSignal(
                signal="HOLD",
                score=0,
                rsi2=50,
                rsi2_equivalent=50,
                regime="UNKNOWN",
                leverage=self.leverage,
                warnings=warnings,
                max_hold_days=self.exit_params['max_hold'],
                stop_loss_pct=self.exit_params['stop'] * 100,
                target_pct=self.exit_params['target'] * 100,
                confidence="LOW"
            )

        # Calculate indicators
        rsi2 = calc_rsi(closes, 2)
        rsi14 = calc_rsi(closes, 14)
        sma50 = calc_sma(closes, 50)
        sma200 = calc_sma(closes, min(200, len(closes)))
        current_price = closes[-1]

        # Detect regime
        if current_price > sma50 > sma200:
            regime = "BULL"
        elif current_price < sma50 < sma200:
            regime = "BEAR"
        else:
            regime = "SIDEWAYS"

        # RSI equivalent (what the RSI would be for 1x)
        # For 3x ETF, RSI moves ~3x faster, so divide by leverage
        rsi2_equiv = 50 + (rsi2 - 50) / self.leverage

        # Score calculation
        score = 0
        factors = []

        # Trend check (required)
        if current_price > sma50:
            score += 20
            factors.append(f"Price > SMA50 (uptrend)")
        else:
            warnings.append("Below SMA50 - counter-trend trade")

        # RSI scoring (adjusted for leverage)
        if rsi2 < self.thresholds['extreme']:
            score += 40
            factors.append(f"RSI(2)={rsi2:.1f} EXTREME for {self.leverage}x (equiv to RSI={rsi2_equiv:.1f})")
        elif rsi2 < self.thresholds['oversold']:
            score += 25
            factors.append(f"RSI(2)={rsi2:.1f} oversold for {self.leverage}x")
        elif rsi2 > self.thresholds['overbought']:
            score -= 20
            warnings.append(f"RSI(2)={rsi2:.1f} OVERBOUGHT for {self.leverage}x")

        # Volume confirmation
        if volumes and len(volumes) >= 20:
            avg_vol = sum(volumes[-20:]) / 20
            vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1
            if vol_ratio > 1.5:
                score += 10
                factors.append(f"Volume spike {vol_ratio:.1f}x")

        # Leverage decay warning
        if self.leverage >= 2:
            warnings.append(f"⚠️ {self.leverage}x leverage - max hold {self.exit_params['max_hold']} days due to decay")

        # Determine signal
        if score >= 50 and rsi2 < self.thresholds['oversold'] and current_price > sma50:
            signal = "BUY"
            confidence = "HIGH" if score >= 70 else "MEDIUM"
        elif rsi2 > self.thresholds['overbought']:
            signal = "SELL"
            confidence = "HIGH"
        else:
            signal = "HOLD"
            confidence = "LOW"

        return LeveragedETFSignal(
            signal=signal,
            score=score,
            rsi2=rsi2,
            rsi2_equivalent=rsi2_equiv,
            regime=regime,
            leverage=self.leverage,
            warnings=warnings,
            max_hold_days=self.exit_params['max_hold'],
            stop_loss_pct=self.exit_params['stop'] * 100,
            target_pct=self.exit_params['target'] * 100,
            confidence=confidence
        )

    def backtest(self, closes: List[float], forward_days: int = None) -> Dict:
        """
        Backtest the adapted model on historical data.

        Args:
            closes: Full price history
            forward_days: Days to measure return (default: max_hold)

        Returns:
            Backtest results
        """
        if forward_days is None:
            forward_days = self.exit_params['max_hold']

        if len(closes) < 60:
            return {'error': 'Insufficient data'}

        trades = []

        for i in range(50, len(closes) - forward_days):
            window = closes[:i+1]
            signal = self.analyze(window)

            if signal.signal != "BUY":
                continue

            entry_price = closes[i]
            exit_price = closes[i + forward_days]
            return_pct = ((exit_price - entry_price) / entry_price) * 100

            trades.append({
                'day': i,
                'entry': entry_price,
                'exit': exit_price,
                'return_pct': return_pct,
                'win': return_pct > 0,
                'rsi2': signal.rsi2
            })

        if not trades:
            return {
                'trades': 0,
                'win_rate': 0,
                'avg_return': 0
            }

        wins = sum(1 for t in trades if t['win'])
        returns = [t['return_pct'] for t in trades]

        return {
            'trades': len(trades),
            'wins': wins,
            'losses': len(trades) - wins,
            'win_rate': round(wins / len(trades) * 100, 1),
            'avg_return': round(sum(returns) / len(returns), 2),
            'total_return': round(sum(returns), 2),
            'best_trade': round(max(returns), 2),
            'worst_trade': round(min(returns), 2),
            'leverage': self.leverage,
            'forward_days': forward_days
        }


def analyze_israeli_etf(ticker: str, leverage: float = 1.0, days: int = 365) -> Dict:
    """
    Complete analysis for Israeli ETF.

    Args:
        ticker: Israeli ticker (e.g., 'TA35.TA')
        leverage: ETF leverage (1, 2, or 3)
        days: Days of history to fetch

    Returns:
        Complete analysis with signal and backtest
    """
    # Fetch data
    data = fetch_israeli_data(ticker, days)
    if not data:
        return {'error': f'Could not fetch data for {ticker}'}

    # Analyze with leverage adapter
    adapter = LeveragedETFAdapter(leverage)
    signal = adapter.analyze(data.closes, data.volumes)

    # Backtest
    backtest = adapter.backtest(data.closes)

    # Current price info
    current_price = data.closes[-1]
    prev_price = data.closes[-2] if len(data.closes) > 1 else current_price
    change_1d = ((current_price - prev_price) / prev_price) * 100

    return {
        'ticker': ticker,
        'leverage': leverage,
        'currency': data.currency,
        'current_price': round(current_price, 2),
        'change_1d': round(change_1d, 2),
        'data_points': len(data.closes),
        'signal': {
            'action': signal.signal,
            'score': signal.score,
            'confidence': signal.confidence,
            'rsi2': round(signal.rsi2, 1),
            'rsi2_equivalent': round(signal.rsi2_equivalent, 1),
            'regime': signal.regime,
            'warnings': signal.warnings,
        },
        'exit_rules': {
            'max_hold_days': signal.max_hold_days,
            'stop_loss_pct': signal.stop_loss_pct,
            'target_pct': signal.target_pct,
        },
        'backtest': backtest,
    }


# Example usage
if __name__ == "__main__":
    print("=" * 60)
    print("ISRAELI MARKET ANALYSIS - TA-35 3x Leveraged")
    print("=" * 60)

    result = analyze_israeli_etf('TA35.TA', leverage=3, days=365)

    if 'error' in result:
        print(f"Error: {result['error']}")
    else:
        print(f"\nTicker: {result['ticker']}")
        print(f"Price: {result['currency']} {result['current_price']} ({result['change_1d']:+.2f}%)")
        print(f"Data points: {result['data_points']}")
        print()
        print(f"Signal: {result['signal']['action']}")
        print(f"Score: {result['signal']['score']}")
        print(f"Confidence: {result['signal']['confidence']}")
        print(f"RSI(2): {result['signal']['rsi2']} (equiv 1x: {result['signal']['rsi2_equivalent']})")
        print(f"Regime: {result['signal']['regime']}")
        print()
        print("Exit Rules:")
        print(f"  Max Hold: {result['exit_rules']['max_hold_days']} days")
        print(f"  Stop Loss: {result['exit_rules']['stop_loss_pct']}%")
        print(f"  Target: {result['exit_rules']['target_pct']}%")
        print()
        print("Backtest:")
        bt = result['backtest']
        print(f"  Trades: {bt.get('trades', 0)}")
        print(f"  Win Rate: {bt.get('win_rate', 0)}%")
        print(f"  Avg Return: {bt.get('avg_return', 0)}%")
        print()
        print("Warnings:")
        for w in result['signal']['warnings']:
            print(f"  - {w}")
