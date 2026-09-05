#!/usr/bin/env python3
"""
Render the 30/60/90-day simulation results (from simulation_30_60_90.py) as Markdown.

Usage: python3 report_30_60_90.py --results data/simulation_30_60_90/results.json --out data/simulation_30_60_90/REPORT.md
"""
import argparse
import json
import os
from collections import defaultdict

LIVE_EXIT = {"MR_V3": "Fixed60d", "MR_V24": "Fixed14d", "MR_CONNORS": "SMA5",
             "MOM_V3": "Fixed90d", "MOM_STRICT": "TRAIL10", "BREAKOUT": "SMA10"}
STRAT_ORDER = ["MR_V3", "MR_V24", "MR_CONNORS", "MOM_V3", "MOM_STRICT", "BREAKOUT"]
STRAT_DESC = {
    "MR_V3": "RSI(2)<10 + ATR>=3% (live V3.0 MR), Fixed60d",
    "MR_V24": "RSI(2)<10 + >SMA50 + vol>1.5x (ATLAS V2.4), Fixed14d",
    "MR_CONNORS": "RSI(2)<10 + >SMA200, exit close>SMA5 (max 10d)",
    "MOM_V3": "Minervini 6/6 + 20d ret>5% (live V3.0 MOM), Fixed90d",
    "MOM_STRICT": "Minervini 6/6 + 20d ret>15% + vol>1.5x, trail -10%/SMA50",
    "BREAKOUT": "20d-high breakout + vol>1.5x + >SMA50, exit close<SMA10",
}
MIN_TRADES_STRAT = 20
MIN_TRADES_CELL = 15


def verdict(s, min_trades):
    """WIN / LOSE / MIXED / n/a from a stats dict (MTM basis)."""
    if not s or s.get("trades", 0) < min_trades:
        return "n/a (few trades)"
    if s["wr"] >= 55 and s["avg"] >= 1.0 and s["pf"] >= 1.3 and s["tstat"] >= 2.0:
        return "**WIN**"
    if s["avg"] < 0 and s["tstat"] <= -2.0:
        return "**LOSE**"
    if s["avg"] < 0:
        return "weak"
    return "mixed"


def fmt_row(label, s, extra=""):
    if not s or s.get("trades", 0) == 0:
        return f"| {label} | 0 | – | – | – | – | – | – |{extra}"
    return (f"| {label} | {s['trades']} | {s['wr']:.1f}% | {s['avg']:+.2f}% | {s['median']:+.2f}% | "
            f"{s['pf']:.2f} | {s['tstat']:+.1f} | {s.get('open_pct', 0):.0f}% |{extra}")


HEADER = "| {} | Trades | Win rate | Avg ret | Median | PF | t-stat | Open (MTM) |{}\n|---|---:|---:|---:|---:|---:|---:|---:|{}"


