#!/usr/bin/env python3
"""
Backtest V6.0 - High Accuracy Model Backtester with ML Learning

Combines:
1. Alpha Engine V6.0 (High accuracy models)
2. ML Learning Engine (Continuous improvement)
3. Portfolio-specific testing

Target: 80%+ win rate on portfolio stocks
"""

import asyncio
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from alpha_engine_v6 import HighAccuracyModels
from ml_learning_engine import MLLearningEngine


# Configuration
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

TWELVE_DATA_KEY = "116ea8557206482e88c40543cec8128b"
ALPHA_VANTAGE_KEY = "2DYORCDF5694R9MO"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# Portfolio
PORTFOLIO = {
    "VST": {"shares": 7.9038, "avg_entry": 169.58},
    "LLY": {"shares": 1, "avg_entry": 1080.50},
    "MRVL": {"shares": 9, "avg_entry": 86.50}
}


async def fetch_historical_data(ticker: str, days: int = 365) -> Dict:
    """Fetch historical data from API"""

    # Try Twelve Data first
    url = f"https://api.twelvedata.com/time_series?symbol={ticker}&interval=1day&outputsize={days}&apikey={TWELVE_DATA_KEY}"

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())

            if "values" in data:
                values = data["values"]
                values.reverse()

                return {
                    "closes": [float(v["close"]) for v in values],
                    "highs": [float(v["high"]) for v in values],
                    "lows": [float(v["low"]) for v in values],
                    "volumes": [float(v["volume"]) for v in values],
                    "dates": [v["datetime"] for v in values]
                }
    except Exception as e:
        print(f"  Twelve Data failed: {e}")

    # Fallback to Alpha Vantage
    url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={ticker}&apikey={ALPHA_VANTAGE_KEY}&outputsize=full"

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())

            if "Time Series (Daily)" in data:
                ts = data["Time Series (Daily)"]
                dates = sorted(ts.keys())[-days:]

                return {
                    "closes": [float(ts[d]["4. close"]) for d in dates],
                    "highs": [float(ts[d]["2. high"]) for d in dates],
                    "lows": [float(ts[d]["3. low"]) for d in dates],
                    "volumes": [float(ts[d]["5. volume"]) for d in dates],
                    "dates": dates
                }
    except Exception as e:
        print(f"  Alpha Vantage failed: {e}")

    return None


def run_backtest(ticker: str, data: Dict, engine: HighAccuracyModels,
                 forward_days: int = 7) -> Dict:
    """
    Run comprehensive backtest on a single ticker.

    Returns performance metrics for all models.
    """
    closes = data["closes"]
    volumes = data["volumes"]

    if len(closes) < 250:
        return {"error": f"Insufficient data: {len(closes)} days (need 250)"}

    results = {}
    models = engine.get_all_models()

    for model_name, model_func in models.items():
        print(f"    Testing {model_name}...")

        signals = []
        min_lookback = 200

        for i in range(min_lookback, len(closes) - forward_days):
            hist_closes = closes[:i+1]
            hist_volumes = volumes[:i+1]

            entry_price = closes[i]
            exit_price = closes[min(i + forward_days, len(closes) - 1)]
            forward_return = ((exit_price - entry_price) / entry_price) * 100

            # Get signal
            signal, strength, indicators = model_func(hist_closes, hist_volumes)

            if signal in ["BUY", "SELL"]:
                correct = (signal == "BUY" and forward_return > 0) or \
                          (signal == "SELL" and forward_return < 0)

                signals.append({
                    "date": data["dates"][i] if i < len(data.get("dates", [])) else f"day_{i}",
                    "signal": signal,
                    "strength": strength,
                    "return": round(forward_return, 2),
                    "correct": correct
                })

        if not signals:
            results[model_name] = {
                "win_rate": 0,
                "total_signals": 0,
                "avg_return": 0,
                "status": "NO_SIGNALS"
            }
            continue

        # Calculate metrics
        total = len(signals)
        wins = sum(1 for s in signals if s["correct"])
        buys = [s for s in signals if s["signal"] == "BUY"]
        buy_wins = sum(1 for s in buys if s["correct"])

        win_rate = round(wins / total * 100, 1) if total > 0 else 0
        buy_win_rate = round(buy_wins / len(buys) * 100, 1) if buys else 0
        avg_return = round(sum(s["return"] for s in buys) / len(buys), 2) if buys else 0

        results[model_name] = {
            "win_rate": win_rate,
            "buy_win_rate": buy_win_rate,
            "total_signals": total,
            "buy_signals": len(buys),
            "avg_return": avg_return,
            "recent_signals": signals[-5:],
            "status": "OK"
        }

    # Find best model
    valid = {k: v for k, v in results.items()
             if v.get("total_signals", 0) >= 5 and v.get("status") == "OK"}

    if valid:
        best = max(valid.items(), key=lambda x: x[1]["win_rate"])
        results["_best_model"] = {
            "name": best[0],
            "win_rate": best[1]["win_rate"],
            "signals": best[1]["total_signals"]
        }
    else:
        results["_best_model"] = {"name": "None", "win_rate": 0, "signals": 0}

    return results


