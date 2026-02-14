"""
ML Framework for Stock Trading - Expert System
===============================================
Based on 2024-2026 academic research and best practices.

Research Sources:
- Transformer vs LSTM: arxiv.org/pdf/2504.16361
- Walk-Forward Optimization: quantinsti.com/walk-forward-optimization
- XGBoost for Trading: Chen & Guestrin (2016)
- Ensemble Methods: tandfonline.com/doi/full/10.1080/08839514.2021.2001178

Key Findings:
1. Transformer (Decoder-Only) > LSTM > Traditional ML for long sequences
2. XGBoost/LightGBM best for tabular data with features
3. Walk-Forward validation essential to avoid overfitting
4. Ensemble methods (stacking) outperform single models
5. 90%+ of academic strategies fail in live trading due to overfitting

Framework Design Principles:
1. Walk-Forward Validation (not simple train/test split)
2. Multiple model ensemble with weighted voting
3. Regime detection (bull/bear/sideways)
4. Feature engineering based on proven indicators
5. Performance tracking with statistical significance testing
"""

import json
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import os

# ============================================================================
# CONFIGURATION
# ============================================================================

class ModelType(Enum):
    RULE_BASED = "rule_based"           # RSI, EMA crossover, etc.
    XGBOOST = "xgboost"                 # Gradient boosting
    RANDOM_FOREST = "random_forest"     # Ensemble trees
    LSTM = "lstm"                       # Deep learning sequence
    ENSEMBLE = "ensemble"               # Combination of above


class MarketRegime(Enum):
    BULL = "bull"           # Trending up
    BEAR = "bear"           # Trending down
    SIDEWAYS = "sideways"   # Range-bound
    HIGH_VOL = "high_vol"   # High volatility


@dataclass
class ModelVersion:
    """Track each model version for comparison"""
    version: str
    name: str
    model_type: ModelType
    parameters: Dict
    created_date: str
    description: str

    # Performance metrics (filled after backtesting)
    win_rate: float = 0.0
    avg_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    total_trades: int = 0

    # Walk-forward metrics
    in_sample_win_rate: float = 0.0
    out_of_sample_win_rate: float = 0.0
    overfitting_ratio: float = 0.0  # IS/OOS ratio, >1.5 = overfitting


@dataclass
class TradeRecord:
    """Record each trade for analysis"""
    id: int
    ticker: str
    model_version: str
    signal_date: str
    signal_type: str  # BUY, SELL, HOLD
    entry_price: float
    exit_price: float
    exit_date: str
    return_pct: float
    correct: bool
    regime: str
    confidence: float
    features: Dict  # All features at signal time


# ============================================================================
# PERFORMANCE TRACKER DATABASE
# ============================================================================

