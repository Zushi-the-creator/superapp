"""
Position Signal Checker
Monitors all positions for entry AND exit signals based on assigned models.
Records all signals and detects missed signals.
"""

import sqlite3
import pandas as pd
import requests
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
import json
import uuid


@dataclass
class Signal:
    signal_id: str
    timestamp: str
    ticker: str
    model: str
    signal_type: str  # BUY, SELL, HOLD
    reason: str
    urgency: str  # HIGH, MEDIUM, LOW
    price_at_signal: float
    indicators: Dict[str, float]
    position_info: Optional[Dict[str, Any]] = None


@dataclass
class MissedSignal:
    date: str
    ticker: str
    model: str
    signal_type: str
    indicator_value: float
    threshold: str
    price_at_signal: float
    price_now: float
    impact_pct: float


# Position configurations with entry dates
POSITIONS = {
    'VST': {
        'shares': 7.9038,
        'entry_price': 169.58,
        'entry_date': '2026-01-05',
        'cost_basis': 1340.33,
        'model': 'V17.0'
    },
    'LLY': {
        'shares': 1,
        'entry_price': 1080.50,
        'entry_date': '2026-01-08',
        'cost_basis': 1080.50,
        'model': 'V15.0'
    },
    'COIN': {
        'shares': 2.7926,
        'entry_price': 256.39,
        'entry_date': '2026-01-10',
        'cost_basis': 715.99,
        'model': 'V20.0'
    },
    'QQQ': {
        'shares': 0.799,
        'entry_price': 619.55,
        'entry_date': '2026-01-15',
        'cost_basis': 494.82,
        'model': 'V15.0'
    }
}

# Buy recommendations when selling - RULE: Always suggest what to buy
BUY_RECOMMENDATIONS = {
    'COIN': {
        'replace_with': 'CEG',
        'reason': 'Constellation Energy: Policy panic oversold (-10%), at -3 StdDev BB, BofA maintained Buy',
        'limit_price': 305.00,
        'target': '+8-10%'
    },
    'LLY': {
        'replace_with': 'MU',
        'reason': 'Micron: $7.8M insider buy by Mark Liu (ex-TSMC CEO), AI memory demand',
        'limit_price': 110.50,
        'target': '+5-7%'
    },
    'VST': {
        'replace_with': 'HOLD_HALF',
        'reason': 'Keep 50% - UBS target $233, Meta deal floor at $160',
        'limit_price': None,
        'target': '+5%'
    }
}


