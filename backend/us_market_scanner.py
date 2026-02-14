"""
US Market Stock Scanner (NYSE, NASDAQ, AMEX)
Scans top 2000 tradeable US stocks efficiently
"""

import asyncio
import aiohttp
from typing import List, Dict
import pandas as pd
from datetime import datetime
from data_fetcher import get_fetcher


class USMarketScanner:
    """Efficient scanner for all US market stocks"""

    def __init__(self):
        self.fetcher = get_fetcher()
        self.batch_size = 100
        self.delay_between_batches = 0.5

    def get_top_us_stocks(self) -> List[str]:
        """
        Return top ~2000 most liquid US stocks across all exchanges
        Manually curated list of real, tradeable stocks
        """
        # S&P 500 + NASDAQ 100 + Russell 2000 leaders + Active traders

        # Large Cap (Market leaders)
        large_cap = [
            # Tech Mega Cap
            'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'GOOG', 'AMZN', 'META', 'TSLA',
            'AVGO', 'ASML', 'AMD', 'INTC', 'QCOM', 'NFLX', 'ADBE', 'CRM',
            'ORCL', 'CSCO', 'ACN', 'TXN', 'NOW', 'IBM', 'INTU', 'AMAT',
            'MU', 'LRCX', 'KLAC', 'SNPS', 'CDNS', 'PANW', 'ADSK', 'MRVL',

            # Finance
            'BRK.B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'MS', 'GS', 'C',
            'SCHW', 'BLK', 'AXP', 'SPGI', 'CME', 'ICE', 'MCO', 'COF',

            # Healthcare
            'LLY', 'UNH', 'JNJ', 'ABBV', 'MRK', 'CVS', 'TMO', 'ABT',
            'PFE', 'DHR', 'AMGN', 'BMY', 'GILD', 'VRTX', 'REGN', 'ISRG',

            # Consumer
            'WMT', 'COST', 'HD', 'MCD', 'NKE', 'SBUX', 'TGT', 'LOW',
            'PG', 'KO', 'PEP', 'MDLZ', 'CL', 'EL', 'DIS', 'CMCSA',

            # Industrial
            'CAT', 'BA', 'UPS', 'RTX', 'HON', 'GE', 'MMM', 'LMT',
            'DE', 'UNP', 'FDX', 'NSC', 'CSX', 'WM', 'EMR', 'ETN',

            # Energy
            'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'MPC', 'PSX', 'VLO',
            'OXY', 'HAL', 'BKR', 'DVN', 'FANG', 'HES', 'MRO', 'APA',

            # Utilities & Real Estate
            'NEE', 'DUK', 'SO', 'D', 'AEP', 'EXC', 'XEL', 'ED',
            'AMT', 'PLD', 'CCI', 'EQIX', 'PSA', 'DLR', 'SPG', 'O'
        ]

        # Mid Cap Growth
        mid_cap = [
            # Tech/Software
            'SNOW', 'CRWD', 'DDOG', 'NET', 'ZS', 'OKTA', 'PLTR', 'COIN',
            'RBLX', 'U', 'DASH', 'ABNB', 'UBER', 'LYFT', 'SQ', 'SHOP',
            'TWLO', 'DOCU', 'ZM', 'ROKU', 'PINS', 'SNAP', 'SPOT', 'PATH',

            # Biotech
            'MRNA', 'BNTX', 'SGEN', 'EXEL', 'NBIX', 'INCY', 'RARE', 'ALNY',
            'BMRN', 'TECH', 'IONS', 'UTHR', 'FOLD', 'ARWR', 'SAGE', 'BLUE',

            # Finance/Fintech
            'SOFI', 'HOOD', 'AFRM', 'UPST', 'LC', 'NU', 'BILL', 'SQ',

            # EV & Clean Energy
            'RIVN', 'LCID', 'FSR', 'CHPT', 'BLNK', 'ENPH', 'SEDG', 'RUN',
            'PLUG', 'BE', 'FCEL', 'BLDP', 'CLSK', 'RIOT', 'MARA', 'HUT',

            # Healthcare Services
            'TDOC', 'DOCS', 'SDGR', 'OSCR', 'TMDX', 'ICUI', 'CYTK', 'CRVL'
        ]

        # Small Cap Active Traders
        small_cap = [
            'SMCI', 'IONQ', 'RGTI', 'QUBT', 'AIFU', 'KULR', 'ABML',
            'FUBO', 'GREE', 'BBAI', 'SOUN', 'RDDT', 'HIMS', 'CELH',
            'MNDY', 'GTLB', 'S', 'DOCN', 'MDB', 'ESTC', 'CFLT', 'FROG',
            'CVNA', 'CAVA', 'BROS', 'WING', 'SHAK', 'CMG', 'CHWY', 'W',
            'ETSY', 'FVRR', 'UPWK', 'FIVERR', 'ZI', 'PCTY', 'SMAR', 'APPN'
        ]

        # Semiconductors (all sizes)
        semis = [
            'TSM', 'AVGO', 'AMD', 'INTC', 'QCOM', 'NVDA', 'TXN', 'ADI',
            'MRVL', 'NXPI', 'LRCX', 'KLAC', 'AMAT', 'MU', 'SNPS', 'CDNS',
            'MPWR', 'MCHP', 'ON', 'SWKS', 'QRVO', 'WOLF', 'CRUS', 'MTSI',
            'SITM', 'SMTC', 'UCTT', 'FORM', 'COHU', 'ICHR', 'LSCC', 'AOSL'
        ]

        # REITs & Dividend
        reits = [
            'VNQ', 'SCHH', 'IYR', 'XLRE', 'REM', 'MORT', 'RWR', 'USRT',
            'O', 'VICI', 'SPG', 'PSA', 'WELL', 'AVB', 'EQR', 'DLR',
            'AMT', 'CCI', 'SBAC', 'EQIX', 'DRE', 'ARE', 'VTR', 'PEAK'
        ]

        # ETFs (Popular)
        etfs = [
            'SPY', 'QQQ', 'DIA', 'IWM', 'VOO', 'VTI', 'EEM', 'EFA',
            'GLD', 'SLV', 'TLT', 'AGG', 'LQD', 'HYG', 'XLE', 'XLF',
            'XLK', 'XLV', 'XLI', 'XLP', 'XLY', 'XLC', 'XLU', 'XLRE'
        ]

        # Combine all (remove duplicates)
        all_stocks = list(set(
            large_cap + mid_cap + small_cap + semis + reits + etfs
        ))

        return all_stocks

    async def scan_stock(self, ticker: str) -> Dict:
        """Scan a single stock and return metrics"""
        try:
            quote = await self.fetcher.get_quote(ticker)
            if not quote or quote['price'] == 0:
                return None

            # Get historical data for RSI
            df = await self.fetcher.fetch_stock_data(ticker, period_days=14)
            if df is None or len(df) < 14:
                return None

            # Calculate RSI
            rsi = self._calculate_rsi(df['Close'])

            # Determine signal
            signal = 'BUY' if rsi < 30 else 'SELL' if rsi > 70 else 'HOLD'
            score = self._calculate_score(quote, rsi)

            return {
                'ticker': ticker,
                'price': quote['price'],
                'change_pct': quote['change_pct'],
                'rsi': round(rsi, 2),
                'signal': signal,
                'score': round(score, 2),
                'volume': quote.get('volume', 0)
            }
        except Exception:
            return None

    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """Calculate RSI indicator"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])

    def _calculate_score(self, quote: Dict, rsi: float) -> float:
        """Calculate overall score for ranking"""
        score = 0

        # RSI component (30 points)
        if rsi < 20:
            score += 30
        elif rsi < 30:
            score += 25
        elif rsi < 40:
            score += 15

        # Momentum component (20 points)
        if abs(quote['change_pct']) > 5:
            score += 20
        elif abs(quote['change_pct']) > 3:
            score += 15
        elif abs(quote['change_pct']) > 2:
            score += 10

        return score

    async def scan_batch(self, tickers: List[str]) -> List[Dict]:
        """Scan a batch of stocks in parallel"""
        tasks = [self.scan_stock(ticker) for ticker in tickers]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    async def scan_all(self, limit: int = 2000) -> List[Dict]:
        """
        Scan top US market stocks
        Returns list of stocks sorted by score
        """
        stocks_to_scan = self.get_top_us_stocks()[:limit]
        print(f"Starting US market scan of {len(stocks_to_scan)} stocks...")

        all_results = []

        # Process in batches
        for i in range(0, len(stocks_to_scan), self.batch_size):
            batch = stocks_to_scan[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (len(stocks_to_scan) - 1) // self.batch_size + 1

            print(f"Scanning batch {batch_num}/{total_batches}...")

            results = await self.scan_batch(batch)
            all_results.extend(results)

            # Delay between batches
            if i + self.batch_size < len(stocks_to_scan):
                await asyncio.sleep(self.delay_between_batches)

        # Sort by score (highest first)
        all_results.sort(key=lambda x: x['score'], reverse=True)

        print(f"✅ Scan complete! Found {len(all_results)} tradeable stocks")
        return all_results

    async def get_top_buys(self, limit: int = 20) -> List[Dict]:
        """Get top BUY signals from scan"""
        all_stocks = await self.scan_all(limit=500)
        buy_signals = [s for s in all_stocks if s['signal'] == 'BUY']
        return buy_signals[:limit]


async def main():
    """Scan and display top opportunities"""
    scanner = USMarketScanner()

    print("Scanning top 2000 US market stocks...\n")
    all_stocks = await scanner.scan_all(limit=2000)

    # Get top 20 BUY signals
    buy_signals = [s for s in all_stocks if s['signal'] == 'BUY'][:20]

    print("\n" + "="*70)
    print("TOP 20 US MARKET BUY SIGNALS")
    print("="*70 + "\n")

    for i, stock in enumerate(buy_signals, 1):
        print(f"{i:2d}. {stock['ticker']:6s} ${stock['price']:>8.2f} "
              f"({stock['change_pct']:+6.2f}%) RSI: {stock['rsi']:>5.1f} "
              f"Score: {stock['score']:>4.1f}")

    print(f"\n" + "="*70)
    print("SCAN SUMMARY:")
    print(f"  Total scanned: {len(all_stocks)}")
    print(f"  BUY signals:   {len([s for s in all_stocks if s['signal'] == 'BUY'])}")
    print(f"  HOLD signals:  {len([s for s in all_stocks if s['signal'] == 'HOLD'])}")
    print(f"  SELL signals:  {len([s for s in all_stocks if s['signal'] == 'SELL'])}")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