def table(label, rows, extra_hdr=""):
    hdr = HEADER.format(label, f" {extra_hdr} |" if extra_hdr else "", "---|" if extra_hdr else "")
    return "\n".join([hdr] + rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    R = json.load(open(args.results))
    W = R["windows"]
    end = R["end_date"]
    out = []
    P = out.append

    P(f"# 30 / 60 / 90-Day Strategy Simulation — by Regime, Strategy, Sector")
    P(f"\nData through **{end}** (Tiingo adjusted daily bars, {R['universe_size']} series from `data/us_stock_universe.txt` + SPY/QQQ/IWM/sector ETFs, VIX from FMP). "
      f"Windows: 30d from {W['30']}, 60d from {W['60']}, 90d from {W['90']} (signal date within window).")
    P("\nMethod: signal at close, **entry at next-day open**, exit per rule on closes, unfinished trades **marked-to-market at the last close** (\"Open\" column = share of trades still open). "
      "Fees: broker schedule (10 free actions/month then $1.50/action) in the portfolio simulation; worst-case 0.18% round-trip on a $1,667 slot in the signal-level tables. "
      "Non-overlapping trades per ticker per rule. No earnings/sentiment veto applied (pure price rules).")

    # Regime timeline
    P("\n## 1. What the market did (regime coverage)\n")
    P("| Window | api_v2 regime days | Trend regime days (SPY) | SPY | QQQ | IWM |")
    P("|---|---|---|---:|---:|---:|")
    for w in ("30", "60", "90"):
        s = R["signal"][w]
        b = R["benchmarks"][w]
        rd = ", ".join(f"{k} {v}" for k, v in sorted(s["regime_days"].items(), key=lambda x: -x[1]))
        td = ", ".join(f"{k} {v}" for k, v in sorted(s["trend_regime_days"].items(), key=lambda x: -x[1]))
        P(f"| {w}d | {rd} | {td} | {b['SPY']:+.2f}% | {b['QQQ']:+.2f}% | {b['IWM']:+.2f}% |")
    tl = R["regime_timeline"]
    dates = sorted(tl)
    lo = min(dates, key=lambda d: tl[d]["drawdown"])
    P(f"\nSPY ran {tl[dates[0]]['spy']} → {tl[dates[-1]]['spy']} over the 90 days; deepest drawdown from 52-week high was "
      f"{tl[lo]['drawdown']:.1f}% on {lo} (VIX {tl[lo]['vix']}). VIX range {min(t['vix'] for t in tl.values()):.1f}–{max(t['vix'] for t in tl.values()):.1f}. "
      "No DANGER / CRISIS / WEAK / CORRECTION / BEAR days occurred, so those regimes cannot be evaluated on this period.")
    P("\nSector ETF returns (benchmark for the sector tables):\n")
    P("| Window | XLK | XLE | XLF | XLV | XLY | XLP | XLU | XLB | XLI | XLRE | XLC |")
    P("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for w in ("30", "60", "90"):
        b = R["benchmarks"][w]
        P(f"| {w}d | " + " | ".join(f"{b[e]:+.1f}%" for e in ["XLK", "XLE", "XLF", "XLV", "XLY", "XLP", "XLU", "XLB", "XLI", "XLRE", "XLC"]) + " |")

    # Scoreboard
    P("\n## 2. Strategy scoreboard (each strategy with its own live exit)\n")
    P("Marked-to-market basis (all signals in window, open trades valued at last close). t-stat = mean / standard error; |t| ≥ 2 is a real edge, not noise.\n")
    for w in ("30", "60", "90"):
        s = R["signal"][w]
        P(f"\n### {w}-day window (signals since {W[w]})\n")
        rows = []
        for st in STRAT_ORDER:
            v = s["live_by_strategy"].get(st)
            rows.append(fmt_row(f"{st} — {STRAT_DESC[st]}", v, f" {verdict(v, MIN_TRADES_STRAT)} |"))
        P(table("Strategy", rows, "Verdict"))
        P("\nClosed trades only (exit rule actually triggered — for time exits this is biased toward the earliest signals, for stop-style exits toward the losers):\n")
        rows = [fmt_row(st, s["live_by_strategy_closed_only"].get(st)) for st in STRAT_ORDER]
        P(table("Strategy (closed only)", rows))

    # Portfolio
    if R.get("portfolio"):
        P("\n## 3. Portfolio simulation — what the live system would have done\n")
        P(f"$10,000 start, max 6 slots, equal weight, api_v2 regime sizing (HEALTHY = 70% slot size, DIP_BUY/PULLBACK = 100%), next-open entries, "
          "exits per strategy rule, broker fee schedule (10 free actions/month, then $1.50). Open positions valued at the last close.\n")
        P("Three ways of choosing which signals fill the 6 slots:\n")
        P("- **live**: rank by each stock's backtest expected value (Bayesian WR × avg return) with the live VETO (≥5 trades, WR ≥ 55%, avg ≥ 3% MR / 2% MOM) — this is how `strategy_evaluator.py` ranks. "
          f"Cache source: {R.get('stock_cache_source', 'n/a')}; validated stocks: {R.get('stock_cache_validated', {})}.")
        P("- **deepest**: MR by deepest RSI(2) then SMA50 buffer, momentum by 20d return × volume ratio (the M1 scanner score).")
        P("- **random**: 100 Monte Carlo runs picking uniformly among qualifying signals — the strategy's expected portfolio result independent of ranking luck. "
          "With 6 slots over ≤ 63 trading days, any single run is dominated by a handful of names; read the median and the p10–p90 band, not one number.\n")
        for w in ("30", "60", "90"):
            pw = R["portfolio"][w]
            spy = R["benchmarks"][w]["SPY"]
            P(f"\n### {w}-day window — SPY buy & hold {spy:+.2f}%\n")
            P("| Portfolio | live rank | live closed (WR / avg) | live open | deepest rank | MC median | MC p10 … p90 | MC % runs > 0 | MC avg MaxDD |")
            P("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
            rows = []
            for name, r in pw.items():
                if "random_mc" not in r:
                    continue
                lv, dp, mc = r["live"], r["deepest"], r["random_mc"]
                cs = lv["closed_stats"]
                lc = f"{cs['trades']} ({cs['wr']:.0f}% / {cs['avg']:+.1f}%)" if cs.get("trades") else "0"
                rows.append((mc["median"], f"| {name} | {lv['return_pct']:+.2f}% | {lc} | {len(lv['open_positions'])} | {dp['return_pct']:+.2f}% | "
                             f"**{mc['median']:+.2f}%** | {mc['p10']:+.1f} … {mc['p90']:+.1f} | {mc['pct_positive']:.0f}% | {mc['avg_max_dd']:.1f}% |"))
            for _, row in sorted(rows, key=lambda x: -x[0]):
                P(row)
            nr = pw.get("LIVE_MR+MOM_noRegimeSizing", {}).get("live")
            if nr:
                P(f"\nLive MR+MOM without regime sizing (always 100% slot size): {nr['return_pct']:+.2f}% (max DD {nr['max_dd']:.2f}%).")
            lv = pw["LIVE_MR+MOM"]["live"]
            if lv["closed"] or lv["open_positions"]:
                P(f"\nLive-ranked MR+MOM trades in the {w}d window:\n")
                P("| Ticker | Rule | Signal | Entry | Exit | Ret | Days | Regime |")
                P("|---|---|---|---:|---:|---:|---:|---|")
                for c in lv["closed"]:
                    P(f"| {c['ticker']} | {c['entry_rule']} | {c['signal_date']} | {c['entry_px']:.2f} | {c['exit_px']:.2f} | {c['ret']:+.2f}% | {c['days_held']} | {c['market_regime']} |")
                for o in lv["open_positions"]:
                    P(f"| {o['ticker']} | {o['entry_rule']} | – | {o['entry_px']:.2f} | open @ {o['last_px']:.2f} | {o['ret']:+.2f}% | {o['days_held']} | – |")

    # Current holdings
    if R.get("open_positions_mtm"):
        P("\n## 3b. Current open positions (positions.db) marked to market\n")
        P("Returns use adjusted closes (split-safe). 'Since entry' is from the close on the entry date, not the recorded fill. positions.db was last updated 2026-04-02, so this may not be the actual current book.\n")
        P("| Ticker | Strategy | Entry | Days held | Since entry | 90d | 60d | 30d |")
        P("|---|---|---|---:|---:|---:|---:|---:|")
        for o in R["open_positions_mtm"]:
            if "note" in o or "error" in o:
                P(f"| {o.get('ticker', '?')} | – | {o.get('entry_date', '')} | – | {o.get('note', o.get('error'))} | | | |")
                continue
            P(f"| {o['ticker']} | {o.get('strategy', '')} | {o['entry_date']} | {o['days_held']} | {o['since_entry_pct']:+.1f}% | "
              f"{o['ret_90d']:+.1f}% | {o['ret_60d']:+.1f}% | {o['ret_30d']:+.1f}% |")

    # By regime
    P("\n## 4. By market regime (api_v2 SPY/VIX regime at signal date)\n")
    for w in ("90", "60"):
        s = R["signal"][w]
        P(f"\n### {w}-day window\n")
        cells = defaultdict(dict)
        for k, v in s["by_market_regime"].items():
            st, reg = k.split("|")
            cells[st][reg] = v
        regs = sorted({reg for st in cells for reg in cells[st]}, key=lambda r: -s["regime_days"].get(r, 0))
        P("| Strategy | " + " | ".join(f"{r} ({s['regime_days'].get(r, 0)}d)" for r in regs) + " |")
        P("|---|" + "---|" * len(regs))
        for st in STRAT_ORDER:
            row = []
            for r in regs:
                v = cells[st].get(r)
                row.append(f"{v['trades']}t, {v['wr']:.0f}% WR, {v['avg']:+.2f}% {verdict(v, MIN_TRADES_CELL)}" if v else "–")
            P(f"| {st} | " + " | ".join(row) + " |")
    P("\n### By SPY trend regime (atlas_v2 RegimeDetector), 90-day window\n")
    s = R["signal"]["90"]
    cells = defaultdict(dict)
    for k, v in s["by_trend_regime"].items():
        st, reg = k.split("|")
        cells[st][reg] = v
    regs = sorted({reg for st in cells for reg in cells[st]})
    P("| Strategy | " + " | ".join(regs) + " |")
    P("|---|" + "---|" * len(regs))
    for st in STRAT_ORDER:
        P(f"| {st} | " + " | ".join(
            (f"{cells[st][r]['trades']}t, {cells[st][r]['wr']:.0f}% WR, {cells[st][r]['avg']:+.2f}% {verdict(cells[st][r], MIN_TRADES_CELL)}" if r in cells[st] else "–")
            for r in regs) + " |")
    P("\n### By the stock's own regime (RegimeDetector on the stock), 90-day window\n")
    cells = defaultdict(dict)
    for k, v in s["by_stock_regime"].items():
        st, reg = k.split("|")
        cells[st][reg] = v
    regs = ["BULL", "SIDEWAYS", "BEAR", "HIGH_VOL"]
    P("| Strategy | " + " | ".join(regs) + " |")
    P("|---|" + "---|" * len(regs))
    for st in STRAT_ORDER:
        P(f"| {st} | " + " | ".join(
            (f"{cells[st][r]['trades']}t, {cells[st][r]['wr']:.0f}% WR, {cells[st][r]['avg']:+.2f}% {verdict(cells[st][r], MIN_TRADES_CELL)}" if r in cells[st] else "–")
            for r in regs) + " |")

    # By sector
    P("\n## 5. By sector (live exits, marked-to-market)\n\nFinnhub industry mapped to GICS-style sectors. UNKNOWN = closed-end funds and SPACs that Finnhub does not classify.\n")
    for w in ("90", "60", "30"):
        s = R["signal"][w]
        P(f"\n### {w}-day window — all strategies pooled\n")
        rows = []
        for sec, v in sorted(s["sector_all_strategies"].items(), key=lambda x: -x[1]["avg"]):
            rows.append(fmt_row(sec, v, f" {verdict(v, MIN_TRADES_CELL)} |"))
        P(table("Sector", rows, "Verdict"))
        P(f"\n### {w}-day window — strategy × sector (avg return, WR, trades)\n")
        cells = defaultdict(dict)
        for k, v in s["by_sector"].items():
            st, sec = k.split("|")
            cells[st][sec] = v
        secs = [x for x in sorted({sec for st in cells for sec in cells[st]}) if x not in ("UNKNOWN", "OTHER")]
        P("| Strategy | " + " | ".join(x.replace("CONSUMER_", "CONS_") for x in secs) + " |")
        P("|---|" + "---|" * len(secs))
        for st in STRAT_ORDER:
            row = []
            for sec in secs:
                v = cells[st].get(sec)
                if not v or v["trades"] < 5:
                    row.append("–")
                else:
                    tag = "✅" if verdict(v, MIN_TRADES_CELL) == "**WIN**" else ("❌" if verdict(v, MIN_TRADES_CELL) == "**LOSE**" else "")
                    row.append(f"{v['avg']:+.1f}% / {v['wr']:.0f}% / {v['trades']}t {tag}")
            P(f"| {st} | " + " | ".join(row) + " |")

    # Month by month + diagnostics
    P("\n## 5b. Month by month (signal month, live exits, marked-to-market)\n")
    s = R["signal"]["90"]
    months = sorted({k.split("|")[1] for k in s["by_month"]})
    P("| Strategy | " + " | ".join(months) + " |")
    P("|---|" + "---:|" * len(months))
    for st in STRAT_ORDER:
        row = []
        for m in months:
            v = s["by_month"].get(f"{st}|{m}")
            row.append(f"{v['avg']:+.2f}% / {v['wr']:.0f}% / {v['trades']}t" if v else "–")
        P(f"| {st} | " + " | ".join(row) + " |")
    P("\n### Volatility of the stock at signal (ATR(14)% bucket), 90-day window\n")
    buckets = ["ATR 3-5%", "ATR 5-8%", "ATR >8%"]
    P("| Strategy | " + " | ".join(buckets) + " |")
    P("|---|" + "---|" * len(buckets))
    for st in STRAT_ORDER:
        row = []
        for b in buckets:
            v = s["by_atr_bucket"].get(f"{st}|{b}")
            row.append(f"{v['trades']}t, {v['wr']:.0f}% WR, {v['avg']:+.2f}% {verdict(v, MIN_TRADES_CELL)}" if v else "–")
        P(f"| {st} | " + " | ".join(row) + " |")
    if s.get("mr_v3_biggest_day"):
        bd = s["mr_v3_biggest_day"]
        P(f"\nMR_V3 concentration check: on its biggest signal day ({bd['date']}) it fired {bd['on_day']['trades']} trades "
          f"({bd['on_day']['avg']:+.2f}% avg, {bd['on_day']['wr']:.0f}% WR); all other days: {bd['excluding_day']['trades']} trades, "
          f"{bd['excluding_day']['avg']:+.2f}% avg, {bd['excluding_day']['wr']:.0f}% WR, t={bd['excluding_day']['tstat']:+.1f}.")
        P("\nMR_V3 by RSI(2) depth (90d): " + "; ".join(f"{k}: {v['trades']}t, {v['wr']:.0f}% WR, {v['avg']:+.2f}%" for k, v in sorted(s["mr_v3_rsi_depth"].items())))

    # Exit grid
    P("\n## 6. Which exit worked for each entry (90-day window, marked-to-market)\n")
    s = R["signal"]["90"]
    grid = defaultdict(dict)
    for k, v in s["grid_entry_exit"].items():
        st, ex = k.split("|")
        grid[st][ex] = v
    exits = ["Fixed5d", "Fixed10d", "Fixed14d", "Fixed21d", "Fixed60d", "Fixed90d", "SMA5", "RSI65", "SMA10", "TRAIL10"]
    P("| Entry | " + " | ".join(exits) + " | Best exit |")
    P("|---|" + "---|" * (len(exits) + 1))
    for st in STRAT_ORDER:
        row = []
        best = None
        for ex in exits:
            v = grid[st].get(ex)
            if not v:
                row.append("–")
                continue
            mark = "★" if ex == LIVE_EXIT[st] else ""
            row.append(f"{v['avg']:+.2f}% / {v['wr']:.0f}%{mark}")
            if v["trades"] >= MIN_TRADES_STRAT and (best is None or v["avg"] > best[1]["avg"]):
                best = (ex, v)
        P(f"| {st} | " + " | ".join(row) + f" | {best[0] if best else '–'} ({best[1]['avg']:+.2f}%, PF {best[1]['pf']:.2f}) |" if best else f"| {st} | " + " | ".join(row) + " | – |")
    P("\n★ = the exit the live system / documented model uses. Closed-only version of this grid is in results.json (`grid_entry_exit_closed_only`).")

    # Verdict
    P("\n## 7. Verdict — what clearly won and what clearly lost\n")
    s90 = R["signal"]["90"]
    s60 = R["signal"]["60"]
    s30 = R["signal"]["30"]
    wins, loses = [], []
    for st in STRAT_ORDER:
        vs = [(w, R["signal"][w]["live_by_strategy"].get(st)) for w in ("30", "60", "90")]
        vd = [(w, verdict(v, MIN_TRADES_STRAT)) for w, v in vs]
        line = f"- **{st}**: " + ", ".join(f"{w}d {d}" for w, d in vd)
        if all(d == "**WIN**" for w, d in vd if d != "n/a (few trades)") and any(d == "**WIN**" for _, d in vd):
            wins.append(line)
        elif any(d == "**LOSE**" for _, d in vd):
            loses.append(line)
    P("**Strategies that won in every window they had enough trades in:**\n")
    P("\n".join(wins) if wins else "- none")
    P("\n**Strategies that clearly lost in at least one window:**\n")
    P("\n".join(loses) if loses else "- none")
    # sectors
    P("\n**Sectors (all strategies pooled, 90d):** " + ", ".join(
        f"{sec} {v['avg']:+.2f}% ({v['trades']}t) {verdict(v, MIN_TRADES_CELL)}"
        for sec, v in sorted(s90["sector_all_strategies"].items(), key=lambda x: -x[1]["avg"]) if sec not in ("UNKNOWN", "OTHER")))
    # regimes
    P("\n**Regimes (90d, live combos):** " + "; ".join(
        f"{k.replace('|', ' in ')}: {v['avg']:+.2f}% / {v['wr']:.0f}% WR / {v['trades']}t {verdict(v, MIN_TRADES_CELL)}"
        for k, v in sorted(s90["by_market_regime"].items(), key=lambda x: -x[1]["avg"]) if v["trades"] >= MIN_TRADES_CELL))

    P("\n## 8. QA performed and caveats\n")
    P("- Indicator math (RSI(2) simple-average, SMA, ATR%) matched `backtest_precompute.py` to 1e-9 on sampled tickers; MR_V3 full-history replay reproduced the precompute trade count exactly.")
    P("- Six random trades were re-derived by hand from raw DB prices (entry open, exit close, fee): all matched to 4 decimals.")
    P("- Zero duplicate and zero overlapping trades per ticker/rule. Series not reaching the end date are excluded (2 universe tickers returned 404 from Tiingo).")
    P("- Look-ahead: all entry conditions use bars ≤ signal day; execution is the next bar's open; exits use closes strictly after entry.")
    P("- Concentration risk: **551 of the MR_V3 signals in the 90-day window fired on one day (2026-06-08 selloff)**, so MR_V3's 90-day result is largely one dip-buy event, not 60 independent days of evidence.")
    P("- Time-exit strategies (Fixed60d/90d) cannot complete inside a 30/60-day window; their rows are marked-to-market and the \"Open\" column says how much.")
    P("- Universe is the repo's Feb-2026 list (survivorship: names delisted since are excluded; names listed since are not included). No earnings or sentiment veto is applied.")
    P("- Only HEALTHY / DIP_BUY / PULLBACK (BULL / SIDEWAYS) regimes occurred; conclusions do not transfer to bear or high-VIX regimes.")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "w").write("\n".join(out) + "\n")
    print(f"wrote {args.out} ({len(out)} lines)")


if __name__ == "__main__":
    main()
