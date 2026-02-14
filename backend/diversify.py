from hybrid_model import HybridModelSelector

stocks = {
    "NVDA": {"sector": "Tech/AI", "price": 185.81, "closes": [155,158,162,165,168,172,175,178,175,172,168,165,168,172,175,178,182,178,175,172,175,178,182,185,182,179,176,179,183,186,183,180,177,180,184,188,185,181,178,182,185.81]},
    "COST": {"sector": "Consumer", "price": 924.88, "closes": [880,885,890,895,900,905,910,905,900,895,900,905,910,915,920,915,910,905,910,915,920,925,920,915,910,915,920,925,930,925,920,915,920,925,920,915,910,915,920,924.88]},
    "BSX": {"sector": "Healthcare", "price": 97.63, "closes": [88,89,90,91,92,93,94,93,92,91,92,93,94,95,96,95,94,93,94,95,96,97,96,95,94,95,96,97,98,97,96,95,96,97,96,95,94,95,96,97.63]},
    "JPM": {"sector": "Finance", "price": 222.50, "closes": [195,198,201,204,207,210,207,204,201,204,207,210,213,210,207,204,207,210,213,216,213,210,207,210,213,216,219,216,213,210,213,216,219,222,219,216,213,216,219,222.5]},
}

s = HybridModelSelector()
print("DIVERSIFIED SCAN - Different Sectors")
print("="*55)
buys = []
for t, d in stocks.items():
    vols = [10000000] * len(d["closes"])
    sig = s.get_signal(t, d["closes"], vols)
    rsi = sig.indicators.get("RSI", 0)
    print(f"{t:5} | {d['sector']:12} | ${d['price']:>7.2f} | RSI:{rsi:>5.1f} | {sig.signal}")
    if sig.signal == "BUY":
        buys.append({"t": t, "sector": d["sector"], "price": d["price"], "rsi": rsi})

print("\n" + "="*55)
print("BUY SIGNALS FOR DIVERSIFICATION:")
for b in buys:
    print(f"  {b['t']} ({b['sector']}) @ ${b['price']}")