class PerformanceTracker:
    """
    SQLite-based performance tracking system.
    Documents every model change and measures improvement.
    """

    def __init__(self, db_path: str = "ml_performance.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Model versions table
        c.execute('''
            CREATE TABLE IF NOT EXISTS model_versions (
                version TEXT PRIMARY KEY,
                name TEXT,
                model_type TEXT,
                parameters TEXT,
                created_date TEXT,
                description TEXT,
                win_rate REAL,
                avg_return REAL,
                sharpe_ratio REAL,
                max_drawdown REAL,
                total_trades INTEGER,
                in_sample_win_rate REAL,
                out_of_sample_win_rate REAL,
                overfitting_ratio REAL
            )
        ''')

        # Individual trades table
        c.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT,
                model_version TEXT,
                signal_date TEXT,
                signal_type TEXT,
                entry_price REAL,
                exit_price REAL,
                exit_date TEXT,
                return_pct REAL,
                correct INTEGER,
                regime TEXT,
                confidence REAL,
                features TEXT,
                FOREIGN KEY (model_version) REFERENCES model_versions(version)
            )
        ''')

        # Daily performance snapshots
        c.execute('''
            CREATE TABLE IF NOT EXISTS daily_performance (
                date TEXT,
                model_version TEXT,
                ticker TEXT,
                cumulative_return REAL,
                win_rate REAL,
                trades_count INTEGER,
                PRIMARY KEY (date, model_version, ticker)
            )
        ''')

        # A/B test results
        c.execute('''
            CREATE TABLE IF NOT EXISTS ab_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT,
                model_a TEXT,
                model_b TEXT,
                start_date TEXT,
                end_date TEXT,
                model_a_return REAL,
                model_b_return REAL,
                winner TEXT,
                p_value REAL,
                significant INTEGER
            )
        ''')

        conn.commit()
        conn.close()

    def register_model(self, model: ModelVersion):
        """Register a new model version"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute('''
            INSERT OR REPLACE INTO model_versions
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            model.version,
            model.name,
            model.model_type.value,
            json.dumps(model.parameters),
            model.created_date,
            model.description,
            model.win_rate,
            model.avg_return,
            model.sharpe_ratio,
            model.max_drawdown,
            model.total_trades,
            model.in_sample_win_rate,
            model.out_of_sample_win_rate,
            model.overfitting_ratio
        ))

        conn.commit()
        conn.close()
        print(f"Registered model: {model.version} - {model.name}")

    def record_trade(self, trade: TradeRecord):
        """Record a trade result"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute('''
            INSERT INTO trades
            (ticker, model_version, signal_date, signal_type, entry_price,
             exit_price, exit_date, return_pct, correct, regime, confidence, features)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trade.ticker,
            trade.model_version,
            trade.signal_date,
            trade.signal_type,
            trade.entry_price,
            trade.exit_price,
            trade.exit_date,
            trade.return_pct,
            1 if trade.correct else 0,
            trade.regime,
            trade.confidence,
            json.dumps(trade.features)
        ))

        conn.commit()
        conn.close()

    def get_model_comparison(self) -> pd.DataFrame:
        """Get comparison of all model versions"""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query('''
            SELECT version, name, model_type, win_rate, avg_return,
                   sharpe_ratio, total_trades, overfitting_ratio,
                   out_of_sample_win_rate
            FROM model_versions
            ORDER BY out_of_sample_win_rate DESC
        ''', conn)
        conn.close()
        return df

    def get_improvement_report(self) -> Dict:
        """Generate report showing if we improved over time"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Get all versions ordered by date
        c.execute('''
            SELECT version, name, created_date, out_of_sample_win_rate, avg_return
            FROM model_versions
            ORDER BY created_date
        ''')
        versions = c.fetchall()

        if len(versions) < 2:
            return {"status": "Need at least 2 model versions to compare"}

        report = {
            "versions_tested": len(versions),
            "baseline": {
                "version": versions[0][0],
                "name": versions[0][1],
                "win_rate": versions[0][3],
                "avg_return": versions[0][4]
            },
            "current_best": None,
            "improvement": None,
            "history": []
        }

        best_win_rate = versions[0][3] or 0
        best_version = versions[0]

        for v in versions:
            win_rate = v[3] or 0
            report["history"].append({
                "version": v[0],
                "name": v[1],
                "date": v[2],
                "win_rate": win_rate,
                "avg_return": v[4]
            })
            if win_rate > best_win_rate:
                best_win_rate = win_rate
                best_version = v

        report["current_best"] = {
            "version": best_version[0],
            "name": best_version[1],
            "win_rate": best_version[3],
            "avg_return": best_version[4]
        }

        baseline_wr = report["baseline"]["win_rate"] or 0
        best_wr = report["current_best"]["win_rate"] or 0
        report["improvement"] = {
            "win_rate_change": best_wr - baseline_wr,
            "improved": best_wr > baseline_wr
        }

        conn.close()
        return report


# ============================================================================
# WALK-FORWARD VALIDATION
# ============================================================================

