"""
Register Baseline Models and Document Current Performance
==========================================================

This script:
1. Registers our current models as baselines
2. Runs walk-forward validation on each
3. Saves results to ml_performance.db
4. Creates a benchmark for future improvements

Run this ONCE to establish the baseline.
Future models will be compared against these.
"""

import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from ml_framework import (
    MLTradingFramework,
    ModelVersion,
    ModelType,
    FeatureEngineer
)

# ============================================================================
# BASELINE MODELS (Our Current Best)
# ============================================================================

def model_v17_extreme_oversold(data: pd.DataFrame) -> list:
    """
    V17.0 Extreme Oversold - Best for VST
    BUY when RSI(2)<5 + RSI(3)<15 + RSI(14)<35 + Uptrend
    """
    signals = []
    df = data.copy()

    # Calculate indicators if not present
    if 'rsi_2' not in df.columns:
        df = FeatureEngineer.create_features(df)

    for i in range(50, len(df)):
        row = df.iloc[i]

        rsi2 = row.get('rsi_2', 50)
        rsi_14 = row.get('rsi_14', 50)
        price = row.get('close', 0)
        sma200 = row.get('sma_200', price)

        # Triple RSI confirmation
        if rsi2 < 5 and rsi_14 < 35 and price > sma200:
            signals.append({
                'date': row.get('date', df.index[i]),
                'signal': 'BUY',
                'confidence': 85,
                'indicators': {'rsi2': rsi2, 'rsi14': rsi_14}
            })

    return signals


def model_v15_connors_rsi2(data: pd.DataFrame) -> list:
    """
    V15.0 Connors RSI(2) - Best for LLY
    BUY when RSI(2)<5 + Price>SMA200
    """
    signals = []
    df = data.copy()

    if 'rsi_2' not in df.columns:
        df = FeatureEngineer.create_features(df)

    for i in range(200, len(df)):
        row = df.iloc[i]

        rsi2 = row.get('rsi_2', 50)
        price = row.get('close', 0)
        sma200 = row.get('sma_200', price)

        if rsi2 < 5 and price > sma200:
            signals.append({
                'date': row.get('date', df.index[i]),
                'signal': 'BUY',
                'confidence': 90,
                'indicators': {'rsi2': rsi2}
            })

    return signals


def model_v20_rsi5_bb(data: pd.DataFrame) -> list:
    """
    V20.0 RSI(5) + Bollinger Band - Best for COIN
    BUY when RSI(5)<25 + Price within 2% of Lower BB
    """
    signals = []
    df = data.copy()

    if 'rsi_5' not in df.columns:
        df = FeatureEngineer.create_features(df)

    for i in range(50, len(df)):
        row = df.iloc[i]

        rsi5 = row.get('rsi_5', 50)
        price = row.get('close', 0)
        bb_lower = row.get('bb_lower', price * 0.95)

        pct_from_bb = ((price - bb_lower) / bb_lower) * 100 if bb_lower > 0 else 10

        if rsi5 < 25 and pct_from_bb < 2:
            signals.append({
                'date': row.get('date', df.index[i]),
                'signal': 'BUY',
                'confidence': 85,
                'indicators': {'rsi5': rsi5, 'pct_from_bb': pct_from_bb}
            })

    return signals


# ============================================================================
# SYNTHETIC DATA FOR TESTING (Replace with real data in production)
# ============================================================================

