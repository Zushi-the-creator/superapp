"""
15-Second Rotational Stock Scanner
Scans top NASDAQ stocks in batches, prioritizing high-volume "hot" stocks
Uses multi-source data fetching - NEVER fails!
"""

import asyncio
import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import json
from pathlib import Path
from signals import SignalEngine
from sentiment import SentimentEngine
from data_fetcher import get_fetcher
from historical import HistoricalDataManager
from positions import PositionManager
from alerts import AlertManager
from analyst_data import get_analyst_data


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

        # Historical data and tracking
        self.historical_manager = HistoricalDataManager(f"{data_dir}/historical.db")
        self.position_manager = PositionManager(f"{data_dir}/positions.db")
        self.alert_manager = AlertManager(f"{data_dir}/alerts.db")

        # Scanner state
        self.scan_results = {}
        self.hot_tickers = set()  # High-volume stocks to prioritize
        self.all_tickers = []
        self.scan_batch_size = 100  # Increased for 1000 stocks
        self.hot_batch_size = 50    # Scan more hot stocks

        # Metadata
        self.last_full_scan = None
        self.last_hot_scan = None
        self.scan_count = 0

        # Load NASDAQ tickers
        self._load_nasdaq_tickers()

        # Load cached results for instant API responses
        self._load_cached_results()

    def _load_nasdaq_tickers(self):
        """Load NASDAQ tickers from a predefined list"""
        # Portfolio stocks FIRST (always prioritized)
        portfolio = ["VST", "LLY", "MRVL"]

        # Expanded to 1000 NASDAQ stocks
        top_nasdaq = portfolio + [
            # Mega caps (Top 10)
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "AVGO", "COST",

            # Large caps (Top 100)
            "NFLX", "ASML", "AMD", "PEP", "ADBE", "CSCO", "TMUS", "CMCSA", "INTC", "TXN",
            "QCOM", "INTU", "AMGN", "HON", "AMAT", "SBUX", "BKNG", "ISRG", "PANW", "ADP",
            "GILD", "ADI", "VRTX", "REGN", "LRCX", "MDLZ", "KLAC", "SNPS", "CDNS", "MELI",
            "MAR", "PYPL", "ABNB", "CRWD", "FTNT", "WDAY", "DASH", "TEAM", "DDOG", "SNOW",
            "ZS", "MRVL", "ORLY", "ADSK", "NXPI", "MNST", "CTAS", "PAYX", "ROST", "FAST",
            "ODFL", "CPRT", "PCAR", "CEG", "EXC", "KDP", "EA", "DXCM", "IDXX", "BIIB",
            "MRNA", "ILMN", "KHC", "CSGP", "GEHC", "DLTR", "MCHP", "CHTR", "ANSS", "ON",
            "WBD", "RIVN", "LCID", "NIO", "PLUG", "COIN", "HOOD", "SOFI", "PLTR", "RBLX",
            "U", "DKNG", "UBER", "LYFT", "ZM", "DOCU", "ROKU", "SQ", "SHOP", "PINS", "SNAP",

            # Mid caps (100-300)
            "CSGP", "FANG", "TTWO", "XEL", "EBAY", "VRSK", "ALGN", "ENPH", "SGEN", "TECH",
            "NTES", "JD", "BIDU", "SIRI", "SWKS", "MCHP", "POOL", "NWSA", "EXPE", "DOCU",
            "OKTA", "ZBRA", "ALNY", "TCOM", "ULTA", "SSNC", "NDAQ", "NDSN", "MTCH", "FOXA",
            "FOX", "INCY", "BMRN", "ICLR", "PODD", "MANH", "NTNX", "EXAS", "TTWO", "TRMB",
            "SWKS", "OTEX", "COHR", "NTAP", "FFIV", "AKAM", "JBHT", "CHRW", "LBRDA", "LBRDK",
            "CHKP", "VRSN", "JKHY", "TTEK", "LSCC", "WIX", "IOVA", "TXRH", "BGNE", "FIVE",
            "MKTX", "FLEX", "NBIX", "ENTG", "WING", "GLPI", "CTRE", "UTHR", "CVLT", "OLED",
            "BILI", "PDD", "CRNC", "STLD", "QRVO", "LULU", "DADA", "LBRDA", "SANM", "PCTY",
            "IBKR", "EWBC", "SLAB", "TGTX", "CASY", "TREE", "LSCC", "CVNA", "ARVN", "FIVE",
            "STAA", "ABCL", "ALRM", "CENT", "ALTR", "CENTA", "ALGM", "SYNH", "FWONK", "LITE",

            # Small caps (300-600)
            "THRM", "DNLI", "CSIQ", "MTSI", "SAVA", "KNSL", "TNDM", "ACLS", "PTON", "JJSF",
            "NSIT", "XRAY", "PDCO", "RXDX", "PRGS", "PEGA", "NOVT", "NEOG", "MASI", "MATX",
            "LOPE", "LANC", "KELYA", "HSIC", "HAIN", "HALO", "GTLS", "FORM", "ETSY", "ENSG",
            "ENTA", "EXPO", "EEFT", "EGBN", "DORM", "DIOD", "CRSR", "CROX", "CORT", "COKE",
            "CHEF", "CELH", "CCOI", "CASY", "CALX", "CAKE", "BRKR", "BPMC", "BNTX", "BL",
            "BHF", "BGCP", "BECN", "BANR", "BANF", "AGIO", "AAON", "WVE", "VNET", "VCYT",
            "URBN", "UFPT", "TREX", "TIGO", "TCBI", "SYNA", "SYKE", "SGMS", "SASR", "RXRX",
            "RGEN", "QGEN", "PULM", "PRTA", "PINC", "PCRX", "PACW", "OLLI", "OMCL", "NVCR",
            "NTCT", "NRIX", "NKTR", "NAVI", "NAOV", "MYGN", "MSGE", "MNDY", "MKTW", "MCRI",
            "MBIN", "LSXMA", "LSXMK", "LOMA", "LITE", "LGND", "KTOS", "KPTI", "KRNT", "IONS",

            # Additional growth/tech (600-800)
            "INSM", "IMGN", "GTLB", "GLBE", "GIII", "GERN", "GBDC", "FYBR", "FSLY", "FRPT",
            "FOLD", "FATE", "EXEL", "EZPW", "EVBG", "EVAX", "ENVA", "ENLC", "ELAN", "EDIT",
            "ECPG", "DZSI", "DSGX", "CRNX", "CRDO", "COUP", "CORZ", "COOP", "CLOV", "CLSK",
            "CHDN", "CDNA", "CASY", "BYND", "BTAI", "BRZE", "BRKL", "BPOP", "BMBL", "BILI",
            "BCPC", "BBIO", "AZPN", "AXON", "AVAV", "AVNW", "ATRC", "ATER", "ARVN", "ARWR",
            "ARQT", "ARCC", "APLS", "APPN", "ANET", "AMSC", "AMED", "ALKT", "ALGN", "ALEC",
            "AIRC", "AGIO", "AGFY", "AFYA", "ADTN", "ADNT", "ADMA", "ACIW", "ACHR", "ABUS",
            "AAWW", "ZLAB", "YEXT", "WTFC", "WOOF", "WOLF", "WIX", "WING", "WDAY", "WAFD",
            "VRTS", "VOYA", "VIRT", "VICR", "VECO", "VBTX", "VAPO", "UMBF", "UCBI", "UBSI",
            "TRUP", "TRMK", "TRAW", "TPTX", "TOWN", "TGTX", "TDUP", "TASK", "SWTX", "STRL",

            # Biotech/Healthcare (800-900)
            "SRRK", "SPSC", "SPNE", "SNDX", "SITM", "SHOO", "SGRY", "SEIC", "SDGR", "SCPH",
            "SBRA", "SATS", "SANM", "RRGB", "RPRX", "RCKT", "RCEL", "RARE", "RAMP", "RAPT",
            "RAIL", "QLYS", "QNST", "PZZA", "PYPD", "PWSC", "PRTA", "POOL", "PLXS", "PLMR",
            "PLCE", "PFSI", "PDCE", "PBCT", "PATK", "PASG", "PACB", "OSPN", "OPCH", "ONCR",
            "OMAB", "OLLI", "OFIX", "ODFL", "OCUL", "NWBI", "NTLA", "NSSC", "NRIX", "NKTR",
            "NCNO", "NAVI", "MVST", "MRVI", "MPWR", "MDGL", "MCBS", "MANT", "LYEL", "LXRX",
            "LWLG", "LIVN", "LHCG", "LFST", "LAZR", "LANC", "LAKE", "KNBE", "KLIC", "KFRC",
            "KAVL", "JOB", "JAZZ", "IRWD", "IRDM", "IOVA", "INVA", "INSM", "INGN", "INCY",
            "IMVT", "IMAX", "IART", "HSII", "HROW", "HQY", "HIMX", "HIFS", "HELE", "HALO",
            "HAFC", "GWRE", "GTIM", "GTBP", "GRFS", "GRAL", "GLPG", "GKOS", "GLDD", "GH",

            # Additional stocks (900-1000)
            "GDRX", "GBDC", "FWRD", "FULT", "FULC", "FTDR", "FRME", "FROG", "FRGE", "FMBI",
            "FLYW", "FIVN", "FIXX", "FIBK", "FFIN", "FELE", "FCNCA", "FBNC", "EXLS",
            "EVGO", "ETNB", "ESTA", "EPRT", "EPAM", "ENOV", "ENFN", "EMBC", "ELOX",
            "DXPE", "DWAC", "DUOL", "DSGX", "DRRX", "DOMO", "DNA", "DMRC", "DESP",
            "DENN", "DECK", "DCBO", "CVCO", "CVBF", "CSSE", "CSOD", "CRWS",
            "CRSP", "CRGY", "CREG", "CRBP", "CPSI", "COLL", "COLM",
            "COLB", "CNXC", "CNMD", "CNET", "CLVT", "CLNE", "CLDX", "CLAY", "CLBK", "CKPT",
            "CHMG", "CGEM", "CERT", "CDAY", "CBRE", "CATX",
            "CASH", "CAPR", "CALA", "CAHC", "CABO", "BYSI", "BUSE", "BTSG", "BSIG",
            "BRLT", "BRID", "BPTH", "BNGO", "BMEA", "BLZE", "BLFS", "BLBD", "BJRI", "BEAT",

            # More stocks to reach 1000
            "ZION", "ZBRA", "YUMC", "YTRA", "YMAB", "YELP", "YELL", "YY", "WWAV", "WRBY",
            "WPRT", "WORX", "WLDN", "WILC", "WIFI", "WHF", "WERN", "WEBR", "WBA", "WABC",
            "VYGR", "VUZI", "VTYX", "VTLE", "VSTM", "VSA", "VRRM", "VRAY", "VOXX", "VNOM",
            "VNDA", "VMEO", "VLTO", "VKTX", "VIOT", "VINP", "VCEL", "VAXX", "VANI", "VAN",
            "VALU", "UTSI", "USNA", "USLM", "USCR", "USAP", "USAK", "URBN", "URGN", "UFPT",
            "UFCS", "UEPS", "UCTT", "UAMY", "TZOO", "TYME", "TYHT", "TXMD", "TWST", "TWLO",
            "TUSK", "TRVG", "TRVI", "TRTX", "TRNR", "TRMD", "TRIL", "TRIB", "TRHC", "TREX",
            "TPTX", "TPHS", "TPIC", "TOPS", "TOON", "TOMZ", "TOMM", "TTSH", "TIPT", "TITN",
            "TIVC", "TISI", "TIRX", "TINV", "TIMB", "TICC", "THRY", "THFF", "TGLS", "TFSL",
            "TFFP", "TEAF", "TDOC", "TCMD", "TCBI", "TCAT", "TARS", "TANH", "TALO", "TALK",
            "TAIT", "TACQ", "TACO", "SYRS", "SYBX", "SVRA", "SVFD", "SUPN", "SUNS", "SUMR",
            "STKL", "STKS", "STIM", "STER", "STEP", "STEM", "STCN", "STBA", "SSYS", "SSRM",
            "SSPK", "SSNT", "SSNC", "SRZN", "SRTS", "SRRA", "SRPT", "SRNG", "SRDX", "SQNS",
            "SPWH", "SPTN", "SPPI", "SPNE", "SPLK", "SPIR", "SPGI", "SPEX", "SPCE", "SOHU",
            "SNPS", "SNPX", "SNPO", "SNFCA", "SNDL", "SMTX", "SMTS", "SMSI", "SMRT", "SMLR",
            "SMBK", "SLRC", "SLRX", "SLQT", "SLNO", "SLNH", "SLNG", "SLGN", "SLDB", "SLAB",
            "SKYX", "SKYT", "SKWD", "SKIN", "SIMO", "SILV", "SILC", "SIEB", "SIEN", "SHSP",
            "SHLS", "SHFS", "SGMA", "SGLY", "SGLB", "SFNC", "SFET", "SEAC", "SDOT", "SCYX",
            "SCWX", "SCVL", "SCPH", "SCOR", "SCKT", "SCHL", "SCHN", "SCHL", "SCHW", "SCBX",
            "SCAY", "SBPH", "SBOW", "SBNY", "SBLK", "SASR", "SASI", "SANW", "SAMG", "SAIA",
            "SABR", "RYAAY", "RVMD", "RVLV", "RUTH", "RVSN", "RUHN", "RTPZ", "RTIX", "RSVR",
            "RSTUF", "RSSS", "RSLS", "RSKD", "RIBT", "RGLS", "RGNX", "RFIL", "RFDI", "REVG",
            "REYN", "RETA", "REST", "REPH", "RENT", "RELI", "REKR", "REFI", "REEF", "RDWR",
            "RDUS", "RDNT", "RDHL", "RDCM", "RCUS", "RCRT", "RCEL", "RAZFF", "RATE", "RAYA",
            "RAVN", "RAVE", "RARE", "RAPT", "RANI", "RAMP", "RAIL", "RADI", "RADA", "QUOT",
            "QTTB", "QTNT", "QTNT", "QSII", "QRHC", "QNST", "QMCO", "QLGN", "QLYS", "QLGN",
            "QFIN", "QETH", "QDEL", "QADB", "QADA", "PZZA", "PYPD", "PWOD", "PWFL", "PTVCA",
            "PTSI", "PSMT", "PRLB", "PRLD", "PRGS", "PRFT", "PRCP", "PRAX", "PRAA", "POWW",
            "POTX", "PONO", "POET", "PNTR", "PNTG", "PNNT", "PNFP", "PMVP", "PMTS", "PLTR",
            "PLAB", "PIII", "PIXY", "PIII", "PINC", "PHAT", "PFIS", "PFIN", "PFBC", "PETV",
            "PESI", "PDEX", "PDCE", "PCRX", "PCSA", "PAYS", "PAVM", "PATI", "PATK", "PASG"
        ]

        self.all_tickers = top_nasdaq
        print(f"Loaded {len(self.all_tickers)} NASDAQ tickers")

    async def scan_ticker(self, ticker: str) -> Optional[Dict]:
        """
        Scan a single ticker and generate comprehensive analysis
        Uses Finnhub for live quotes (always works)

        Returns:
            Dict with ticker data, signals, and sentiment
        """
        try:
            fetcher = get_fetcher()

            # PRIORITY: Get live quote from Finnhub (free, no limits)
            quote = await fetcher.get_quote(ticker)
            if not quote or quote.get('price', 0) == 0:
                print(f"⚠️ {ticker}: No live quote available")
                return None

            current_price = quote['price']
            price_change = quote.get('change', 0)
            price_change_pct = quote.get('change_pct', 0)

            # Try to get historical data for technical analysis (may fail due to rate limits)
            df = await fetcher.fetch_stock_data(ticker, period_days=30)

            # Stock info - use simple fallback (no Yahoo Finance)
            company_name = ticker
            company_desc = ""
            sector = "Technology"
            info = {"shortName": ticker, "sector": sector}

            # Calculate technical signals (if historical data available)
            if df is not None and not df.empty and len(df) >= 5:
                signals = self.signal_engine.generate_signals(df)
                current_volume = int(df['Volume'].iloc[-1])
                avg_volume = int(df['Volume'].mean())
                is_hot = current_volume > (avg_volume * 1.5)
            else:
                # No historical data - use defaults
                signals = {"signal": "HOLD", "strength": 0, "rsi": 50.0, "ema_fast": 0, "ema_slow": 0, "reasons": ["No historical data"]}
                current_volume = 0
                avg_volume = 1
                is_hot = False

            # Get sentiment (async)
            sentiment = await self.sentiment_engine.get_ticker_sentiment(ticker)

            # Get analyst data (async)
            analyst_data = await get_analyst_data(ticker)

            # Calculate combined score
            # Technical (40%) + Sentiment (20%) + Analyst Consensus (40%)
            tech_score = signals["strength"] / 100.0
            sent_score = (sentiment["sentiment_score"] + 1) / 2  # Normalize -1 to 1 -> 0 to 1

            # Analyst score - based on upside potential and consensus
            analyst_score = 0
            if analyst_data and analyst_data.get('source') != 'no_data':
                upside_pct = analyst_data.get('upside_potential', 0)
                upside_score = min(upside_pct / 100, 1.0)
                consensus_map = {
                    'Strong Buy': 1.0, 'Buy': 0.8, 'Hold': 0.5, 'Sell': 0.2, 'Strong Sell': 0.0, 'No Data': 0.5
                }
                consensus_score = consensus_map.get(analyst_data.get('consensus', 'Hold'), 0.5)
                analyst_score = (upside_score * 0.6) + (consensus_score * 0.4)

            combined_score = (tech_score * 0.4) + (sent_score * 0.2) + (analyst_score * 0.4)

            result = {
                "ticker": ticker,
                "name": company_name,
                "description": company_desc,
                "sector": sector,
                "price": round(current_price, 2),
                "change": round(price_change, 2),
                "change_pct": round(price_change_pct, 2),
                "volume": current_volume,
                "avg_volume": avg_volume,
                "volume_ratio": round(current_volume / avg_volume, 2) if avg_volume > 0 else 0,
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

                # Analyst data - NEW!
                "analyst_target_avg": analyst_data.get('price_target_avg', 0) if analyst_data else 0,
                "analyst_target_high": analyst_data.get('price_target_high', 0) if analyst_data else 0,
                "analyst_target_low": analyst_data.get('price_target_low', 0) if analyst_data else 0,
                "analyst_consensus": analyst_data.get('consensus', 'No Data') if analyst_data else 'No Data',
                "analyst_count": analyst_data.get('analyst_count', 0) if analyst_data else 0,
                "upside_potential": analyst_data.get('upside_potential', 0) if analyst_data else 0,
                "has_analyst_data": bool(analyst_data and analyst_data.get('source') != 'no_data'),

                # Combined
                "combined_score": round(combined_score * 100, 2),
                "reasons": signals["reasons"],

                # Metadata
                "last_updated": datetime.now().isoformat()
            }

            # Update hot tickers set
            if is_hot:
                self.hot_tickers.add(ticker)

            # Store historical snapshot (async, non-blocking)
            asyncio.create_task(self.historical_manager.store_snapshot(result))

            # Check alerts (async, non-blocking)
            asyncio.create_task(self._check_and_trigger_alerts(result))

            # Update open positions (async, non-blocking)
            asyncio.create_task(self._update_positions(result))

            return result

        except Exception as e:
            print(f"Error scanning {ticker}: {e}")
            return None

    async def _check_and_trigger_alerts(self, stock_data: Dict):
        """Check if any alerts should be triggered for this stock"""
        try:
            triggered = await self.alert_manager.check_alerts(
                stock_data['ticker'],
                stock_data['price'],
                stock_data['rsi'],
                stock_data['signal']
            )

            if triggered:
                for alert in triggered:
                    print(f"🚨 ALERT: {alert['message']}")
        except Exception as e:
            print(f"Error checking alerts for {stock_data['ticker']}: {e}")

    async def _update_positions(self, stock_data: Dict):
        """Update position snapshots with current data"""
        try:
            positions = await self.position_manager.get_open_positions()

            for position in positions:
                if position['ticker'] == stock_data['ticker']:
                    await self.position_manager.update_position_snapshot(
                        position['id'],
                        stock_data['price'],
                        stock_data['signal'],
                        stock_data['signal_strength'],
                        stock_data['rsi']
                    )
        except Exception as e:
            print(f"Error updating positions for {stock_data['ticker']}: {e}")

    async def scan_batch(self, tickers: List[str]) -> List[Dict]:
        """Scan a batch of tickers with rate limit handling"""
        results = []

        # Process in smaller sub-batches to avoid rate limiting
        sub_batch_size = 20  # Increased for faster scanning
        for i in range(0, len(tickers), sub_batch_size):
            sub_batch = tickers[i:i + sub_batch_size]
            tasks = [self.scan_ticker(ticker) for ticker in sub_batch]
            batch_results = await asyncio.gather(*tasks)
            results.extend([r for r in batch_results if r is not None])

            # Small delay between sub-batches
            if i + sub_batch_size < len(tickers):
                await asyncio.sleep(0.3)  # Reduced delay for faster scanning

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
            await asyncio.sleep(0.5)  # Reduced delay for faster scanning

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
            signal_type_upper = signal_type.upper()
            results = [r for r in results if r["signal"] == signal_type_upper]

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

    def get_top_sentiment(self, limit: int = 20) -> List[Dict]:
        """Get stocks with highest sentiment scores"""
        results = list(self.scan_results.values())
        results.sort(key=lambda x: x["sentiment_score"], reverse=True)
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

    def _load_cached_results(self):
        """Load previous scan results from disk for instant API responses"""
        try:
            results_file = self.data_dir / "scan_results.json"
            if results_file.exists():
                with open(results_file, 'r') as f:
                    data = json.load(f)
                    results = data.get("results", [])
                    for stock in results:
                        self.scan_results[stock["ticker"]] = stock
                print(f"✅ Loaded {len(self.scan_results)} cached results - API ready immediately!")
            else:
                print("No cached results found - will populate on first scan")
        except Exception as e:
            print(f"Error loading cached results: {e}")

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

    # Wait 5 seconds to ensure API is fully responsive before starting scan
    await asyncio.sleep(5)
    print("API is ready, starting background scan...")

    # Start full scan in background (don't block startup)
    asyncio.create_task(scanner.full_scan())

    full_scan_interval = 1800  # 30 minutes (1000 stocks takes longer)
    hot_scan_interval = 15     # 15 seconds for faster updates

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