class WalkForwardValidator:
    """
    Implements walk-forward optimization to prevent overfitting.

    Process:
    1. Split data into multiple windows
    2. For each window: train on in-sample, test on out-of-sample
    3. Roll forward and repeat
    4. Aggregate results across all windows

    Key metrics:
    - In-sample vs out-of-sample performance ratio
    - If ratio > 1.5, likely overfitting
    """

    def __init__(self,
                 in_sample_days: int = 180,    # 6 months training
                 out_of_sample_days: int = 30,  # 1 month testing
                 step_days: int = 30):          # Roll forward 1 month
        self.in_sample_days = in_sample_days
        self.out_of_sample_days = out_of_sample_days
        self.step_days = step_days

    def generate_windows(self, data: pd.DataFrame) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """Generate train/test windows for walk-forward analysis"""
        windows = []

        if 'date' not in data.columns:
            data = data.reset_index()
            if 'Date' in data.columns:
                data = data.rename(columns={'Date': 'date'})

        data['date'] = pd.to_datetime(data['date'])
        data = data.sort_values('date')

        start_date = data['date'].min()
        end_date = data['date'].max()

        current_start = start_date

        while True:
            in_sample_end = current_start + timedelta(days=self.in_sample_days)
            out_sample_end = in_sample_end + timedelta(days=self.out_of_sample_days)

            if out_sample_end > end_date:
                break

            in_sample = data[(data['date'] >= current_start) &
                            (data['date'] < in_sample_end)]
            out_sample = data[(data['date'] >= in_sample_end) &
                             (data['date'] < out_sample_end)]

            if len(in_sample) > 20 and len(out_sample) > 5:
                windows.append((in_sample, out_sample))

            current_start += timedelta(days=self.step_days)

        return windows

    def validate(self,
                 model_func,  # Function that takes data, returns signals
                 data: pd.DataFrame,
                 holding_period: int = 7) -> Dict:
        """
        Run walk-forward validation on a model.

        Args:
            model_func: Function(data) -> List[signals]
            data: DataFrame with OHLCV data
            holding_period: Days to hold after signal

        Returns:
            Dict with in-sample, out-of-sample metrics and overfitting ratio
        """
        windows = self.generate_windows(data)

        if not windows:
            return {"error": "Not enough data for walk-forward validation"}

        in_sample_results = []
        out_sample_results = []

        for in_sample, out_sample in windows:
            # Test on in-sample
            is_signals = model_func(in_sample)
            is_returns = self._calculate_returns(in_sample, is_signals, holding_period)
            if is_returns:
                in_sample_results.extend(is_returns)

            # Test on out-of-sample (THE REAL TEST)
            oos_signals = model_func(out_sample)
            oos_returns = self._calculate_returns(out_sample, oos_signals, holding_period)
            if oos_returns:
                out_sample_results.extend(oos_returns)

        # Calculate metrics
        is_win_rate = self._calc_win_rate(in_sample_results)
        oos_win_rate = self._calc_win_rate(out_sample_results)

        # Overfitting ratio: if IS >> OOS, we're overfitting
        if oos_win_rate > 0:
            overfitting_ratio = is_win_rate / oos_win_rate
        else:
            overfitting_ratio = float('inf')

        return {
            "windows_tested": len(windows),
            "in_sample": {
                "trades": len(in_sample_results),
                "win_rate": is_win_rate,
                "avg_return": np.mean([r['return'] for r in in_sample_results]) if in_sample_results else 0
            },
            "out_of_sample": {
                "trades": len(out_sample_results),
                "win_rate": oos_win_rate,
                "avg_return": np.mean([r['return'] for r in out_sample_results]) if out_sample_results else 0
            },
            "overfitting_ratio": overfitting_ratio,
            "overfitting_warning": overfitting_ratio > 1.5,
            "recommendation": self._get_recommendation(overfitting_ratio, oos_win_rate)
        }

    def _calculate_returns(self, data: pd.DataFrame, signals: List[Dict],
                          holding_period: int) -> List[Dict]:
        """Calculate returns for each signal"""
        returns = []
        data = data.reset_index(drop=True)

        for signal in signals:
            if signal.get('signal') != 'BUY':
                continue

            signal_date = signal.get('date')
            if signal_date is None:
                continue

            # Find entry index
            entry_idx = data[data['date'] == signal_date].index
            if len(entry_idx) == 0:
                continue
            entry_idx = entry_idx[0]

            # Find exit index
            exit_idx = min(entry_idx + holding_period, len(data) - 1)

            if exit_idx <= entry_idx:
                continue

            entry_price = data.iloc[entry_idx]['close']
            exit_price = data.iloc[exit_idx]['close']
            ret = ((exit_price - entry_price) / entry_price) * 100

            returns.append({
                'date': signal_date,
                'entry': entry_price,
                'exit': exit_price,
                'return': ret,
                'correct': ret > 0
            })

        return returns

    def _calc_win_rate(self, results: List[Dict]) -> float:
        if not results:
            return 0.0
        wins = sum(1 for r in results if r['correct'])
        return (wins / len(results)) * 100

    def _get_recommendation(self, ratio: float, oos_win_rate: float) -> str:
        if ratio > 2.0:
            return "REJECT: Severe overfitting detected. Model memorized past data."
        elif ratio > 1.5:
            return "CAUTION: Moderate overfitting. Simplify model or add regularization."
        elif oos_win_rate < 55:
            return "WEAK: Out-of-sample performance too low. Need better features."
        elif oos_win_rate >= 70:
            return "STRONG: Good out-of-sample performance. Consider for live trading."
        else:
            return "ACCEPTABLE: Reasonable performance. Monitor in paper trading."


