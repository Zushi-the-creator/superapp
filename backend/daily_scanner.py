#!/usr/bin/env python3
"""
Daily Stock Scanner
Discovers trending stocks and runs hybrid model to find opportunities

Usage:
    python daily_scanner.py              # Full scan
    python daily_scanner.py --quick      # Quick scan (top 20 only)
    python daily_scanner.py --portfolio  # Scan only portfolio stocks
"""

import asyncio
import urllib.request
import json
import math
import os
import re
import argparse
from datetime import datetime
from pathlib import Path

# Configuration
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

TWELVE_DATA_KEY = os.environ.get("TWELVEDATA_API_KEY", "116ea8557206482e88c40543cec8128b")
ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "2DYORCDF5694R9MO")

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# Your portfolio
PORTFOLIO = {
    "VST": {"shares": 7.9038, "avg_entry": 169.58},
    "LLY": {"shares": 1, "avg_entry": 1080.50},
    "MRVL": {"shares": 9, "avg_entry": 86.50}
}


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def calc_ema(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def calc_sma(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    return sum(closes[-period:]) / period


def calc_bollinger(closes, period=20):
    if len(closes) < period:
        return closes[-1], closes[-1], closes[-1]
    middle = sum(closes[-period:]) / period
    variance = sum((x - middle) ** 2 for x in closes[-period:]) / period
    std = math.sqrt(variance) if variance > 0 else 0
    return middle + 2*std, middle, middle - 2*std


# ============================================================
# PREDICTION MODELS
# ============================================================

def model_v1_rsi_ema(closes, volumes):
    """V1.0 RSI/EMA - Classic technical analysis"""
    if len(closes) < 30:
        return "HOLD", 0
    rsi = calc_rsi(closes)
    ema9 = calc_ema(closes, 9)
    ema21 = calc_ema(closes, 21)
    signal, strength = "HOLD", 0
    if rsi < 30:
        signal, strength = "BUY", 40
    elif rsi > 70:
        signal, strength = "SELL", 40
    if ema9 > ema21:
        if signal != "SELL":
            signal = "BUY"
        strength += 30
    elif ema9 < ema21:
        if signal != "BUY":
            signal = "SELL"
        strength += 30
    return signal, min(strength, 100)


def model_v8_mean_reversion(closes, volumes):
    """V8.0 Mean Reversion - Buy extremes"""
    if len(closes) < 30:
        return "HOLD", 0
    price = closes[-1]
    upper, middle, lower = calc_bollinger(closes, 20)
    rsi = calc_rsi(closes)
    if price < lower and rsi < 30:
        return "BUY", 80
    elif price < lower or rsi < 35:
        return "BUY", 60
    elif price > upper and rsi > 70:
        return "SELL", 80
    elif price > upper or rsi > 65:
        return "SELL", 60
    return "HOLD", 0


def model_v11_buy_dip(closes, volumes):
    """V11.0 Buy The Dip - Buy pullbacks in uptrends"""
    if len(closes) < 50:
        return "HOLD", 0
    price = closes[-1]
    recent_high = max(closes[-20:])
    pullback = (recent_high - price) / recent_high * 100
    rsi = calc_rsi(closes)
    sma50 = calc_sma(closes, 50)
    uptrend = price > sma50 * 0.95

    if pullback >= 8 and pullback <= 15 and rsi < 40 and uptrend:
        return "BUY", 85
    elif pullback >= 5 and pullback <= 12 and rsi < 45 and uptrend:
        return "BUY", 70
    elif pullback >= 3 and rsi < 40:
        return "BUY", 55
    elif pullback < 1 and rsi > 70:
        return "SELL", 70
    elif rsi > 75:
        return "SELL", 60
    return "HOLD", 0


def model_v12_support_resistance(closes, volumes):
    """V12.0 Support/Resistance - Trade key levels"""
    if len(closes) < 60:
        return "HOLD", 0
    price = closes[-1]
    recent = closes[-60:]

    pivots_high, pivots_low = [], []
    for i in range(5, len(recent) - 5):
        if recent[i] == max(recent[i-5:i+6]):
            pivots_high.append(recent[i])
        if recent[i] == min(recent[i-5:i+6]):
            pivots_low.append(recent[i])

    if not pivots_high or not pivots_low:
        return "HOLD", 0

    support = max([p for p in pivots_low if p < price], default=price * 0.95)
    resistance = min([p for p in pivots_high if p > price], default=price * 1.05)

    dist_support = (price - support) / price * 100
    dist_resistance = (resistance - price) / price * 100
    rsi = calc_rsi(closes)

    if dist_support < 2 and rsi < 45:
        return "BUY", 75
    elif dist_support < 3 and rsi < 40:
        return "BUY", 60
    elif dist_resistance < 2 and rsi > 55:
        return "SELL", 75
    elif dist_resistance < 3 and rsi > 60:
        return "SELL", 60
    return "HOLD", 0


MODELS = {
    "V1.0 RSI/EMA": model_v1_rsi_ema,
    "V8.0 Mean Rev": model_v8_mean_reversion,
    "V11.0 Buy Dip": model_v11_buy_dip,
    "V12.0 Support": model_v12_support_resistance,
}


# ============================================================
# DATA FETCHING
# ============================================================

async def fetch_twelve_data(ticker, days=100):
    """Fetch from Twelve Data API"""
    url = f"https://api.twelvedata.com/time_series?symbol={ticker}&interval=1day&outputsize={days}&apikey={TWELVE_DATA_KEY}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            if "values" not in data:
                return None
            values = data["values"]
            values.reverse()
            return {
                "closes": [float(v["close"]) for v in values],
                "volumes": [float(v["volume"]) for v in values]
            }
    except Exception as e:
        return None


async def fetch_alpha_vantage(ticker):
    """Fetch from Alpha Vantage API"""
    url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={ticker}&apikey={ALPHA_VANTAGE_KEY}&outputsize=compact"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            if "Time Series (Daily)" not in data:
                return None
            ts = data["Time Series (Daily)"]
            dates = sorted(ts.keys())
            return {
                "closes": [float(ts[d]["4. close"]) for d in dates],
                "volumes": [float(ts[d]["5. volume"]) for d in dates]
            }
    except:
        return None


# ============================================================
# STOCK DISCOVERY
# ============================================================

def discover_yahoo_movers():
    """Fetch trending stocks from Yahoo Finance"""
    results = {"most_active": [], "gainers": [], "losers": []}

    urls = {
        "most_active": "https://finance.yahoo.com/most-active",
        "gainers": "https://finance.yahoo.com/gainers",
        "losers": "https://finance.yahoo.com/losers"
    }

    for category, url in urls.items():
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8')
                tickers = re.findall(r'data-symbol="([A-Z]{1,5})"', html)
                unique = list(dict.fromkeys(tickers))[:25]
                results[category] = unique
        except:
            pass

    return results


def discover_finviz_oversold():
    """Fetch oversold stocks from Finviz (RSI < 30)"""
    url = "https://finviz.com/screener.ashx?v=111&f=sh_avgvol_o500,ta_rsi_os30&ft=4"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8')
            tickers = re.findall(r'class="screener-link-primary"[^>]*>([A-Z]{1,5})</a>', html)
            return list(dict.fromkeys(tickers))[:30]
    except:
        return []


# ============================================================
# BACKTESTING & ANALYSIS
# ============================================================

def backtest_model(model_func, closes, volumes):
    """Backtest a model on historical data"""
    results = []
    for i in range(50, len(closes) - 7):
        hist_closes = closes[:i+1]
        hist_volumes = volumes[:i+1] if volumes else []
        entry = closes[i]
        exit_7d = closes[min(i+7, len(closes)-1)]
        return_7d = ((exit_7d - entry) / entry) * 100

        signal, _ = model_func(hist_closes, hist_volumes)

        if signal == "BUY":
            correct = return_7d > 0
        elif signal == "SELL":
            correct = return_7d < 0
        else:
            correct = abs(return_7d) < 5

        results.append({"signal": signal, "correct": correct, "return": return_7d})

    buys = [r for r in results if r["signal"] == "BUY"]
    directional = [r for r in results if r["signal"] in ["BUY", "SELL"]]

    win_rate = sum(1 for r in directional if r["correct"]) / len(directional) * 100 if directional else 50
    avg_return = sum(r["return"] for r in buys) / len(buys) if buys else 0

    return {
        "win_rate": round(win_rate, 1),
        "signals": len(directional),
        "avg_return": round(avg_return, 2)
    }


def analyze_stock(ticker, data):
    """Full analysis with all models"""
    closes = data["closes"]
    volumes = data["volumes"]

    # Backtest all models
    model_results = {}
    for name, func in MODELS.items():
        try:
            model_results[name] = backtest_model(func, closes, volumes)
        except:
            model_results[name] = {"win_rate": 50, "signals": 0, "avg_return": 0}

    # Find best model
    valid = {k: v for k, v in model_results.items() if v["signals"] >= 5}
    if not valid:
        return None

    best_model = max(valid, key=lambda x: valid[x]["win_rate"])
    best_stats = valid[best_model]

    # Get current signal from best model
    signal, strength = MODELS[best_model](closes, volumes)

    # Calculate indicators
    price = closes[-1]
    rsi = calc_rsi(closes)
    high_20d = max(closes[-20:]) if len(closes) >= 20 else price
    pullback = (high_20d - price) / high_20d * 100
    change_5d = ((closes[-1] - closes[-5]) / closes[-5] * 100) if len(closes) >= 5 else 0

    return {
        "ticker": ticker,
        "price": round(price, 2),
        "rsi": round(rsi, 1),
        "pullback": round(pullback, 1),
        "change_5d": round(change_5d, 1),
        "best_model": best_model,
        "accuracy": best_stats["win_rate"],
        "signal": signal,
        "strength": strength,
        "avg_return": best_stats["avg_return"],
        "all_models": model_results
    }


# ============================================================
# MAIN SCANNER
# ============================================================

async def run_scan(mode="full"):
    """
    Run the daily scan

    Modes:
        full: Discover + scan all (~50-100 stocks)
        quick: Top 20 most promising only
        portfolio: Only portfolio stocks
    """

    print("=" * 70)
    print(f"🔍 DAILY STOCK SCANNER - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    tickers_to_scan = []

    if mode == "portfolio":
        tickers_to_scan = list(PORTFOLIO.keys())
        print(f"\n📊 Scanning portfolio: {tickers_to_scan}")
    else:
        # Discover trending stocks
        print("\n📡 Discovering trending stocks...")

        yahoo = discover_yahoo_movers()
        print(f"   Yahoo Most Active: {len(yahoo.get('most_active', []))}")
        print(f"   Yahoo Gainers: {len(yahoo.get('gainers', []))}")
        print(f"   Yahoo Losers: {len(yahoo.get('losers', []))}")

        finviz_oversold = discover_finviz_oversold()
        print(f"   Finviz Oversold: {len(finviz_oversold)}")

        # Priority order: Oversold first (best for our models)
        seen = set()

        # Add portfolio first
        for t in PORTFOLIO.keys():
            if t not in seen:
                tickers_to_scan.append(t)
                seen.add(t)

        # Add oversold
        for t in finviz_oversold:
            if t not in seen:
                tickers_to_scan.append(t)
                seen.add(t)

        # Add losers (potential bounce)
        for t in yahoo.get("losers", []):
            if t not in seen:
                tickers_to_scan.append(t)
                seen.add(t)

        # Add most active
        for t in yahoo.get("most_active", []):
            if t not in seen:
                tickers_to_scan.append(t)
                seen.add(t)

        if mode == "quick":
            tickers_to_scan = tickers_to_scan[:20]
        else:
            tickers_to_scan = tickers_to_scan[:50]

        print(f"\n📊 Scanning {len(tickers_to_scan)} stocks...")

    # Scan each ticker
    opportunities = []
    sell_signals = []
    hold_signals = []

    for i, ticker in enumerate(tickers_to_scan):
        # Try Twelve Data first, then Alpha Vantage
        data = await fetch_twelve_data(ticker)
        if not data or len(data["closes"]) < 50:
            await asyncio.sleep(0.5)
            data = await fetch_alpha_vantage(ticker)

        if not data or len(data["closes"]) < 50:
            print(f"   [{i+1}/{len(tickers_to_scan)}] {ticker}: ❌ No data")
            await asyncio.sleep(0.5)
            continue

        result = analyze_stock(ticker, data)

        if not result:
            print(f"   [{i+1}/{len(tickers_to_scan)}] {ticker}: ❌ Analysis failed")
            await asyncio.sleep(0.5)
            continue

        # Categorize by signal
        if result["signal"] == "BUY" and result["accuracy"] >= 55:
            opportunities.append(result)
            print(f"   [{i+1}/{len(tickers_to_scan)}] {ticker}: ✅ BUY ({result['best_model']}: {result['accuracy']}%)")
        elif result["signal"] == "SELL":
            sell_signals.append(result)
            print(f"   [{i+1}/{len(tickers_to_scan)}] {ticker}: 🔴 SELL ({result['accuracy']}%)")
        else:
            hold_signals.append(result)
            print(f"   [{i+1}/{len(tickers_to_scan)}] {ticker}: 🟡 HOLD (RSI: {result['rsi']})")

        await asyncio.sleep(0.5)  # Rate limiting

    # Sort opportunities by accuracy
    opportunities.sort(key=lambda x: x["accuracy"], reverse=True)

    # Print results
    print("\n" + "=" * 70)
    print("🏆 TOP BUY OPPORTUNITIES")
    print("=" * 70)

    if opportunities:
        print(f"\n{'Rank':<5} {'Ticker':<8} {'Price':<10} {'Model':<15} {'Accuracy':<10} {'RSI':<6} {'Pullback'}")
        print("-" * 70)
        for i, opp in enumerate(opportunities[:10], 1):
            print(f"{i:<5} {opp['ticker']:<8} ${opp['price']:<9} {opp['best_model']:<15} {opp['accuracy']:<10}% {opp['rsi']:<6} {opp['pullback']:.1f}%")
    else:
        print("\n   No high-confidence BUY signals found today.")

    # Portfolio status
    print("\n" + "=" * 70)
    print("📊 PORTFOLIO STATUS")
    print("=" * 70)

    for ticker, pos in PORTFOLIO.items():
        # Find in results
        result = next((r for r in opportunities + sell_signals + hold_signals if r["ticker"] == ticker), None)
        if result:
            pnl = (result["price"] - pos["avg_entry"]) * pos["shares"]
            pnl_pct = (result["price"] - pos["avg_entry"]) / pos["avg_entry"] * 100
            sig_emoji = "✅" if result["signal"] == "BUY" else "🔴" if result["signal"] == "SELL" else "🟡"
            print(f"\n   {ticker}: {sig_emoji} {result['signal']} | ${result['price']} | P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)")
            print(f"      Model: {result['best_model']} ({result['accuracy']}% accuracy)")

    # Save results
    results = {
        "scan_time": datetime.now().isoformat(),
        "opportunities": opportunities,
        "sell_signals": sell_signals,
        "hold_signals": hold_signals
    }

    with open(DATA_DIR / "daily_scan_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n📁 Results saved to {DATA_DIR / 'daily_scan_results.json'}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Daily Stock Scanner")
    parser.add_argument("--quick", action="store_true", help="Quick scan (top 20 only)")
    parser.add_argument("--portfolio", action="store_true", help="Scan only portfolio stocks")
    args = parser.parse_args()

    if args.portfolio:
        mode = "portfolio"
    elif args.quick:
        mode = "quick"
    else:
        mode = "full"

    asyncio.run(run_scan(mode))


if __name__ == "__main__":
    main()
