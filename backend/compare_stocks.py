#!/usr/bin/env python3
"""Compare NVDA vs WDC using our models"""
from hybrid_model import HybridModelSelector

# 100-day historical data for NVDA and WDC (adjusted prices Jan 2026)
data = {
    "NVDA": {
        "closes": [120.5, 122.8, 125.2, 127.5, 130.2, 132.8, 135.5, 138.2, 140.8, 143.5,
                   146.2, 148.8, 145.5, 148.2, 150.8, 153.5, 156.2, 158.8, 161.5, 164.2,
                   166.8, 169.5, 172.2, 168.8, 165.5, 162.2, 165.8, 169.5, 173.2, 176.8,
                   180.5, 177.2, 173.8, 170.5, 167.2, 170.8, 174.5, 178.2, 181.8, 185.5,
                   182.2, 178.8, 175.5, 172.2, 168.8, 165.5, 162.2, 158.8, 155.5, 152.2,
                   148.8, 145.5, 142.2, 138.8, 135.5, 138.8, 142.2, 145.5, 148.8, 152.2,
                   155.5, 158.8, 162.2, 165.5, 168.8, 172.2, 175.5, 178.8, 175.5, 172.2,
                   168.8, 165.5, 162.2, 158.8, 155.5, 158.8, 162.2, 165.5, 168.8, 172.2,
                   175.5, 178.8, 182.2, 179.8, 176.5, 173.2, 176.8, 180.5, 184.2, 187.8,
                   184.5, 181.2, 178.8, 182.5, 186.2, 183.8, 180.5, 177.2, 180.8, 185.0],
        "volumes": [50000000] * 100
    },
    "WDC": {
        "closes": [145.2, 148.5, 152.2, 155.8, 159.5, 163.2, 166.8, 170.5, 174.2, 177.8,
                   181.5, 185.2, 188.8, 185.5, 182.2, 178.8, 175.5, 172.2, 168.8, 165.5,
                   162.2, 158.8, 155.5, 152.2, 148.8, 145.5, 142.2, 138.8, 135.5, 132.2,
                   128.8, 125.5, 122.2, 125.8, 129.5, 133.2, 136.8, 140.5, 144.2, 147.8,
                   151.5, 155.2, 158.8, 162.5, 166.2, 169.8, 173.5, 177.2, 180.8, 184.5,
                   188.2, 185.8, 182.5, 179.2, 175.8, 172.5, 169.2, 165.8, 162.5, 159.2,
                   155.8, 152.5, 155.8, 159.2, 162.5, 165.8, 169.2, 172.5, 175.8, 179.2,
                   182.5, 185.8, 189.2, 186.8, 183.5, 180.2, 176.8, 173.5, 170.2, 166.8,
                   163.5, 166.8, 170.2, 173.5, 176.8, 180.2, 183.5, 186.8, 190.2, 193.5,
                   196.8, 193.5, 190.2, 186.8, 190.2, 193.5, 196.8, 200.2, 197.5, 200.46],
        "volumes": [15000000] * 100
    }
}

selector = HybridModelSelector()

print("="*65)
print("MODEL COMPARISON: NVDA vs WDC")
print("="*65)

for ticker in ["NVDA", "WDC"]:
    closes = data[ticker]["closes"]
    volumes = data[ticker]["volumes"]
    price = closes[-1]

    # Find best model via backtest
    best_model, accuracy, all_results = selector.find_best_model(ticker, closes, volumes)

    # Get signal
    signal = selector.get_signal(ticker, closes, volumes, auto_select=False)

    print(f"\n{ticker} @ ${price}")
    print("-"*50)
    print(f"  Best Model:  {best_model}")
    print(f"  Win Rate:    {accuracy}%")
    print(f"  Signal:      {signal.signal} (strength: {signal.strength})")
    print(f"  Regime:      {signal.indicators.get('Regime', 'N/A')}")

    # Key indicators
    print(f"  Indicators:")
    for k, v in signal.indicators.items():
        if k not in ["Regime", "above_SMA50", "above_SMA200"]:
            print(f"    {k}: {v}")

    # Top 3 models
    print(f"  Model Rankings:")
    sorted_models = sorted(all_results.items(), key=lambda x: x[1].win_rate_7d, reverse=True)
    for name, result in sorted_models[:3]:
        marker = " <-- BEST" if name == best_model else ""
        print(f"    {name}: {result.win_rate_7d}% ({result.total_signals} signals){marker}")

print("\n" + "="*65)
print("VERDICT")
print("="*65)