class PositionSignalChecker:
    def __init__(self, db_path: str = 'signal_history.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize signal history database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                timestamp TEXT,
                ticker TEXT,
                model TEXT,
                signal_type TEXT,
                reason TEXT,
                urgency TEXT,
                price_at_signal REAL,
                indicators TEXT,
                position_info TEXT,
                was_followed INTEGER DEFAULT NULL,
                outcome_price REAL DEFAULT NULL,
                outcome_date TEXT DEFAULT NULL,
                outcome_pct REAL DEFAULT NULL,
                signal_was_correct INTEGER DEFAULT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS missed_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_date TEXT,
                signal_date TEXT,
                ticker TEXT,
                model TEXT,
                signal_type TEXT,
                indicator_value REAL,
                threshold TEXT,
                price_at_signal REAL,
                price_at_detection REAL,
                impact_pct REAL
            )
        ''')

        conn.commit()
        conn.close()

    def fetch_data(self, ticker: str, days: int = 90) -> Optional[pd.DataFrame]:
        """Fetch historical data from Yahoo Finance"""
        end = int(datetime.now().timestamp())
        start = int((datetime.now() - timedelta(days=days)).timestamp())

        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
        params = {
            'period1': start,
            'period2': end,
            'interval': '1d',
            'events': 'history'
        }
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
        }

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            data = resp.json()

            if 'chart' in data and 'result' in data['chart'] and data['chart']['result']:
                result = data['chart']['result'][0]
                quotes = result['indicators']['quote'][0]
                timestamps = result['timestamp']

                df = pd.DataFrame({
                    'Date': pd.to_datetime(timestamps, unit='s'),
                    'Open': quotes['open'],
                    'High': quotes['high'],
                    'Low': quotes['low'],
                    'Close': quotes['close'],
                    'Volume': quotes['volume']
                })
                df = df.dropna()
                df = df.set_index('Date')
                return df
        except Exception as e:
            print(f"Error fetching {ticker}: {e}")
        return None

    def calc_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate RSI"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def calc_indicators(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Calculate all required indicators"""
        close = df['Close']
        current_price = close.iloc[-1]

        indicators = {
            'price': current_price,
            'rsi_2': self.calc_rsi(close, 2).iloc[-1],
            'rsi_5': self.calc_rsi(close, 5).iloc[-1],
            'rsi_14': self.calc_rsi(close, 14).iloc[-1],
            'sma_5': close.rolling(5).mean().iloc[-1],
            'sma_20': close.rolling(20).mean().iloc[-1],
            'sma_50': close.rolling(50).mean().iloc[-1] if len(close) >= 50 else close.mean(),
            'sma_200': close.rolling(200).mean().iloc[-1] if len(close) >= 200 else close.rolling(min(len(close), 50)).mean().iloc[-1],
            'ema_9': close.ewm(span=9).mean().iloc[-1],
            'ema_21': close.ewm(span=21).mean().iloc[-1],
        }

        # Bollinger Bands
        std_20 = close.rolling(20).std().iloc[-1]
        indicators['bb_upper'] = indicators['sma_20'] + (2 * std_20)
        indicators['bb_lower'] = indicators['sma_20'] - (2 * std_20)
        indicators['bb_pct'] = ((current_price - indicators['bb_lower']) /
                                (indicators['bb_upper'] - indicators['bb_lower'])) * 100

        return indicators

    def calc_indicators_at_date(self, df: pd.DataFrame, target_date: datetime) -> Optional[Dict[str, Any]]:
        """Calculate indicators as of a specific historical date"""
        # Filter data up to target date
        df_filtered = df[df.index <= target_date]
        if len(df_filtered) < 20:
            return None
        return self.calc_indicators(df_filtered)

    def check_v17_signal(self, indicators: Dict, position: Dict) -> tuple:
        """V17.0 Extreme Oversold - check for signals"""
        rsi_2 = indicators['rsi_2']
        rsi_14 = indicators['rsi_14']
        price = indicators['price']
        sma_200 = indicators['sma_200']

        entry_date = datetime.strptime(position['entry_date'], '%Y-%m-%d')
        days_held = (datetime.now() - entry_date).days

        # EXIT CONDITIONS (for existing position)
        if rsi_2 > 60:
            return 'SELL', f'RSI(2) = {rsi_2:.1f} > 60 threshold', 'HIGH'
        if days_held >= 7:
            return 'SELL', f'TIME STOP: {days_held} days held (max 7)', 'MEDIUM'

        # ENTRY CONDITIONS (if no position - not applicable here since we have position)

        # HOLD with distance to exit
        distance = 60 - rsi_2
        return 'HOLD', f'RSI(2) = {rsi_2:.1f}, {distance:.1f} points from sell trigger', 'LOW'

    def check_v15_signal(self, indicators: Dict, position: Dict) -> tuple:
        """V15.0 Connors RSI(2) - check for signals"""
        price = indicators['price']
        sma_5 = indicators['sma_5']
        rsi_2 = indicators['rsi_2']

        entry_date = datetime.strptime(position['entry_date'], '%Y-%m-%d')
        days_held = (datetime.now() - entry_date).days

        # EXIT CONDITIONS
        if price > sma_5:
            pct_above = ((price - sma_5) / sma_5) * 100
            return 'SELL', f'Price ${price:.2f} > SMA(5) ${sma_5:.2f} (+{pct_above:.2f}%)', 'HIGH'
        if days_held >= 7:
            return 'SELL', f'TIME STOP: {days_held} days held (max 7)', 'MEDIUM'

        # HOLD with distance to exit
        pct_below = ((sma_5 - price) / price) * 100
        return 'HOLD', f'Price ${price:.2f} is {pct_below:.2f}% below SMA(5) ${sma_5:.2f}', 'LOW'

    def check_v20_signal(self, indicators: Dict, position: Dict) -> tuple:
        """V20.0 RSI(5) + BB - check for signals"""
        rsi_5 = indicators['rsi_5']

        entry_date = datetime.strptime(position['entry_date'], '%Y-%m-%d')
        days_held = (datetime.now() - entry_date).days

        # EXIT CONDITIONS
        if rsi_5 > 80:
            return 'SELL', f'RSI(5) = {rsi_5:.1f} > 80 threshold', 'HIGH'
        if days_held >= 7:
            return 'SELL', f'TIME STOP: {days_held} days held (max 7)', 'MEDIUM'

        # HOLD with distance to exit
        distance = 80 - rsi_5
        return 'HOLD', f'RSI(5) = {rsi_5:.1f}, {distance:.1f} points from sell trigger', 'LOW'

    def check_position_signals(self) -> List[Signal]:
        """Check all positions for current signals"""
        signals = []

        for ticker, position in POSITIONS.items():
            print(f"\nChecking {ticker} ({position['model']})...")

            df = self.fetch_data(ticker, 90)
            if df is None or len(df) < 20:
                print(f"  Could not fetch data for {ticker}")
                continue

            indicators = self.calc_indicators(df)

            # Get model-specific signal
            model = position['model']
            if model == 'V17.0':
                signal_type, reason, urgency = self.check_v17_signal(indicators, position)
            elif model == 'V15.0':
                signal_type, reason, urgency = self.check_v15_signal(indicators, position)
            elif model == 'V20.0':
                signal_type, reason, urgency = self.check_v20_signal(indicators, position)
            else:
                signal_type, reason, urgency = 'HOLD', 'Unknown model', 'LOW'

            # Calculate position P&L
            current_value = position['shares'] * indicators['price']
            pnl = current_value - position['cost_basis']
            pnl_pct = (pnl / position['cost_basis']) * 100

            signal = Signal(
                signal_id=str(uuid.uuid4()),
                timestamp=datetime.now().isoformat(),
                ticker=ticker,
                model=model,
                signal_type=signal_type,
                reason=reason,
                urgency=urgency,
                price_at_signal=indicators['price'],
                indicators={k: round(v, 2) if isinstance(v, float) else v for k, v in indicators.items()},
                position_info={
                    'shares': position['shares'],
                    'entry_price': position['entry_price'],
                    'entry_date': position['entry_date'],
                    'current_value': round(current_value, 2),
                    'pnl': round(pnl, 2),
                    'pnl_pct': round(pnl_pct, 2)
                }
            )

            signals.append(signal)
            self._record_signal(signal)

            print(f"  {signal_type} - {reason}")

        return signals

    def detect_missed_signals(self, lookback_days: int = 7) -> List[MissedSignal]:
        """Detect sell signals that occurred in the past but weren't acted upon"""
        missed = []

        for ticker, position in POSITIONS.items():
            print(f"\nChecking {ticker} for missed signals (last {lookback_days} days)...")

            df = self.fetch_data(ticker, 90)
            if df is None or len(df) < 20:
                continue

            current_price = df['Close'].iloc[-1]
            model = position['model']

            # Check each day in lookback period
            for i in range(lookback_days, 0, -1):
                target_date = datetime.now() - timedelta(days=i)

                indicators = self.calc_indicators_at_date(df, target_date)
                if indicators is None:
                    continue

                was_signal = False
                indicator_value = 0
                threshold = ""

                # Check model-specific exit conditions
                if model == 'V17.0':
                    if indicators['rsi_2'] > 60:
                        was_signal = True
                        indicator_value = indicators['rsi_2']
                        threshold = "RSI(2) > 60"

                elif model == 'V15.0':
                    if indicators['price'] > indicators['sma_5']:
                        was_signal = True
                        indicator_value = indicators['price']
                        threshold = f"Price > SMA(5) (${indicators['sma_5']:.2f})"

                elif model == 'V20.0':
                    if indicators['rsi_5'] > 80:
                        was_signal = True
                        indicator_value = indicators['rsi_5']
                        threshold = "RSI(5) > 80"

                if was_signal:
                    impact_pct = ((current_price - indicators['price']) / indicators['price']) * 100

                    missed_signal = MissedSignal(
                        date=target_date.strftime('%Y-%m-%d'),
                        ticker=ticker,
                        model=model,
                        signal_type='SELL',
                        indicator_value=round(indicator_value, 2),
                        threshold=threshold,
                        price_at_signal=round(indicators['price'], 2),
                        price_now=round(current_price, 2),
                        impact_pct=round(impact_pct, 2)
                    )

                    missed.append(missed_signal)
                    self._record_missed_signal(missed_signal)

                    print(f"  MISSED {target_date.strftime('%Y-%m-%d')}: "
                          f"{threshold} = {indicator_value:.1f} | "
                          f"Price then: ${indicators['price']:.2f} | "
                          f"Now: ${current_price:.2f} | Impact: {impact_pct:+.2f}%")

        return missed

    def _record_signal(self, signal: Signal):
        """Record signal to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT OR REPLACE INTO signals
            (signal_id, timestamp, ticker, model, signal_type, reason, urgency,
             price_at_signal, indicators, position_info)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            signal.signal_id,
            signal.timestamp,
            signal.ticker,
            signal.model,
            signal.signal_type,
            signal.reason,
            signal.urgency,
            signal.price_at_signal,
            json.dumps(signal.indicators),
            json.dumps(signal.position_info) if signal.position_info else None
        ))

        conn.commit()
        conn.close()

    def _record_missed_signal(self, missed: MissedSignal):
        """Record missed signal to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO missed_signals
            (detected_date, signal_date, ticker, model, signal_type,
             indicator_value, threshold, price_at_signal, price_at_detection, impact_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().strftime('%Y-%m-%d'),
            missed.date,
            missed.ticker,
            missed.model,
            missed.signal_type,
            missed.indicator_value,
            missed.threshold,
            missed.price_at_signal,
            missed.price_now,
            missed.impact_pct
        ))

        conn.commit()
        conn.close()

    def get_signal_history(self, ticker: Optional[str] = None, days: int = 30) -> List[Dict]:
        """Get historical signals from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        if ticker:
            cursor.execute('''
                SELECT * FROM signals
                WHERE ticker = ? AND timestamp > ?
                ORDER BY timestamp DESC
            ''', (ticker, cutoff))
        else:
            cursor.execute('''
                SELECT * FROM signals
                WHERE timestamp > ?
                ORDER BY timestamp DESC
            ''', (cutoff,))

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()

        return [dict(zip(columns, row)) for row in rows]

    def get_missed_signals(self, days: int = 7) -> List[Dict]:
        """Get missed signals from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        cursor.execute('''
            SELECT * FROM missed_signals
            WHERE signal_date > ?
            ORDER BY signal_date DESC
        ''', (cutoff,))

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()

        return [dict(zip(columns, row)) for row in rows]

    def generate_report(self) -> str:
        """Generate a comprehensive signal report"""
        report = []
        report.append("=" * 70)
        report.append(f"POSITION SIGNAL REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("=" * 70)

        # Current signals
        report.append("\n## CURRENT SIGNALS\n")
        signals = self.check_position_signals()

        for signal in signals:
            emoji = "🔴" if signal.signal_type == "SELL" else "🟢" if signal.signal_type == "BUY" else "🟡"
            report.append(f"{emoji} {signal.ticker} ({signal.model}): {signal.signal_type}")
            report.append(f"   Reason: {signal.reason}")
            report.append(f"   Price: ${signal.price_at_signal:.2f}")
            if signal.position_info:
                report.append(f"   P&L: ${signal.position_info['pnl']:.2f} ({signal.position_info['pnl_pct']:+.2f}%)")

            # Add buy recommendation if selling
            if signal.signal_type == "SELL" and signal.ticker in BUY_RECOMMENDATIONS:
                rec = BUY_RECOMMENDATIONS[signal.ticker]
                report.append(f"   ➡️  REPLACE WITH: {rec['replace_with']}")
                report.append(f"      Reason: {rec['reason']}")
                if rec['limit_price']:
                    report.append(f"      Limit: ${rec['limit_price']:.2f} | Target: {rec['target']}")
                else:
                    report.append(f"      Target: {rec['target']}")
            report.append("")

        # Missed signals
        report.append("\n## MISSED SIGNALS (Last 7 Days)\n")
        missed = self.detect_missed_signals(7)

        if missed:
            for ms in missed:
                report.append(f"❌ {ms.ticker} on {ms.date}")
                report.append(f"   Signal: {ms.signal_type} ({ms.threshold})")
                report.append(f"   Value: {ms.indicator_value}")
                report.append(f"   Price then: ${ms.price_at_signal:.2f} → Now: ${ms.price_now:.2f}")
                report.append(f"   Impact: {ms.impact_pct:+.2f}%")
                report.append("")
        else:
            report.append("No missed signals detected.\n")

        # Buy recommendations summary
        report.append("\n## BUY RECOMMENDATIONS (When Selling)\n")
        for ticker, rec in BUY_RECOMMENDATIONS.items():
            if rec['replace_with'] != 'HOLD_HALF':
                report.append(f"🟢 {rec['replace_with']} (replaces {ticker})")
                report.append(f"   {rec['reason']}")
                if rec['limit_price']:
                    report.append(f"   Limit: ${rec['limit_price']:.2f} | Target: {rec['target']}")
                report.append("")

        # Summary
        report.append("=" * 70)
        sell_signals = [s for s in signals if s.signal_type == "SELL"]
        if sell_signals:
            report.append(f"⚠️  ACTION REQUIRED: {len(sell_signals)} SELL signal(s) active!")
            report.append(f"📋 EXECUTION PLAN: Tuesday Jan 20, 2026 (Market closed Mon for MLK Day)")
            report.append(f"   9:30 AM: Execute SELL orders")
            report.append(f"   10:30 AM: Execute BUY orders (wait 1hr for volatility)")
        else:
            report.append("✅ No immediate action required.")

        if missed:
            total_impact = sum(ms.impact_pct for ms in missed if ms.impact_pct < 0)
            report.append(f"📉 Estimated cost of missed signals: {total_impact:.2f}%")

        return "\n".join(report)


def main():
    """Run the position signal checker"""
    checker = PositionSignalChecker()
    report = checker.generate_report()
    print(report)

    # Save report to file
    with open('signal_report.txt', 'w') as f:
        f.write(report)
    print("\nReport saved to signal_report.txt")


if __name__ == "__main__":
    main()
