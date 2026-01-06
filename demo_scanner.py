#!/usr/bin/env python3
"""
NASDAQ Super App - Simplified Demo
Demonstrates scanner functionality without external dependencies
"""

import json
import random
from datetime import datetime
from typing import Dict, List


class SimplifiedScanner:
    """Simplified scanner for demonstration"""

    def __init__(self):
        self.tickers = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
            "AVGO", "COST", "NFLX", "AMD", "INTC", "QCOM", "CSCO"
        ]

    def calculate_rsi(self, closes: List[float], period: int = 14) -> float:
        """Calculate RSI indicator"""
        if len(closes) < period + 1:
            return 50.0

        gains = []
        losses = []

        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate EMA"""
        if not prices or len(prices) < period:
            return prices[-1] if prices else 0

        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period

        for price in prices[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))

        return ema

    def generate_sample_data(self, ticker: str) -> Dict:
        """Generate sample stock data for demo"""
        # Simulate price data
        base_price = random.uniform(50, 800)
        prices = []

        for i in range(30):
            change = random.uniform(-0.05, 0.05)
            if i == 0:
                prices.append(base_price)
            else:
                prices.append(prices[-1] * (1 + change))

        current_price = prices[-1]
        prev_price = prices[-2]
        change = current_price - prev_price
        change_pct = (change / prev_price) * 100

        # Calculate indicators
        rsi = self.calculate_rsi(prices)
        ema_fast = self.calculate_ema(prices, 9)
        ema_slow = self.calculate_ema(prices, 21)

        # Volume simulation
        base_volume = random.randint(1000000, 50000000)
        volume_ratio = random.uniform(0.5, 3.0)

        # Sentiment simulation
        sentiment_score = random.uniform(-0.5, 0.5)
        sentiment_label = "POSITIVE" if sentiment_score > 0.05 else "NEGATIVE" if sentiment_score < -0.05 else "NEUTRAL"

        # Generate signal
        signal = "HOLD"
        signal_strength = 0
        reasons = []

        if rsi < 30:
            signal = "BUY"
            signal_strength += 40
            reasons.append(f"RSI Oversold ({rsi:.1f})")
        elif rsi > 70:
            signal = "SELL"
            signal_strength += 40
            reasons.append(f"RSI Overbought ({rsi:.1f})")

        if ema_fast > ema_slow:
            if signal != "SELL":
                signal = "BUY"
            signal_strength += 30
            reasons.append("EMA Bullish Crossover")
        elif ema_fast < ema_slow:
            if signal != "BUY":
                signal = "SELL"
            signal_strength += 30
            reasons.append("EMA Bearish Crossover")

        if volume_ratio > 2.0:
            signal_strength += 30
            reasons.append(f"Volume Spike ({volume_ratio:.1f}x avg)")

        if abs(change_pct) > 2:
            reasons.append(f"Strong momentum ({change_pct:+.2f}%)")
            signal_strength += 20

        # Combined score (60% technical + 40% sentiment)
        tech_score = min(signal_strength, 100) / 100.0
        sent_score = (sentiment_score + 1) / 2
        combined_score = (tech_score * 0.6) + (sent_score * 0.4)

        return {
            "ticker": ticker,
            "name": f"{ticker} Inc.",
            "sector": random.choice(["Technology", "Healthcare", "Finance", "Consumer"]),
            "price": round(current_price, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "volume": base_volume,
            "volume_ratio": round(volume_ratio, 2),
            "signal": signal,
            "signal_strength": round(min(signal_strength, 100), 2),
            "rsi": round(rsi, 2),
            "ema_fast": round(ema_fast, 2),
            "ema_slow": round(ema_slow, 2),
            "sentiment_score": round(sentiment_score, 3),
            "sentiment_label": sentiment_label,
            "combined_score": round(combined_score * 100, 2),
            "reasons": reasons,
            "is_hot": volume_ratio > 1.5,
            "last_updated": datetime.now().isoformat()
        }

    def scan_all(self) -> List[Dict]:
        """Scan all tickers"""
        results = []
        for ticker in self.tickers:
            data = self.generate_sample_data(ticker)
            results.append(data)
        return results

    def get_top_signals(self, results: List[Dict], signal_type: str = None, limit: int = 5) -> List[Dict]:
        """Get top signals"""
        filtered = results
        if signal_type:
            filtered = [r for r in results if r["signal"] == signal_type]

        sorted_results = sorted(filtered, key=lambda x: x["combined_score"], reverse=True)
        return sorted_results[:limit]

    def display_results(self, results: List[Dict]):
        """Display results in a nice format"""
        print("\n" + "="*100)
        print(f"{'TICKER':<8} {'PRICE':<10} {'CHANGE':<10} {'SIGNAL':<8} {'STRENGTH':<10} {'RSI':<8} {'SENTIMENT':<12} {'SCORE':<8}")
        print("="*100)

        for r in results:
            price_str = f"${r['price']:.2f}"
            change_str = f"{r['change_pct']:+.2f}%"
            signal_color = "🟢" if r['signal'] == "BUY" else "🔴" if r['signal'] == "SELL" else "⚪"

            print(f"{r['ticker']:<8} {price_str:<10} {change_str:<10} {signal_color} {r['signal']:<6} {r['signal_strength']:<10.1f} {r['rsi']:<8.1f} {r['sentiment_label']:<12} {r['combined_score']:<8.1f}")

        print("="*100)

    def display_detail(self, stock: Dict):
        """Display detailed analysis"""
        print("\n" + "="*80)
        print(f"  {stock['ticker']} - {stock['name']}")
        print("="*80)
        print(f"  Sector: {stock['sector']}")
        print(f"  Price: ${stock['price']:.2f} ({stock['change_pct']:+.2f}%)")
        print()
        print(f"  Signal: {stock['signal']} (Strength: {stock['signal_strength']:.1f}%)")
        print()
        print("  Technical Indicators:")
        print(f"    • RSI (14): {stock['rsi']:.2f}")
        print(f"    • EMA Fast (9): ${stock['ema_fast']:.2f}")
        print(f"    • EMA Slow (21): ${stock['ema_slow']:.2f}")
        print(f"    • Volume Ratio: {stock['volume_ratio']:.2f}x")
        print()
        print("  Sentiment Analysis:")
        print(f"    • Score: {stock['sentiment_score']:+.3f}")
        print(f"    • Label: {stock['sentiment_label']}")
        print()
        print(f"  Combined Score: {stock['combined_score']:.1f}/100")
        print()
        print("  Reasoning:")
        for i, reason in enumerate(stock['reasons'], 1):
            print(f"    {i}. {reason}")
        print("="*80)


def main():
    """Main demo"""
    print("\n🚀 NASDAQ SUPER APP - DEMO MODE")
    print("="*100)
    print("This is a simplified demo running without external dependencies")
    print("In production, this uses real data from yfinance + AI analysis")
    print("="*100)

    # Create scanner
    scanner = SimplifiedScanner()

    # Perform scan
    print("\n📊 Scanning stocks...")
    results = scanner.scan_all()
    print(f"✅ Scanned {len(results)} stocks\n")

    # Show all results
    print("\n📈 ALL STOCKS")
    scanner.display_results(results)

    # Show top buy signals
    print("\n\n🟢 TOP BUY SIGNALS")
    top_buys = scanner.get_top_signals(results, "BUY", 5)
    scanner.display_results(top_buys)

    # Show top sell signals
    print("\n\n🔴 TOP SELL SIGNALS")
    top_sells = scanner.get_top_signals(results, "SELL", 5)
    scanner.display_results(top_sells)

    # Show detailed analysis for top stock
    if top_buys:
        print("\n\n💡 DETAILED ANALYSIS - TOP BUY")
        scanner.display_detail(top_buys[0])

    # Export to JSON
    output_file = "/home/user/superapp/demo_output.json"
    with open(output_file, 'w') as f:
        json.dump({
            "scan_time": datetime.now().isoformat(),
            "total_stocks": len(results),
            "results": results,
            "top_buys": top_buys,
            "top_sells": top_sells
        }, f, indent=2)

    print(f"\n💾 Results saved to: {output_file}")

    print("\n" + "="*100)
    print("✅ DEMO COMPLETE!")
    print()
    print("📝 To run the full version with real data:")
    print("   1. Install Docker")
    print("   2. Run: ./start.sh")
    print("   3. Open: http://localhost:3000")
    print("="*100 + "\n")


if __name__ == "__main__":
    main()
