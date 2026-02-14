#!/usr/bin/env python3
"""
Deep Stock Scanner - Scans ~500 major US stocks using Yahoo Finance (yfinance 1.1+).
Uses ATLAS V2.2 criteria: RSI(2) mean reversion with SMA(50) trend filter.
"""
from __future__ import annotations

import time
import sys
import warnings
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd

# ============================================================
# STOCK UNIVERSE - ~400+ major US stocks (deduplicated)
# ============================================================
TICKERS = list(dict.fromkeys([
    "AAPL","MSFT","AMZN","NVDA","GOOGL","META","BRK-B","TSLA","UNH","XOM",
    "JNJ","JPM","V","PG","MA","HD","CVX","MRK","ABBV","LLY",
    "PFE","KO","BAC","PEP","AVGO","COST","TMO","MCD","WMT","CSCO",
    "ACN","ABT","CRM","DHR","ADBE","NFLX","AMD","TXN","NEE","BMY",
    "PM","UNP","RTX","HON","INTC","LOW","QCOM","UPS","MS","SPGI",
    "ELV","GS","INTU","BLK","ISRG","GILD","MDT","SYK","ADP","DE",
    "VRTX","AMT","SCHW","BKNG","REGN","ADI","LRCX","ETN","CB","PLD",
    "MDLZ","CI","TMUS","TJX","MO","SLB","AMAT","NOW","BSX","ZTS",
    "DUK","SO","BDX","CME","EQIX","SNPS","CL","AON","MMC","ITW",
    "NOC","ICE","SHW","PGR","GE","HUM","WM","MCK","CDNS","FIS",
    "MPC","EMR","NSC","APD","ORLY","AZO","AJG","ECL","TT","CTAS",
    "GD","ROP","CARR","TDG","CMG","PSA","CCI","DLR","D","GIS",
    "HCA","PCAR","MSCI","MNST","WEC","ILMN","DXCM","IDXX","MCHP","FSLR",
    "A","DHI","FTNT","OTIS","AME","DD","BKR","VRSK","LHX","EW",
    "KEYS","GWW","AEP","STE","KDP","HPQ","ANSS","NDAQ","YUM","WBD",
    "FAST","RSG","IFF","ED","EXR","APTV","ALGN","ROK","ROL","MTD",
    "VTR","ARE","MAA","WAT","AWK","TSCO","SWKS","STZ","CDW","CAH",
    "LH","TER","AMCR","FMC","BIO","TRGP","CF","ALB","CLX","ETSY",
    "POOL","GPC","JBHT","HRL","CPRT","PAYC","TECH","J","RDW","HAS",
    "AOS","RE","DPZ","TYL","MOH","GNRC","CRL","IEX","PODD","SJM",
    "EMN","DAL","LW","UAL","AAL","WYNN","LVS","MGM","CZR","NCLH",
    "CCL","RCL","MAR","HLT","SNA","GL","IP","KIM","UDR","AIZ",
    "SEE","FRT","HII","CTRA","PNR","BEN","WHR","MHK","NWL","BWA",
    "IVZ","ZION","CMA","WRB","RL","QRVO","DVA","BBWI","VFC","NWS",
    "NWSA","AAP","SEDG","LNC","TPR","PVH","FOXA","FOX","XRAY","DXC",
    "DISH","LUMN","MOS","OGN","PARA","VTRS","CTLT","HSIC","ALLE","NRG",
    "CEG","APA","FANG","HAL","DVN","OXY","MRO","EOG","COP","PSX",
    "VLO","HES","LYB","DOW","CE","PPG","NUE","STLD","FCX","AA",
    "NEM","FNV","AEM","WPM","RGLD","GOLD","COHR","BE","SMCI","KTOS",
    "SOUN","MSTR","PLTR","SOFI","RIVN","LCID","JOBY","NIO","BABA","JD",
    "PDD","SNOW","CRWD","NET","DDOG","ZS","OKTA","MDB","U","RBLX",
    "AI","PATH","S","BILL","HUBS","VEEV","TWLO","TTD","TOST","PINS",
    "SNAP","LYFT","UBER","ABNB","DASH","SE","GRAB","SHOP","SQ","PYPL",
    "COIN","HOOD","AFRM","UPST","LMND","OPEN","CLOV","WISH","VRT","GEV",
    "VST","ORCL","IBM","SAP","PANW","CYBR","WDAY","SPLK","TEAM","DOCU",
    "CFLT","ESTC","MNDY","GTLB","IOT","CRDO","APP","ARM","MRVL","ON",
    "NXPI","KLAC","ASML","MPWR","ENTG","MKSI","TDY","FTV","ZBRA","BR",
    "PTC","MANH","IT","EPAM","GLOB","WEX","FLUT","DKNG","PENN",
    "CHTR","CMCSA","T","VZ","AMG","CALM","BLDR","URI","WSC","MTZ",
    "PWR","EME","FIX","UFPI","ENPH","RUN","ARRY","MAXN","NOVA",
    "SPWR","NEP","BEP","CWEN","AQN","BEPC","ORA","TPIC",
    "QQQ",
]))

# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def calc_rsi(closes: List[float], period: int = 2) -> Optional[float]:
    """Calculate RSI using Wilder's smoothing method."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas[:period]]
    losses = [abs(min(d, 0)) for d in deltas[:period]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period, len(deltas)):
        d = deltas[i]
        avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
        avg_loss = (avg_loss * (period - 1) + abs(min(d, 0))) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_sma(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def get_rsi_zone(rsi_val: float) -> Tuple[int, int]:
    lo = min(int(rsi_val // 10) * 10, 90)
    return (lo, lo + 10)


# ============================================================
# ANALYSIS
# ============================================================

def analyze_stock(ticker: str, closes: List[float]) -> Optional[Dict]:
    """Run full ATLAS V2.2 analysis on a single stock."""
    if len(closes) < 100:
        return None
    current_price = closes[-1]
    if current_price <= 0:
        return None

    rsi2 = calc_rsi(closes, 2)
    if rsi2 is None:
        return None
    sma50 = calc_sma(closes, 50)
    if sma50 is None:
        return None
    above_sma50 = current_price > sma50
    rsi14 = calc_rsi(closes, 14) or 0.0

    zone_lo, zone_hi = get_rsi_zone(rsi2)
    zone_label = f"{zone_lo}-{zone_hi}"

    bt_wins = 0; bt_total = 0; bt_returns = []
    zone_wins = 0; zone_total = 0; zone_returns = []

    for i in range(52, len(closes) - 7):
        local_rsi = calc_rsi(closes[:i+1], 2)
        if local_rsi is None or i < 49:
            continue
        local_sma50 = sum(closes[i-49:i+1]) / 50
        price_i = closes[i]
        if price_i <= 0:
            continue
        above_sma = price_i > local_sma50
        fwd_ret = (closes[i + 7] - price_i) / price_i * 100.0

        if local_rsi < 20 and above_sma:
            bt_total += 1
            if fwd_ret > 0: bt_wins += 1
            bt_returns.append(fwd_ret)

        day_zone_lo, _ = get_rsi_zone(local_rsi)
        if day_zone_lo == zone_lo and above_sma:
            zone_total += 1
            if fwd_ret > 0: zone_wins += 1
            zone_returns.append(fwd_ret)

    bt_wr = (bt_wins / bt_total * 100) if bt_total > 0 else 0
    bt_avg = (sum(bt_returns) / len(bt_returns)) if bt_returns else 0
    zone_wr = (zone_wins / zone_total * 100) if zone_total > 0 else 0
    zone_avg = (sum(zone_returns) / len(zone_returns)) if zone_returns else 0

    return {
        "ticker": ticker, "price": round(current_price, 2),
        "rsi2": round(rsi2, 1), "rsi14": round(rsi14, 1),
        "sma50": round(sma50, 2), "above_sma50": above_sma50,
        "zone": zone_label,
        "bt_wr": round(bt_wr, 1), "bt_trades": bt_total, "bt_avg_ret": round(bt_avg, 2),
        "zone_wr": round(zone_wr, 1), "zone_trades": zone_total, "zone_avg_ret": round(zone_avg, 2),
        "days": len(closes),
    }


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 80)
    print("  DEEP STOCK SCANNER - ATLAS V2.2 Criteria")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Universe: {len(TICKERS)} stocks")
    print(f"  Data source: Yahoo Finance (yfinance {yf.__version__})")
    print("=" * 80)
    print(flush=True)

    start_time = time.time()
    batch_size = 50
    all_closes = {}  # ticker -> list of closes

    print(f"[FETCH] Downloading 1-year history for {len(TICKERS)} stocks in batches of {batch_size}...")
    print(flush=True)

    for batch_start in range(0, len(TICKERS), batch_size):
        batch = TICKERS[batch_start:batch_start + batch_size]
        batch_end = min(batch_start + batch_size, len(TICKERS))
        try:
            data = yf.download(
                batch,
                period="1y",
                progress=False,
                group_by="ticker",
                threads=True,
            )
            if data.empty:
                elapsed = time.time() - start_time
                print(f"  [PROGRESS] {batch_end}/{len(TICKERS)} | {len(all_closes)} OK | {elapsed:.0f}s | batch empty", flush=True)
                continue

            if len(batch) == 1:
                t = batch[0]
                try:
                    c = data["Close"].dropna().tolist()
                    if len(c) >= 50:
                        all_closes[t] = c
                except Exception:
                    pass
            else:
                # New yfinance 1.1: MultiIndex columns (Price, Ticker)
                for t in batch:
                    try:
                        c = data[("Close", t)].dropna().tolist()
                        if len(c) >= 50:
                            all_closes[t] = c
                    except (KeyError, TypeError):
                        # Try alternate column access
                        try:
                            c = data[t]["Close"].dropna().tolist()
                            if len(c) >= 50:
                                all_closes[t] = c
                        except Exception:
                            pass
        except Exception as e:
            print(f"  [WARN] Batch error: {e}", flush=True)

        elapsed = time.time() - start_time
        print(f"  [PROGRESS] {batch_end}/{len(TICKERS)} | {len(all_closes)} OK | {elapsed:.0f}s", flush=True)

    fetch_time = time.time() - start_time
    fetch_ok = len(all_closes)
    fetch_fail = len(TICKERS) - fetch_ok
    print(f"\n[FETCH] Done in {fetch_time:.1f}s | {fetch_ok} received, {fetch_fail} failed\n", flush=True)

    # ---- Analyze ----
    print("[ANALYZE] Running ATLAS V2.2 backtest...", flush=True)
    analyzed = []
    insufficient = 0
    count = 0
    for ticker, closes in all_closes.items():
        if len(closes) < 100:
            insufficient += 1
            continue
        r = analyze_stock(ticker, closes)
        if r:
            analyzed.append(r)
        count += 1
        if count % 50 == 0:
            print(f"  [ANALYZE] {count} processed...", flush=True)

    analyze_time = time.time() - start_time - fetch_time
    print(f"[ANALYZE] Done in {analyze_time:.1f}s | {len(analyzed)} analyzed, {insufficient} insufficient\n", flush=True)

    # ---- Filter ----
    print("[FILTER] RSI(2)<35 + Price>SMA50 + WR>=55% + 10+ trades + Zone return>0%", flush=True)
    candidates = [r for r in analyzed
                  if r["rsi2"] < 35 and r["above_sma50"]
                  and r["bt_wr"] >= 55.0 and r["bt_trades"] >= 10
                  and r["zone_avg_ret"] > 0]
    candidates.sort(key=lambda x: x["zone_avg_ret"], reverse=True)

    relaxed = [r for r in analyzed if r["rsi2"] < 35 and r["above_sma50"]]
    relaxed.sort(key=lambda x: x["zone_avg_ret"], reverse=True)

    # ---- Print Top Candidates ----
    total_time = time.time() - start_time
    W = 130

    print(f"\n{'='*W}")
    print(f"  TOP CANDIDATES ({len(candidates)} passed all filters)")
    print(f"{'='*W}\n")

    hdr = (f"{'#':>3} {'Ticker':<8} {'Price':>10} {'RSI(2)':>8} {'RSI(14)':>8} "
           f"{'Zone':>8} {'BT WR%':>8} {'BT Trds':>8} {'BT AvgR%':>10} "
           f"{'ZnWR%':>8} {'ZnTrds':>8} {'ZnAvgR%':>10}")

    if candidates:
        print(hdr); print("-" * W)
        for i, c in enumerate(candidates[:30], 1):
            print(f"{i:>3} {c['ticker']:<8} {c['price']:>10.2f} {c['rsi2']:>8.1f} "
                  f"{c['rsi14']:>8.1f} {c['zone']:>8} {c['bt_wr']:>8.1f} "
                  f"{c['bt_trades']:>8} {c['bt_avg_ret']:>10.2f} "
                  f"{c['zone_wr']:>8.1f} {c['zone_trades']:>8} {c['zone_avg_ret']:>10.2f}")
    else:
        print("  No stocks passed all strict filters.")

    print(f"\n{'='*W}")
    print(f"  ALL OVERSOLD + UPTREND ({len(relaxed)} found) - RSI(2)<35 & Price>SMA50")
    print(f"{'='*W}\n")

    if relaxed:
        print(hdr); print("-" * W)
        for i, c in enumerate(relaxed[:50], 1):
            flag = " ***" if c["bt_wr"] >= 55 and c["bt_trades"] >= 10 else ""
            print(f"{i:>3} {c['ticker']:<8} {c['price']:>10.2f} {c['rsi2']:>8.1f} "
                  f"{c['rsi14']:>8.1f} {c['zone']:>8} {c['bt_wr']:>8.1f} "
                  f"{c['bt_trades']:>8} {c['bt_avg_ret']:>10.2f} "
                  f"{c['zone_wr']:>8.1f} {c['zone_trades']:>8} {c['zone_avg_ret']:>10.2f}{flag}")
    else:
        print("  None found.")

    # ---- Holdings ----
    print(f"\n{'='*W}")
    print(f"  CURRENT HOLDINGS - RSI ZONE ANALYSIS")
    print(f"{'='*W}\n")

    holdings = ["QQQ","LRCX","LIN","BE","ALB"]
    hf = sorted([r for r in analyzed if r["ticker"] in holdings],
                key=lambda x: holdings.index(x["ticker"]) if x["ticker"] in holdings else 99)

    if hf:
        print(f"{'Ticker':<8} {'Price':>10} {'RSI(2)':>8} {'RSI(14)':>8} "
              f"{'Zone':>8} {'AbvSMA':>7} {'BT WR%':>8} {'BT Trds':>8} "
              f"{'BT AvgR%':>10} {'ZnWR%':>8} {'ZnTrds':>8} {'ZnAvgR%':>10}")
        print("-" * W)
        for c in hf:
            sf = "YES" if c["above_sma50"] else "NO"
            print(f"{c['ticker']:<8} {c['price']:>10.2f} {c['rsi2']:>8.1f} "
                  f"{c['rsi14']:>8.1f} {c['zone']:>8} {sf:>7} {c['bt_wr']:>8.1f} "
                  f"{c['bt_trades']:>8} {c['bt_avg_ret']:>10.2f} "
                  f"{c['zone_wr']:>8.1f} {c['zone_trades']:>8} {c['zone_avg_ret']:>10.2f}")
    else:
        print("  Holdings not found in scan results.")

    # ---- Stats ----
    print(f"\n{'='*80}")
    print(f"  SCAN STATISTICS")
    print(f"{'='*80}")
    print(f"  Total tickers:               {len(TICKERS)}")
    print(f"  Data received:               {fetch_ok}")
    print(f"  Failed/missing:              {fetch_fail}")
    print(f"  Analyzed:                    {len(analyzed)}")
    print(f"  Oversold+Uptrend (RSI<35):   {len(relaxed)}")
    print(f"  Passed ALL filters:          {len(candidates)}")
    print(f"  Fetch time:                  {fetch_time:.1f}s")
    print(f"  Analysis time:               {analyze_time:.1f}s")
    print(f"  Total time:                  {total_time:.1f}s")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