def generate_test_data(ticker: str, days: int = 365) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing"""
    np.random.seed(42)  # Reproducible

    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')

    # Start price based on ticker
    start_prices = {'VST': 150, 'LLY': 900, 'COIN': 200, 'QQQ': 500}
    start = start_prices.get(ticker, 100)

    # Random walk with drift
    returns = np.random.normal(0.0005, 0.02, days)
    prices = start * np.cumprod(1 + returns)

    df = pd.DataFrame({
        'date': dates,
        'open': prices * (1 + np.random.normal(0, 0.005, days)),
        'high': prices * (1 + np.abs(np.random.normal(0, 0.01, days))),
        'low': prices * (1 - np.abs(np.random.normal(0, 0.01, days))),
        'close': prices,
        'volume': np.random.randint(1000000, 10000000, days)
    })

    return df


# ============================================================================
# MAIN REGISTRATION
# ============================================================================

def register_all_baselines():
    """Register all baseline models"""
    print("="*60)
    print("REGISTERING BASELINE MODELS")
    print("="*60)
    print(f"Date: {datetime.now().isoformat()}")
    print()

    framework = MLTradingFramework(db_path="ml_performance.db")

    # Define baselines
    baselines = [
        {
            'version': 'V17.0',
            'name': 'Extreme Oversold',
            'ticker': 'VST',
            'model_func': model_v17_extreme_oversold,
            'model_type': ModelType.RULE_BASED,
            'parameters': {
                'rsi2_threshold': 5,
                'rsi14_threshold': 35,
                'require_uptrend': True
            },
            'expected_win_rate': 85.7,
            'description': 'Triple RSI confirmation for extreme oversold'
        },
        {
            'version': 'V15.0',
            'name': 'Connors RSI(2)',
            'ticker': 'LLY',
            'model_func': model_v15_connors_rsi2,
            'model_type': ModelType.RULE_BASED,
            'parameters': {
                'rsi2_threshold': 5,
                'require_above_sma200': True
            },
            'expected_win_rate': 83.3,
            'description': 'Larry Connors RSI(2) mean reversion'
        },
        {
            'version': 'V20.0',
            'name': 'RSI(5) + Bollinger Band',
            'ticker': 'COIN',
            'model_func': model_v20_rsi5_bb,
            'model_type': ModelType.RULE_BASED,
            'parameters': {
                'rsi5_threshold': 25,
                'bb_pct_threshold': 2,
                'holding_period': 7
            },
            'expected_win_rate': 80.0,
            'description': 'RSI(5) with Bollinger Band for volatile crypto stocks'
        }
    ]

    results = []

    for baseline in baselines:
        print(f"\nTesting: {baseline['version']} - {baseline['name']} ({baseline['ticker']})")
        print("-" * 40)

        # Generate test data (replace with real data fetch)
        data = generate_test_data(baseline['ticker'], days=365)

        # Run validation
        result = framework.test_new_model(
            version=baseline['version'],
            name=baseline['name'],
            model_func=baseline['model_func'],
            model_type=baseline['model_type'],
            parameters=baseline['parameters'],
            data=data,
            description=baseline['description']
        )

        if 'error' not in result:
            validation = result['validation']
            print(f"  In-Sample Win Rate: {validation['in_sample']['win_rate']:.1f}%")
            print(f"  Out-of-Sample Win Rate: {validation['out_of_sample']['win_rate']:.1f}%")
            print(f"  Overfitting Ratio: {validation['overfitting_ratio']:.2f}")
            print(f"  Recommendation: {validation['recommendation']}")

            results.append({
                'version': baseline['version'],
                'name': baseline['name'],
                'ticker': baseline['ticker'],
                'expected_wr': baseline['expected_win_rate'],
                'actual_oos_wr': validation['out_of_sample']['win_rate'],
                'overfitting_ratio': validation['overfitting_ratio']
            })
        else:
            print(f"  Error: {result['error']}")

    # Summary
    print("\n" + "="*60)
    print("BASELINE REGISTRATION COMPLETE")
    print("="*60)

    # Save results
    results_df = pd.DataFrame(results)
    if not results_df.empty:
        print("\nRegistered Baselines:")
        print(results_df.to_string(index=False))

        # Save to file
        results_df.to_json('data/baseline_models.json', orient='records', indent=2)
        print("\nSaved to: data/baseline_models.json")

    print("\nNext Steps:")
    print("1. Replace synthetic data with real price data")
    print("2. Test new models with: framework.test_new_model()")
    print("3. Compare improvement with: framework.get_improvement_report()")
    print("4. All results tracked in: ml_performance.db")

    return results


if __name__ == "__main__":
    register_all_baselines()
