#!/usr/bin/env python3
"""Fetch analyst data, sentiment, and live quotes asynchronously."""

import asyncio
import aiohttp
import feedparser
from bs4 import BeautifulSoup
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

FINNHUB_TOKEN = "d5ed7a9r01qjckl3djkgd5ed7a9r01qjckl3djl0"
ANALYST_TICKERS = ["TER", "GD"]
QUOTE_TICKERS = ["COHR", "ALB", "GOOGL", "BE", "LRCX"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


async def fetch_finviz_analyst(session, ticker):
    """Scrape Finviz snapshot-table2 for Price, Target Price, Recom."""
    url = f"https://finviz.com/quote.ashx?t={ticker}"
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return {"ticker": ticker, "error": f"HTTP {resp.status}"}
            html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_="snapshot-table2")
        if not table:
            return {"ticker": ticker, "error": "snapshot-table2 not found"}

        cells = table.find_all("td")
        data = {}
        for i in range(0, len(cells) - 1, 2):
            key = cells[i].get_text(strip=True)
            val = cells[i + 1].get_text(strip=True)
            data[key] = val

        return {
            "ticker": ticker,
            "price": data.get("Price", "N/A"),
            "target_price": data.get("Target Price", "N/A"),
            "recommendation": data.get("Recom", "N/A"),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


async def fetch_google_news_sentiment(session, ticker):
    """Fetch top 5 Google News RSS titles and run VADER sentiment."""
    url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
    analyzer = SentimentIntensityAnalyzer()
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return {"ticker": ticker, "error": f"HTTP {resp.status}"}
            text = await resp.text()

        feed = feedparser.parse(text)
        entries = feed.entries[:5]
        results = []
        total_compound = 0.0
        for entry in entries:
            title = entry.get("title", "")
            scores = analyzer.polarity_scores(title)
            results.append({"title": title, "compound": scores["compound"]})
            total_compound += scores["compound"]

        avg_compound = total_compound / len(results) if results else 0.0
        if avg_compound >= 0.05:
            overall = "POSITIVE"
        elif avg_compound <= -0.05:
            overall = "NEGATIVE"
        else:
            overall = "NEUTRAL"

        return {
            "ticker": ticker,
            "articles": results,
            "avg_compound": round(avg_compound, 4),
            "overall_sentiment": overall,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


async def fetch_finnhub_quote(session, ticker):
    """Fetch live quote from Finnhub."""
    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_TOKEN}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return {"ticker": ticker, "error": f"HTTP {resp.status}"}
            data = await resp.json()
            pc = data.get("pc", 0)
            c = data.get("c", 0)
            change = round(c - pc, 2)
            change_pct = round(((c - pc) / pc) * 100, 2) if pc else None
            return {
                "ticker": ticker,
                "current_price": c,
                "open": data.get("o"),
                "high": data.get("h"),
                "low": data.get("l"),
                "prev_close": pc,
                "change": change,
                "change_pct": change_pct,
            }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


async def main():
    async with aiohttp.ClientSession() as session:
        analyst_tasks = [fetch_finviz_analyst(session, t) for t in ANALYST_TICKERS]
        sentiment_tasks = [fetch_google_news_sentiment(session, t) for t in ANALYST_TICKERS]
        quote_tasks = [fetch_finnhub_quote(session, t) for t in QUOTE_TICKERS]

        all_results = await asyncio.gather(
            *analyst_tasks, *sentiment_tasks, *quote_tasks,
            return_exceptions=True
        )

    n_a = len(ANALYST_TICKERS)
    n_s = len(ANALYST_TICKERS)

    analyst_results = all_results[:n_a]
    sentiment_results = all_results[n_a:n_a + n_s]
    quote_results = all_results[n_a + n_s:]

    print("=" * 70)
    print("FINVIZ ANALYST DATA")
    print("=" * 70)
    for r in analyst_results:
        if isinstance(r, Exception):
            print(f"  ERROR: {r}")
            continue
        if "error" in r:
            print(f"  {r['ticker']}: ERROR - {r['error']}")
        else:
            print(f"  {r['ticker']}:")
            print(f"    Price:          {r['price']}")
            print(f"    Target Price:   {r['target_price']}")
            print(f"    Recommendation: {r['recommendation']}")
        print()

    print("=" * 70)
    print("GOOGLE NEWS SENTIMENT (VADER)")
    print("=" * 70)
    for r in sentiment_results:
        if isinstance(r, Exception):
            print(f"  ERROR: {r}")
            continue
        if "error" in r:
            print(f"  {r['ticker']}: ERROR - {r['error']}")
        else:
            print(f"  {r['ticker']} - Overall: {r['overall_sentiment']} (avg compound: {r['avg_compound']})")
            for i, art in enumerate(r["articles"], 1):
                print(f"    {i}. [{art['compound']:+.4f}] {art['title']}")
        print()

    print("=" * 70)
    print("FINNHUB LIVE QUOTES")
    print("=" * 70)
    hdr = f"  {'Ticker':<8} {'Price':>10} {'Open':>10} {'High':>10} {'Low':>10} {'PrevCl':>10} {'Chg':>8} {'Chg%':>8}"
    print(hdr)
    print("  " + "-" * 76)
    for r in quote_results:
        if isinstance(r, Exception):
            print(f"  ERROR: {r}")
            continue
        if "error" in r:
            print(f"  {r['ticker']:<8} ERROR - {r['error']}")
        else:
            print(
                f"  {r['ticker']:<8} "
                f"{r['current_price']:>10.2f} "
                f"{r['open']:>10.2f} "
                f"{r['high']:>10.2f} "
                f"{r['low']:>10.2f} "
                f"{r['prev_close']:>10.2f} "
                f"{r['change']:>+8.2f} "
                f"{r['change_pct']:>+7.2f}%"
            )
    print()


if __name__ == "__main__":
    asyncio.run(main())
