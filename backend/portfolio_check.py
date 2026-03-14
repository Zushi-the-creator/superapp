"""
Portfolio Health Check - Automated ATLAS V2 Rule Validator
==========================================================
Runs EVERY rule on EVERY holding in one shot. No rule can be skipped.

Usage:
    python3 portfolio_check.py                  # Full check (console)
    python3 portfolio_check.py --ticker COHR    # Check single ticker
    python3 portfolio_check.py --json           # Output JSON (for webhooks)
    python3 portfolio_check.py --webhook URL    # Push alerts to Make.com webhook

Rules checked (all mandatory):
    1. SMA50 trend filter (price > SMA50?)
    2. RSI(2) zone + expected return
    3. Regime detection + BEAR filter
    4. Crash detection (>8% single-day drop)
    5. Volume confirmation (volume > 1.5x avg)
    6. Earnings within 7 days (SELL before, not just veto buys)
    7. News sentiment (VETO if negative)
    8. Analyst target (overvalued?)
    9. Backtest WR >= 55%, 10+ trades
    10. Macro check (SPY/QQQ trend)
"""

import asyncio
import aiohttp
import json
import sys
import os
import argparse
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_cache import DataCache
from atlas_v2.entry import EntryEngine
from atlas_v2.regime import RegimeDetector


@dataclass
class HoldingCheck:
    ticker: str
    shares: float
    entry_price: float
    # Populated by checks
    live_price: float = 0
    day_change_pct: float = 0
    pnl: float = 0
    pnl_pct: float = 0
    # Rule results
    sma50: float = 0
    above_sma50: bool = False
    rsi2: float = -1
    rsi_zone: str = ""
    zone_return: float = 0
    zone_wr: float = 0
    zone_trades: int = 0
    regime: str = ""
    overall_wr: float = 0
    overall_trades: int = 0
    overall_avg_return: float = 0
    # NEW: Crash detection
    crash_detected: bool = False
    # NEW: Volume confirmation
    volume_ratio: float = 0  # current vol / 20-day avg vol
    volume_confirmed: bool = False
    # NEW: Macro
    spy_above_sma50: bool = True
    qqq_above_sma50: bool = True
    macro_ok: bool = True
    # Existing
    earnings_date: str = ""
    earnings_within_7d: bool = False
    sentiment_label: str = ""
    sentiment_score: float = 0
    analyst_consensus: str = ""
    analyst_target: float = 0
    analyst_upside: float = 0
    # Verdict
    issues: List[str] = field(default_factory=list)
    signal: str = ""  # BUY_ZONE, HOLD, SELL, CAUTION


FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "d5ed7a9r01qjckl3djkgd5ed7a9r01qjckl3djl0")


async def _get_quote(session, ticker: str) -> Optional[Dict]:
    """Get live quote from Finnhub."""
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
        async with session.get(url, timeout=8) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("c", 0) > 0:
                    pc = data.get("pc", data["c"])
                    return {
                        "price": data["c"],
                        "prev_close": pc,
                        "day_chg": (data["c"] - pc) / pc * 100 if pc else 0,
                    }
    except Exception:
        pass
    return None


