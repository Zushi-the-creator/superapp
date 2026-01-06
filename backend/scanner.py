"""
15-Second Rotational Stock Scanner
Scans top NASDAQ stocks in batches, prioritizing high-volume "hot" stocks
"""

import asyncio
import yfinance as yf
import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import json
from pathlib import Path
from signals import SignalEngine
from sentiment import SentimentEngine


class NASDAQScanner:
    """
    Intelligent stock scanner with rotation strategy
    - Scans top 2000 NASDAQ stocks
    - Prioritizes high-volume stocks for 15s refresh
    - Calculates technical signals + sentiment
    """

    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        self.signal_engine = SignalEngine()
        self.sentiment_engine = SentimentEngine()

        # Scanner state
        self.scan_results = {}
        self.hot_tickers = set()  # High-volume stocks to prioritize
        self.all_tickers = []
        self.scan_batch_size = 50
        self.hot_batch_size = 20

        # Metadata
        self.last_full_scan = None
        self.last_hot_scan = None
        self.scan_count = 0

        # Load NASDAQ tickers
        self._load_nasdaq_tickers()

    def _load_nasdaq_tickers(self):
        """Load NASDAQ tickers from a predefined list"""
        # Top NASDAQ-100 tickers (free, no API needed)
        # In production, you'd fetch this from a CSV or API
        top_nasdaq = [
            # Mega caps
            "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "COST", "NFLX",
            # Large caps
            "ASML", "AMD", "PEP", "ADBE", "CSCO", "TMUS", "CMCSA", "INTC", "TXN", "QCOM",
            "INTU", "AMGN", "HON", "AMAT", "SBUX", "BKNG", "ISRG", "PANW", "ADP", "GILD",
            # Growth stocks
            "ADI", "VRTX", "REGN", "LRCX", "MDLZ", "KLAC", "SNPS", "CDNS", "MELI", "MAR",
            "PYPL", "ABNB", "CRWD", "FTNT", "WDAY", "DASH", "TEAM", "DDOG", "SNOW", "ZS",
            # Mid/Small caps with volume
            "MRVL", "ORLY", "ADSK", "NXPI", "MNST", "CTAS", "PAYX", "ROST", "FAST", "ODFL",
            "CPRT", "PCAR", "CEG", "EXC", "KDP", "EA", "DXCM", "IDXX", "BIIB", "MRNA",
            "ILMN", "KHC", "CSGP", "GEHC", "DLTR", "MCHP", "CHTR", "ANSS", "ON", "WBD",
            # High-volume traders
            "RIVN", "LCID", "NIO", "PLUG", "COIN", "HOOD", "SOFI", "PLTR", "RBLX", "U",
            "DKNG", "UBER", "LYFT", "ZM", "DOCU", "ROKU", "SQ", "SHOP", "PINS", "SNAP"
        ]

        self.all_tickers = top_nasdaq
        print(f"Loaded {len(self.all_tickers)} NASDAQ tickers")

    async def scan_ticker(self, ticker: str) -> Optional[Dict]:
        """
        Scan a single ticker and generate comprehensive analysis

        Returns:
            Dict with ticker data, signals, and sentiment
        """
        try:
            # Download data with proper configuration
            stock = yf.Ticker(ticker)

            # Try with shorter period first (more reliable)
            df = stock.history(period="30d", interval="1d")

            # Fallback: try with different parameters
            if df.empty:
                df = stock.history(period="1mo", interval="1d")

            if df.empty or len(df) < 20:  # Reduced minimum from 30 to 20
                print(f"Insufficient data for {ticker}: {len(df)} days")
                return None

            # Get current quote data
            try:
                info = stock.info
            except:
                # Fallback if info fails
                info = {"shortName": ticker, "sector": "Unknown"}

            current_price = df['Close'].iloc[-1]
            prev_close = df['Close'].iloc[-2] if len(df) > 1 else current_price
            price_change = current_price - prev_close
            price_change_pct = (price_change / prev_close) * 100

            # Calculate technical signals
            signals = self.signal_engine.generate_signals(df)

            # Get sentiment (async)
            sentiment = await self.sentiment_engine.get_ticker_sentiment(ticker)

            # Calculate combined score (Technical 60% + Sentiment 40%)
            tech_score = signals["strength"] / 100.0
            sent_score = (sentiment["sentiment_score"] + 1) / 2  # Normalize -1 to 1 -> 0 to 1
            combined_score = (tech_score * 0.6) + (sent_score * 0.4)

            # Determine if "hot" (high volume)
            current_volume = df['Volume'].iloc[-1]
            avg_volume = df['Volume'].mean()
            is_hot = current_volume > (avg_volume * 1.5)

            result = {
                "ticker": ticker,
                "name": info.get("shortName", ticker),
                "sector": info.get("sector", "Unknown"),
                "price": round(current_price, 2),
                "change": round(price_change, 2),
                "change_pct": round(price_change_pct, 2),
                "volume": int(current_volume),
                "avg_volume": int(avg_volume),
                "volume_ratio": round(current_volume / avg_volume, 2),
                "market_cap": info.get("marketCap", 0),
                "is_hot": is_hot,

                # Technical signals
                "signal": signals["signal"],
                "signal_strength": signals["strength"],
                "rsi": signals["rsi"],
                "ema_fast": signals["ema_fast"],
                "ema_slow": signals["ema_slow"],

                # Sentiment
                "sentiment_score": sentiment["sentiment_score"],
                "sentiment_label": sentiment["sentiment_label"],
                "article_count": sentiment["article_count"],

                # Combined
                "combined_score": round(combined_score * 100, 2),
                "reasons": signals["reasons"],

                # Metadata
                "last_updated": datetime.now().isoformat()
            }

            # Update hot tickers set
            if is_hot:
                self.hot_tickers.add(ticker)

            return result

        except Exception as e:
            print(f"Error scanning {ticker}: {e}")
            return None

    async def scan_batch(self, tickers: List[str]) -> List[Dict]:
        """Scan a batch of tickers with rate limit handling"""
        results = []

        # Process in smaller sub-batches to avoid rate limiting
        sub_batch_size = 10
        for i in range(0, len(tickers), sub_batch_size):
            sub_batch = tickers[i:i + sub_batch_size]
            tasks = [self.scan_ticker(ticker) for ticker in sub_batch]
            batch_results = await asyncio.gather(*tasks)
            results.extend([r for r in batch_results if r is not None])

            # Small delay between sub-batches
            if i + sub_batch_size < len(tickers):
                await asyncio.sleep(1)

        return results

    async def full_scan(self):
        """
        Perform a full scan of all tickers in batches
        This runs less frequently (every 5-10 minutes)
        """
        print(f"Starting full scan of {len(self.all_tickers)} tickers...")
        all_results = []

        # Scan in batches to avoid rate limiting
        for i in range(0, len(self.all_tickers), self.scan_batch_size):
            batch = self.all_tickers[i:i + self.scan_batch_size]
            batch_results = await self.scan_batch(batch)
            all_results.extend(batch_results)

            print(f"Scanned batch {i // self.scan_batch_size + 1}: {len(batch_results)} stocks")

            # Small delay to avoid rate limiting
            await asyncio.sleep(2)

        # Update scan results
        for result in all_results:
            self.scan_results[result["ticker"]] = result

        self.last_full_scan = datetime.now()
        self.scan_count += 1

        print(f"Full scan complete: {len(all_results)} stocks scanned")
        self._save_results()

        return all_results

    async def hot_scan(self):
        """
        Quick scan of "hot" stocks (high volume)
        This runs every 15 seconds
        """
        if not self.hot_tickers:
            # If no hot stocks yet, scan a quick batch
            hot_batch = self.all_tickers[:self.hot_batch_size]
        else:
            hot_batch = list(self.hot_tickers)[:self.hot_batch_size]

        print(f"Hot scan: scanning {len(hot_batch)} high-volume stocks...")
        results = await self.scan_batch(hot_batch)

        # Update scan results
        for result in results:
            self.scan_results[result["ticker"]] = result

        self.last_hot_scan = datetime.now()

        return results

    def get_top_signals(self, signal_type: str = None, limit: int = 20) -> List[Dict]:
        """
        Get top stocks by signal strength

        Args:
            signal_type: Filter by "BUY", "SELL", or None for all
            limit: Number of results

        Returns:
            List of top stocks sorted by combined score
        """
        results = list(self.scan_results.values())

        if signal_type:
            results = [r for r in results if r["signal"] == signal_type]

        # Sort by combined score
        results.sort(key=lambda x: x["combined_score"], reverse=True)

        return results[:limit]

    def get_most_volatile(self, limit: int = 20) -> List[Dict]:
        """Get stocks with highest price volatility"""
        results = list(self.scan_results.values())
        results.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        return results[:limit]

    def get_volume_leaders(self, limit: int = 20) -> List[Dict]:
        """Get stocks with highest volume ratio"""
        results = list(self.scan_results.values())
        results.sort(key=lambda x: x["volume_ratio"], reverse=True)
        return results[:limit]

    def get_by_ticker(self, ticker: str) -> Optional[Dict]:
        """Get cached data for a specific ticker"""
        return self.scan_results.get(ticker.upper())

    def get_scanner_stats(self) -> Dict:
        """Get scanner statistics"""
        return {
            "total_tickers": len(self.all_tickers),
            "scanned_tickers": len(self.scan_results),
            "hot_tickers": len(self.hot_tickers),
            "last_full_scan": self.last_full_scan.isoformat() if self.last_full_scan else None,
            "last_hot_scan": self.last_hot_scan.isoformat() if self.last_hot_scan else None,
            "scan_count": self.scan_count
        }

    def _save_results(self):
        """Save scan results to disk (for persistence)"""
        try:
            output_file = self.data_dir / "scan_results.json"
            with open(output_file, 'w') as f:
                json.dump({
                    "results": list(self.scan_results.values()),
                    "metadata": self.get_scanner_stats()
                }, f, indent=2)
        except Exception as e:
            print(f"Error saving results: {e}")


# Background scanner task
async def run_scanner_loop(scanner: NASDAQScanner):
    """
    Main scanner loop:
    - Full scan every 10 minutes
    - Hot scan every 15 seconds
    """
    print("Starting scanner loop...")

    # Initial full scan
    await scanner.full_scan()

    full_scan_interval = 600  # 10 minutes
    hot_scan_interval = 15    # 15 seconds

    last_full_scan_time = datetime.now()

    while True:
        try:
            # Check if we need a full scan
            if (datetime.now() - last_full_scan_time).seconds >= full_scan_interval:
                await scanner.full_scan()
                last_full_scan_time = datetime.now()
            else:
                # Otherwise, do a hot scan
                await scanner.hot_scan()

            # Wait 15 seconds before next scan
            await asyncio.sleep(hot_scan_interval)

        except Exception as e:
            print(f"Error in scanner loop: {e}")
            await asyncio.sleep(5)  # Wait a bit before retrying