# ============================================================================
# FEATURE ENGINEERING
# ============================================================================

class FeatureEngineer:
    """
    Creates features for ML models based on proven indicators.

    Feature Categories:
    1. Price-based: Returns, momentum, volatility
    2. Technical: RSI, MACD, Bollinger Bands, EMAs
    3. Volume: Volume ratios, OBV
    4. Pattern: Support/resistance, trend
    """

    @staticmethod
    def create_features(data: pd.DataFrame) -> pd.DataFrame:
        """Create all features for ML model"""
        df = data.copy()

        # Ensure we have required columns
        required = ['open', 'high', 'low', 'close', 'volume']
        for col in required:
            if col not in df.columns:
                col_upper = col.capitalize()
                if col_upper in df.columns:
                    df[col] = df[col_upper]

        # Price-based features
        df['return_1d'] = df['close'].pct_change(1) * 100
        df['return_5d'] = df['close'].pct_change(5) * 100
        df['return_20d'] = df['close'].pct_change(20) * 100

        # Volatility
        df['volatility_20d'] = df['return_1d'].rolling(20).std()
        df['atr_14'] = FeatureEngineer._calc_atr(df, 14)

        # RSI variants (key for mean reversion)
        df['rsi_2'] = FeatureEngineer._calc_rsi(df['close'], 2)
        df['rsi_5'] = FeatureEngineer._calc_rsi(df['close'], 5)
        df['rsi_14'] = FeatureEngineer._calc_rsi(df['close'], 14)

        # Moving averages
        df['sma_5'] = df['close'].rolling(5).mean()
        df['sma_20'] = df['close'].rolling(20).mean()
        df['sma_50'] = df['close'].rolling(50).mean()
        df['sma_200'] = df['close'].rolling(200).mean()

        df['ema_9'] = df['close'].ewm(span=9).mean()
        df['ema_21'] = df['close'].ewm(span=21).mean()

        # Price vs MAs
        df['price_vs_sma20'] = ((df['close'] - df['sma_20']) / df['sma_20']) * 100
        df['price_vs_sma50'] = ((df['close'] - df['sma_50']) / df['sma_50']) * 100
        df['price_vs_sma200'] = ((df['close'] - df['sma_200']) / df['sma_200']) * 100

        # Bollinger Bands
        df['bb_middle'] = df['sma_20']
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_middle'] + (2 * df['bb_std'])
        df['bb_lower'] = df['bb_middle'] - (2 * df['bb_std'])
        df['bb_width'] = ((df['bb_upper'] - df['bb_lower']) / df['bb_middle']) * 100
        df['bb_position'] = ((df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])) * 100

        # MACD
        ema_12 = df['close'].ewm(span=12).mean()
        ema_26 = df['close'].ewm(span=26).mean()
        df['macd'] = ema_12 - ema_26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        # Volume features
        df['volume_sma_20'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma_20']

        # Trend features
        df['higher_high'] = (df['high'] > df['high'].shift(1)).astype(int)
        df['higher_low'] = (df['low'] > df['low'].shift(1)).astype(int)
        df['trend_strength'] = df['higher_high'].rolling(5).sum() + df['higher_low'].rolling(5).sum()

        # Consecutive down days (for mean reversion)
        df['down_day'] = (df['close'] < df['close'].shift(1)).astype(int)
        df['consecutive_down'] = df['down_day'].rolling(5).sum()

        # Distance from 20-day high/low
        df['high_20d'] = df['high'].rolling(20).max()
        df['low_20d'] = df['low'].rolling(20).min()
        df['pct_from_high'] = ((df['close'] - df['high_20d']) / df['high_20d']) * 100
        df['pct_from_low'] = ((df['close'] - df['low_20d']) / df['low_20d']) * 100

        return df

    @staticmethod
    def _calc_rsi(prices: pd.Series, period: int) -> pd.Series:
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _calc_atr(df: pd.DataFrame, period: int) -> pd.Series:
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(period).mean()


# ============================================================================
# ENSEMBLE MODEL
# ============================================================================

class EnsembleModel:
    """
    Combines multiple models with weighted voting.

    Based on research:
    - Stacking outperforms individual models
    - Dynamic weighting based on recent performance
    """

    def __init__(self):
        self.models = {}
        self.weights = {}
        self.performance_window = 30  # Days to calculate weights

    def add_model(self, name: str, model_func, initial_weight: float = 1.0):
        """Add a model to the ensemble"""
        self.models[name] = model_func
        self.weights[name] = initial_weight

    def update_weights(self, recent_performance: Dict[str, float]):
        """
        Update model weights based on recent performance.
        Uses softmax to convert win rates to weights.
        """
        total = sum(np.exp(p/10) for p in recent_performance.values())
        for name, perf in recent_performance.items():
            if name in self.weights:
                self.weights[name] = np.exp(perf/10) / total

    def predict(self, data: pd.DataFrame) -> Dict:
        """
        Get ensemble prediction by weighted voting.

        Returns:
            Dict with signal, confidence, and individual model votes
        """
        votes = {}
        weighted_score = 0
        total_weight = 0

        for name, model_func in self.models.items():
            try:
                signal = model_func(data)
                votes[name] = {
                    'signal': signal.get('signal', 'HOLD'),
                    'confidence': signal.get('confidence', 0),
                    'weight': self.weights.get(name, 1.0)
                }

                # Convert signal to numeric: BUY=1, HOLD=0, SELL=-1
                signal_value = {'BUY': 1, 'HOLD': 0, 'SELL': -1}.get(signal.get('signal'), 0)
                weight = self.weights.get(name, 1.0)

                weighted_score += signal_value * weight * signal.get('confidence', 50) / 100
                total_weight += weight

            except Exception as e:
                votes[name] = {'error': str(e)}

        # Determine ensemble signal
        if total_weight > 0:
            final_score = weighted_score / total_weight
        else:
            final_score = 0

        if final_score > 0.3:
            ensemble_signal = 'BUY'
        elif final_score < -0.3:
            ensemble_signal = 'SELL'
        else:
            ensemble_signal = 'HOLD'

        return {
            'signal': ensemble_signal,
            'confidence': abs(final_score) * 100,
            'weighted_score': final_score,
            'individual_votes': votes,
            'model_weights': self.weights.copy()
        }


# ============================================================================
# MAIN FRAMEWORK CLASS
# ============================================================================

class MLTradingFramework:
    """
    Main framework that ties everything together.

    Usage:
    1. Initialize framework
    2. Register baseline model
    3. Run walk-forward validation
    4. Compare with new models
    5. Track improvement over time
    """

    def __init__(self, db_path: str = "ml_performance.db"):
        self.tracker = PerformanceTracker(db_path)
        self.validator = WalkForwardValidator()
        self.feature_engineer = FeatureEngineer()
        self.ensemble = EnsembleModel()
        self.current_version = None

    def register_baseline(self, name: str, model_func, parameters: Dict):
        """Register the baseline model (V1.0)"""
        model = ModelVersion(
            version="V1.0",
            name=name,
            model_type=ModelType.RULE_BASED,
            parameters=parameters,
            created_date=datetime.now().isoformat(),
            description="Baseline model for comparison"
        )
        self.tracker.register_model(model)
        self.current_version = "V1.0"
        self.ensemble.add_model(name, model_func)
        return model

    def test_new_model(self,
                       version: str,
                       name: str,
                       model_func,
                       model_type: ModelType,
                       parameters: Dict,
                       data: pd.DataFrame,
                       description: str = "") -> Dict:
        """
        Test a new model and compare to baseline.

        Returns comparison report with recommendation.
        """
        print(f"\n{'='*60}")
        print(f"Testing Model: {version} - {name}")
        print(f"{'='*60}")

        # Create features
        data_with_features = self.feature_engineer.create_features(data)

        # Run walk-forward validation
        print("\nRunning walk-forward validation...")
        validation = self.validator.validate(model_func, data_with_features)

        if 'error' in validation:
            return validation

        # Create model version record
        model = ModelVersion(
            version=version,
            name=name,
            model_type=model_type,
            parameters=parameters,
            created_date=datetime.now().isoformat(),
            description=description,
            win_rate=validation['out_of_sample']['win_rate'],
            avg_return=validation['out_of_sample']['avg_return'],
            total_trades=validation['out_of_sample']['trades'],
            in_sample_win_rate=validation['in_sample']['win_rate'],
            out_of_sample_win_rate=validation['out_of_sample']['win_rate'],
            overfitting_ratio=validation['overfitting_ratio']
        )

        # Register in tracker
        self.tracker.register_model(model)

        # Get comparison
        comparison = self.tracker.get_model_comparison()
        improvement = self.tracker.get_improvement_report()

        return {
            'model': asdict(model),
            'validation': validation,
            'comparison': comparison.to_dict() if not comparison.empty else {},
            'improvement': improvement
        }

    def get_recommendation(self, ticker: str, data: pd.DataFrame) -> Dict:
        """Get trading recommendation from ensemble"""
        data_with_features = self.feature_engineer.create_features(data)
        return self.ensemble.predict(data_with_features)

    def print_status(self):
        """Print current framework status"""
        print("\n" + "="*60)
        print("ML TRADING FRAMEWORK STATUS")
        print("="*60)

        comparison = self.tracker.get_model_comparison()
        if not comparison.empty:
            print("\nModel Comparison (sorted by OOS win rate):")
            print(comparison.to_string())

        improvement = self.tracker.get_improvement_report()
        if 'improvement' in improvement and improvement['improvement']:
            print(f"\nImprovement from Baseline:")
            print(f"  Win Rate Change: {improvement['improvement']['win_rate_change']:+.1f}%")
            print(f"  Improved: {'YES' if improvement['improvement']['improved'] else 'NO'}")

        print("\n" + "="*60)


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Initialize framework
    framework = MLTradingFramework()

    print("""
    ML Trading Framework Initialized
    ================================

    This framework provides:
    1. Walk-Forward Validation (prevents overfitting)
    2. Performance Tracking (documents every change)
    3. Model Comparison (measures improvement)
    4. Ensemble Predictions (combines multiple models)
    5. Feature Engineering (proven technical indicators)

    Next Steps:
    1. Run: python ml_framework.py --register-baseline
    2. Run: python ml_framework.py --test-model V2.0
    3. Run: python ml_framework.py --compare

    All results are saved to ml_performance.db for tracking.
    """)