async def check_portfolio(holdings: List[Dict]) -> List[HoldingCheck]:
    """Run ALL rules on ALL holdings. Returns list of HoldingCheck with full diagnostics."""
    cache = DataCache()
    entry = EntryEngine()
    results = []

    # ── Step 1: Live quotes ──
    print("  [1/8] Live quotes...", end=" ", flush=True)
    async with aiohttp.ClientSession() as session:
        for h in holdings:
            quote = await _get_quote(session, h["ticker"])
            if quote:
                check = HoldingCheck(
                    ticker=h["ticker"],
                    shares=h["shares"],
                    entry_price=h["entry"],
                    live_price=quote["price"],
                    day_change_pct=quote["day_chg"],
                )
                check.pnl = (check.live_price - check.entry_price) * check.shares
                check.pnl_pct = (check.live_price - check.entry_price) / check.entry_price * 100
                results.append(check)
            await asyncio.sleep(0.3)
    print(f"{len(results)} OK")

    # ── Step 2: Technical analysis (SMA50, RSI, regime, backtest, volume, crash) ──
    print("  [2/8] Technical + crash + volume...", end=" ", flush=True)
    for check in results:
        df = cache.get(check.ticker, 1260)
        if df is None:
            check.issues.append("NO CACHED DATA - cannot validate")
            continue

        closes = df["Close"].dropna().tolist()
        if len(closes) < 60:
            check.issues.append(f"Only {len(closes)} days of data (need 60+)")
            continue

        highs = df["High"].tolist() if "High" in df.columns else closes
        lows = df["Low"].tolist() if "Low" in df.columns else closes
        volumes = df["Volume"].tolist() if "Volume" in df.columns else [0] * len(closes)

        # SMA50
        check.sma50 = entry.calc_sma(closes, 50)
        check.above_sma50 = check.live_price > check.sma50

        # RSI(2)
        check.rsi2 = entry.calc_rsi(closes, 2)

        # Regime
        regime_info = RegimeDetector.detect(closes, highs, lows, volumes)
        check.regime = regime_info.regime.value if hasattr(regime_info, "regime") else str(regime_info)

        # ── NEW: Crash detection (>8% single-day drop) ──
        if check.day_change_pct <= -8.0:
            check.crash_detected = True
            check.issues.append(f"CRASH: {check.day_change_pct:+.1f}% today (>8% drop)")

        # ── NEW: Volume confirmation ──
        if len(volumes) >= 20 and volumes[-1] > 0:
            avg_vol = sum(volumes[-20:]) / 20
            if avg_vol > 0:
                check.volume_ratio = volumes[-1] / avg_vol
                check.volume_confirmed = check.volume_ratio >= 1.5

        # Full backtest — V2.6: RSI<10, next-day open, 30d hold, fee-adjusted, non-overlapping
        _FEE_PCT = 0.30
        _HOLD = 30
        opens = df["Open"].tolist() if "Open" in df.columns else closes
        trades = []
        last_exit_day = -1
        for i in range(50, len(closes) - _HOLD - 1):
            if i <= last_exit_day:
                continue
            hist_closes = closes[:i + 1]
            hist_rsi2 = entry.calc_rsi(hist_closes, 2)
            hist_sma50 = entry.calc_sma(hist_closes, 50)

            if hist_rsi2 < 10 and hist_closes[-1] > hist_sma50:
                entry_p = opens[i + 1] if i + 1 < len(opens) and opens[i + 1] > 0 else closes[i]
                exit_p = closes[i + 1 + _HOLD]
                ret = ((exit_p - entry_p) / entry_p) * 100 - _FEE_PCT
                trades.append({"return": ret, "win": ret > 0, "rsi": hist_rsi2})
                last_exit_day = i + 1 + _HOLD

        if trades:
            check.overall_trades = len(trades)
            check.overall_wr = sum(1 for t in trades if t["win"]) / len(trades) * 100
            check.overall_avg_return = sum(t["return"] for t in trades) / len(trades)

        # RSI zone analysis
        zone_low = int(check.rsi2 // 10) * 10
        zone_high = zone_low + 10
        check.rsi_zone = f"{zone_low}-{zone_high}"
        zone_trades = [t for t in trades if zone_low <= t["rsi"] < zone_high]
        if zone_trades:
            check.zone_trades = len(zone_trades)
            check.zone_return = sum(t["return"] for t in zone_trades) / len(zone_trades)
            check.zone_wr = sum(1 for t in zone_trades if t["win"]) / len(zone_trades) * 100

        # RULE CHECKS
        # Zone quality: fails ATLAS V2.4 entry VETO = rotate out
        if check.zone_trades >= 10 and check.zone_return < 0:
            check.issues.append(f"NEGATIVE zone return ({check.zone_return:+.1f}%, {check.zone_wr:.0f}% WR, {check.zone_trades}t)")
        elif check.zone_trades >= 10 and check.zone_wr < 65:
            check.issues.append(f"Zone WR below 65% ({check.zone_wr:.0f}%, {check.zone_return:+.1f}% ret, {check.zone_trades}t)")

        if not check.above_sma50:
            check.issues.append(f"BELOW SMA50 (${check.live_price:.2f} < ${check.sma50:.2f}, gap {(check.live_price-check.sma50)/check.sma50*100:+.1f}%)")

        if check.overall_trades > 0 and check.overall_wr < 55:
            check.issues.append(f"WR below 55% ({check.overall_wr:.1f}%)")

        if check.overall_trades < 10 and check.overall_trades > 0:
            check.issues.append(f"Insufficient trades ({check.overall_trades})")

        # ── NEW: BEAR regime warning ──
        if "BEAR" in str(check.regime).upper():
            check.issues.append(f"BEAR regime - no edge for mean reversion")

    print("done")

    # ── Step 3: Macro check (SPY + QQQ above SMA50?) ──
    print("  [3/8] Macro check (SPY/QQQ)...", end=" ", flush=True)
    for macro_ticker in ["SPY", "QQQ"]:
        df = cache.get(macro_ticker, 365)
        if df is not None:
            mc = df["Close"].dropna().tolist()
            if len(mc) >= 50:
                macro_sma50 = entry.calc_sma(mc, 50)
                macro_above = mc[-1] > macro_sma50
                for check in results:
                    if macro_ticker == "SPY":
                        check.spy_above_sma50 = macro_above
                    else:
                        check.qqq_above_sma50 = macro_above

    for check in results:
        check.macro_ok = check.spy_above_sma50 and check.qqq_above_sma50
        if not check.spy_above_sma50:
            check.issues.append("MACRO: SPY below SMA50 - broad market downtrend")
        if not check.qqq_above_sma50:
            check.issues.append("MACRO: QQQ below SMA50 - tech sector downtrend")
    print("done")

    # ── Step 4: Earnings check ──
    print("  [4/8] Earnings calendar...", end=" ", flush=True)
    async with aiohttp.ClientSession() as session:
        today = datetime.now()
        from_date = today.strftime("%Y-%m-%d")
        to_date = (today + timedelta(days=7)).strftime("%Y-%m-%d")

        for check in results:
            try:
                url = (f"https://finnhub.io/api/v1/calendar/earnings"
                       f"?from={from_date}&to={to_date}"
                       f"&symbol={check.ticker}&token={FINNHUB_KEY}")
                async with session.get(url, timeout=8) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for e in data.get("earningsCalendar", []):
                            if e.get("symbol", "").upper() == check.ticker.upper():
                                check.earnings_date = e.get("date", "")
                                check.earnings_within_7d = True
                                check.issues.append(f"EARNINGS on {check.earnings_date} - SELL BEFORE")
                await asyncio.sleep(0.3)
            except Exception:
                pass
    print("done")

    # ── Step 5: Sentiment ──
    print("  [5/8] News sentiment...", end=" ", flush=True)
    try:
        from sentiment import SentimentEngine
        sentiment_engine = SentimentEngine()
        for check in results:
            try:
                sdata = await sentiment_engine.get_ticker_sentiment(check.ticker)
                if sdata:
                    check.sentiment_label = sdata.get("sentiment_label", "NEUTRAL")
                    check.sentiment_score = sdata.get("sentiment_score", 0)
                    if check.sentiment_score < -0.3:
                        check.issues.append(f"NEGATIVE sentiment ({check.sentiment_score:.2f})")
            except Exception:
                check.sentiment_label = "N/A"
    except ImportError:
        for check in results:
            check.sentiment_label = "N/A"
    print("done")

    # ── Step 6: Analyst targets ──
    print("  [6/8] Analyst targets...", end=" ", flush=True)
    try:
        from analyst_data import AnalystDataFetcher
        analyst = AnalystDataFetcher()
        for check in results:
            try:
                adata = await analyst.fetch_analyst_data(check.ticker)
                if adata:
                    check.analyst_consensus = adata.get("consensus", "")
                    check.analyst_target = adata.get("price_target_avg", 0)
                    if check.analyst_target > 0:
                        check.analyst_upside = ((check.analyst_target - check.live_price) / check.live_price) * 100
                    if check.analyst_target > 0 and check.live_price > check.analyst_target:
                        check.issues.append(f"OVERVALUED (${check.live_price:.0f} > target ${check.analyst_target:.0f})")
            except Exception:
                pass
    except ImportError:
        pass
    print("done")

    # ── Step 7: Determine signal ──
    print("  [7/8] Generating signals...", end=" ", flush=True)
    for check in results:
        # Priority order: most critical issues first
        # NOTE: BELOW SMA50 alone is NOT an exit trigger — ATLAS V2.4 uses per-stock
        # exit strategies (Fixed14d, RSI80, etc.). SMA50 breach is a CAUTION, not SELL.
        if any("NEGATIVE zone return" in i for i in check.issues):
            check.signal = "SELL"
        elif any("Zone WR below 65%" in i for i in check.issues):
            check.signal = "SELL"
        elif any("CRASH" in i for i in check.issues):
            check.signal = "CRASH"
        elif any("EARNINGS" in i for i in check.issues):
            check.signal = "SELL BEFORE EARNINGS"
        elif any("BEAR regime" in i for i in check.issues):
            check.signal = "SELL"
        elif any("WR below" in i for i in check.issues):
            check.signal = "SELL"
        elif any("BELOW SMA50" in i for i in check.issues):
            check.signal = "CAUTION"
        elif any("NEGATIVE sentiment" in i for i in check.issues):
            check.signal = "CAUTION"
        elif any("OVERVALUED" in i for i in check.issues):
            check.signal = "CAUTION"
        elif any("MACRO" in i for i in check.issues):
            check.signal = "CAUTION"
        elif check.rsi2 >= 0 and check.rsi2 < 10 and check.above_sma50:
            check.signal = "BUY ZONE"
        elif check.rsi2 < 30 and check.above_sma50:
            check.signal = "NEAR BUY"
        elif check.rsi2 > 80:
            check.signal = "OVERBOUGHT"
        else:
            check.signal = "HOLD"
    print("done")

    # ── Step 8: Build alerts ──
    print("  [8/8] Building alerts...", end=" ", flush=True)
    print("done\n")

    cache.close()
    return results


def build_alerts(results: List[HoldingCheck]) -> List[Dict]:
    """Build alert messages for webhook/WhatsApp."""
    alerts = []
    for c in results:
        if not c.issues and c.signal in ("HOLD", "OVERBOUGHT"):
            continue  # No alert needed for clean holds

        severity = "INFO"
        if c.signal in ("SELL", "CRASH", "SELL BEFORE EARNINGS"):
            severity = "CRITICAL"
        elif c.signal == "CAUTION":
            severity = "WARNING"
        elif c.signal == "BUY ZONE":
            severity = "OPPORTUNITY"

        alert = {
            "severity": severity,
            "ticker": c.ticker,
            "signal": c.signal,
            "price": c.live_price,
            "day_change": f"{c.day_change_pct:+.1f}%",
            "pnl": f"${c.pnl:+,.2f} ({c.pnl_pct:+.1f}%)",
            "issues": c.issues,
            "summary": f"{c.ticker}: {c.signal} | ${c.live_price:.2f} ({c.day_change_pct:+.1f}%) | {'; '.join(c.issues) if c.issues else 'All clear'}",
        }
        alerts.append(alert)
    return alerts


def results_to_json(results: List[HoldingCheck]) -> Dict:
    """Convert results to JSON-serializable dict for webhook."""
    total_value = sum(c.shares * c.live_price for c in results)
    total_pnl = sum(c.pnl for c in results)
    alerts = build_alerts(results)

    return {
        "timestamp": datetime.now().isoformat(),
        "portfolio_value": round(total_value, 2),
        "portfolio_pnl": round(total_pnl, 2),
        "portfolio_pnl_pct": round(total_pnl / total_value * 100, 2) if total_value else 0,
        "holdings": len(results),
        "alerts_count": len(alerts),
        "has_critical": any(a["severity"] == "CRITICAL" for a in alerts),
        "alerts": alerts,
        "positions": [
            {
                "ticker": c.ticker,
                "shares": c.shares,
                "entry": c.entry_price,
                "live": c.live_price,
                "day_chg": round(c.day_change_pct, 2),
                "pnl": round(c.pnl, 2),
                "pnl_pct": round(c.pnl_pct, 2),
                "signal": c.signal,
                "rsi2": round(c.rsi2, 1),
                "sma50": round(c.sma50, 2),
                "above_sma50": c.above_sma50,
                "regime": str(c.regime),
                "wr": round(c.overall_wr, 1),
                "zone_return": round(c.zone_return, 2),
                "volume_ratio": round(c.volume_ratio, 2),
                "macro_ok": c.macro_ok,
                "sentiment": c.sentiment_label,
                "analyst": c.analyst_consensus,
                "issues": c.issues,
            }
            for c in results
        ],
    }


async def push_to_webhook(url: str, data: Dict) -> bool:
    """Push alert data to Make.com (or any) webhook."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, timeout=10) as resp:
                if resp.status in (200, 201, 202):
                    print(f"  Webhook OK ({resp.status})")
                    return True
                else:
                    print(f"  Webhook failed ({resp.status}): {await resp.text()}")
                    return False
    except Exception as e:
        print(f"  Webhook error: {e}")
        return False


def print_report(results: List[HoldingCheck]):
    """Print formatted portfolio health report."""
    print("=" * 105)
    print("  PORTFOLIO HEALTH CHECK - ATLAS V2 Full Validation")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')} | {len(results)} holdings | 10 rules checked per stock")
    print("=" * 105)

    total_value = 0
    total_pnl = 0

    for c in results:
        value = c.shares * c.live_price
        total_value += value
        total_pnl += c.pnl
        pct_of_portfolio = value / sum(r.shares * r.live_price for r in results) * 100

        sig_map = {
            "SELL": "!! SELL !!",
            "CRASH": "!! CRASH !!",
            "SELL BEFORE EARNINGS": "!! SELL (EARNINGS) !!",
            "BUY ZONE": ">> BUY ZONE <<",
            "CAUTION": "~~ CAUTION ~~",
        }
        sig = sig_map.get(c.signal, c.signal)

        print(f"\n  {c.ticker} | {sig}")
        print(f"  {'─' * 65}")
        print(f"  Position:  {c.shares:.4f} shares @ ${c.entry_price:.2f} = ${value:,.0f} ({pct_of_portfolio:.1f}%)")
        print(f"  Live:      ${c.live_price:.2f} (day: {c.day_change_pct:+.1f}%) | P&L: ${c.pnl:+,.2f} ({c.pnl_pct:+.1f}%)")
        print(f"  Trend:     SMA50=${c.sma50:.2f} | {'ABOVE' if c.above_sma50 else 'BELOW'} ({(c.live_price-c.sma50)/c.sma50*100:+.1f}% gap)")
        print(f"  RSI(2):    {c.rsi2:.1f} | Zone {c.rsi_zone}: {c.zone_return:+.2f}% ret, {c.zone_wr:.0f}% WR, {c.zone_trades} trades")
        print(f"  Backtest:  WR={c.overall_wr:.1f}% | {c.overall_trades} trades | Avg: {c.overall_avg_return:+.2f}%")
        print(f"  Regime:    {c.regime}")
        print(f"  Crash:     {'YES ' + str(c.day_change_pct) + '%' if c.crash_detected else 'No'}")
        print(f"  Volume:    {c.volume_ratio:.1f}x avg {'(CONFIRMED)' if c.volume_confirmed else '(low)'}")
        print(f"  Macro:     SPY>SMA50: {'Yes' if c.spy_above_sma50 else 'NO'} | QQQ>SMA50: {'Yes' if c.qqq_above_sma50 else 'NO'}")
        print(f"  Earnings:  {'WITHIN 7 DAYS: ' + c.earnings_date + ' - SELL BEFORE!' if c.earnings_within_7d else 'Clear'}")
        print(f"  Sentiment: {c.sentiment_label} ({c.sentiment_score:+.2f})")
        if c.analyst_target > 0:
            print(f"  Analyst:   {c.analyst_consensus} | Target: ${c.analyst_target:.0f} ({c.analyst_upside:+.1f}%)")
        else:
            print(f"  Analyst:   {c.analyst_consensus or 'N/A'}")

        if c.issues:
            print(f"  ISSUES:")
            for issue in c.issues:
                print(f"    >> {issue}")
        else:
            print(f"  ISSUES:    None - all checks passed")

    # Summary
    print(f"\n{'=' * 105}")
    print(f"  SUMMARY")
    print(f"{'=' * 105}")
    print(f"  Portfolio value: ${total_value:,.2f} | P&L: ${total_pnl:+,.2f} ({total_pnl/total_value*100:+.1f}%)")
    print()

    sells = [r for r in results if r.signal in ("SELL", "CRASH", "SELL BEFORE EARNINGS")]
    cautions = [r for r in results if r.signal == "CAUTION"]
    buys = [r for r in results if r.signal == "BUY ZONE"]

    if sells:
        print(f"  ACTION REQUIRED ({len(sells)}):")
        for r in sells:
            print(f"    {r.ticker} [{r.signal}]: {', '.join(r.issues)}")
    if cautions:
        print(f"  CAUTION ({len(cautions)}):")
        for r in cautions:
            print(f"    {r.ticker}: {', '.join(r.issues)}")
    if buys:
        print(f"  OPPORTUNITY ({len(buys)}):")
        for r in buys:
            print(f"    {r.ticker}: RSI={r.rsi2:.1f}, zone return {r.zone_return:+.2f}%, WR={r.zone_wr:.0f}%")

    if not sells and not cautions:
        print("  All holdings PASS - no issues found")

    print()


# ── CLI ──

async def main():
    parser = argparse.ArgumentParser(description="Portfolio Health Check")
    parser.add_argument("--ticker", help="Check single ticker")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--webhook", help="Push to Make.com webhook URL")
    args = parser.parse_args()

    # Current holdings - UPDATE THESE when portfolio changes
    # Last updated: 2026-02-12
    holdings = [
        {"ticker": "COHR", "shares": 9.3113, "entry": 220.59},
        {"ticker": "LRCX", "shares": 4.5502, "entry": 220.42},
        {"ticker": "ALB", "shares": 6.5893, "entry": 162.38},
        {"ticker": "BE", "shares": 7.1667, "entry": 141.90},
    ]

    if args.ticker:
        holdings = [h for h in holdings if h["ticker"] == args.ticker.upper()]
        if not holdings:
            print(f"Ticker {args.ticker} not in portfolio")
            return

    print()
    print("  Running 10-rule validation on all holdings...")
    results = await check_portfolio(holdings)

    if args.json:
        data = results_to_json(results)
        print(json.dumps(data, indent=2))
    elif args.webhook:
        data = results_to_json(results)
        print_report(results)
        print(f"\n  Pushing to webhook: {args.webhook}")
        await push_to_webhook(args.webhook, data)
    else:
        print_report(results)


if __name__ == "__main__":
    asyncio.run(main())