async def main():
    """Run comprehensive backtest on portfolio stocks"""

    print("=" * 70)
    print("BACKTEST V6.0 - High Accuracy Model Testing")
    print("Target: 80%+ Win Rate")
    print("=" * 70)
    print(f"\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    engine = HighAccuracyModels()
    ml_engine = MLLearningEngine()

    all_results = {}

    # Try to load cached data first
    cached_file = DATA_DIR / "historical_backtest.json"
    cached_data = {}
    if cached_file.exists():
        with open(cached_file, "r") as f:
            cached_data = json.load(f)
        print(f"Loaded cached data for {list(cached_data.keys())}")

    # Fetch and test each ticker
    for ticker in PORTFOLIO.keys():
        print(f"\n{'='*50}")
        print(f"TESTING: {ticker}")
        print(f"{'='*50}")

        # Use cached data if available
        if ticker in cached_data:
            print(f"  Using cached historical data...")
            data = cached_data[ticker]
        else:
            # Fetch data
            print(f"  Fetching historical data...")
            data = await fetch_historical_data(ticker, days=400)

        if not data:
            print(f"  ERROR: Could not fetch data for {ticker}")
            continue

        print(f"  Got {len(data['closes'])} days of data")

        # Run backtest
        print(f"  Running backtests...")
        results = run_backtest(ticker, data, engine)

        all_results[ticker] = results

        # Print results
        print(f"\n  RESULTS FOR {ticker}:")
        print(f"  {'-'*40}")

        for model_name, metrics in sorted(results.items(), key=lambda x: x[1].get("win_rate", 0) if isinstance(x[1], dict) else 0, reverse=True):
            if model_name.startswith("_"):
                continue

            if isinstance(metrics, dict) and "win_rate" in metrics:
                status = "TARGET MET" if metrics["win_rate"] >= 80 else ""
                print(f"  {model_name}:")
                print(f"    Win Rate: {metrics['win_rate']}% {status}")
                print(f"    Buy Win Rate: {metrics.get('buy_win_rate', 0)}%")
                print(f"    Signals: {metrics['total_signals']} ({metrics.get('buy_signals', 0)} buys)")
                print(f"    Avg Return: {metrics.get('avg_return', 0)}%")

        if "_best_model" in results:
            best = results["_best_model"]
            print(f"\n  BEST MODEL: {best['name']}")
            print(f"  WIN RATE: {best['win_rate']}%")

        await asyncio.sleep(1)  # Rate limiting

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY - BEST MODELS PER TICKER")
    print("=" * 70)

    target_met = []
    target_missed = []

    for ticker, results in all_results.items():
        if "_best_model" in results:
            best = results["_best_model"]
            if best["win_rate"] >= 80:
                target_met.append((ticker, best["name"], best["win_rate"]))
                status = "TARGET MET"
            else:
                target_missed.append((ticker, best["name"], best["win_rate"]))
                status = "NEEDS IMPROVEMENT"

            print(f"\n{ticker}: {best['name']}")
            print(f"  Win Rate: {best['win_rate']}% - {status}")

    print("\n" + "=" * 70)
    print("TARGET ACHIEVEMENT")
    print("=" * 70)
    print(f"\nTargets Met (>=80%): {len(target_met)}/{len(all_results)}")
    for ticker, model, rate in target_met:
        print(f"  {ticker}: {model} ({rate}%)")

    if target_missed:
        print(f"\nNeeds Improvement (<80%): {len(target_missed)}")
        for ticker, model, rate in target_missed:
            print(f"  {ticker}: {model} ({rate}%)")

    # Run ML learning cycle
    print("\n" + "=" * 70)
    print("ML LEARNING CYCLE")
    print("=" * 70)

    # Aggregate model performances
    model_perfs = {}
    for ticker, results in all_results.items():
        for model_name, metrics in results.items():
            if model_name.startswith("_") or not isinstance(metrics, dict):
                continue
            if model_name not in model_perfs:
                model_perfs[model_name] = {"win_rates": [], "signals": 0}
            if "win_rate" in metrics:
                model_perfs[model_name]["win_rates"].append(metrics["win_rate"])
                model_perfs[model_name]["signals"] += metrics.get("total_signals", 0)

    # Average performance per model
    avg_perfs = {}
    for model, data in model_perfs.items():
        if data["win_rates"]:
            avg_perfs[model] = {
                "win_rate": round(sum(data["win_rates"]) / len(data["win_rates"]), 1),
                "signals": data["signals"]
            }

    learning_result = ml_engine.run_learning_cycle(avg_perfs)

    print("\nEnsemble Weights (Updated):")
    for model, weight in sorted(learning_result["new_ensemble_weights"].items(), key=lambda x: -x[1]):
        print(f"  {model}: {weight:.3f}")

    # Save results
    output = {
        "test_date": datetime.now().isoformat(),
        "target": "80% win rate",
        "results": all_results,
        "learning_summary": learning_result["learning_summary"],
        "ensemble_weights": learning_result["new_ensemble_weights"]
    }

    output_file = DATA_DIR / "backtest_v6_results.json"
    with open(output_file, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\nResults saved to: {output_file}")

    # Get current signals
    print("\n" + "=" * 70)
    print("CURRENT SIGNALS (Using Best Models)")
    print("=" * 70)

    for ticker, results in all_results.items():
        if "_best_model" not in results:
            continue

        best_model_name = results["_best_model"]["name"]
        accuracy = results["_best_model"]["win_rate"]

        # Fetch fresh data for current signal
        data = await fetch_historical_data(ticker, days=250)
        if not data:
            continue

        closes = data["closes"]
        volumes = data["volumes"]

        # Get signal from best model
        signal_result = engine.get_signal(closes, volumes, best_model_name)

        print(f"\n{ticker}:")
        print(f"  Model: {best_model_name} ({accuracy}% accuracy)")
        print(f"  Signal: {signal_result.signal}")
        print(f"  Strength: {signal_result.strength}%")
        if signal_result.signal == "BUY":
            print(f"  Entry: ${signal_result.entry_price}")
            print(f"  Stop: ${signal_result.stop_loss}")
            print(f"  Target: ${signal_result.target}")
        print(f"  Indicators: {signal_result.indicators}")


if __name__ == "__main__":
    asyncio.run(main())
