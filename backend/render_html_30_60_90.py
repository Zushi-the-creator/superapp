#!/usr/bin/env python3
"""Render simulation results.json as a standalone HTML page (for sharing / Artifact publishing).
Usage: python3 render_html_30_60_90.py --results results.json --out report.html
"""
import argparse
import html
import json
from collections import defaultdict

STRATS = ["MR_V3", "MR_V24", "MR_CONNORS", "MOM_V3", "MOM_STRICT", "BREAKOUT"]
DESC = {
    "MR_V3": ("Live MR (V3.0)", "RSI(2)&lt;10 · ATR≥3% · Fixed 60d"),
    "MR_V24": ("ATLAS V2.4 MR", "RSI(2)&lt;10 · &gt;SMA50 · vol&gt;1.5× · Fixed 14d"),
    "MR_CONNORS": ("Connors classic", "RSI(2)&lt;10 · &gt;SMA200 · exit &gt;SMA5"),
    "MOM_V3": ("Live momentum (V3.0)", "Minervini 6/6 · 20d&gt;5% · Fixed 90d"),
    "MOM_STRICT": ("M1 momentum", "Minervini 6/6 · 20d&gt;15% · vol&gt;1.5× · trail −10%"),
    "BREAKOUT": ("Breakout", "20d high · vol&gt;1.5× · &gt;SMA50 · exit &lt;SMA10"),
}
LIVE_EXIT = {"MR_V3": "Fixed60d", "MR_V24": "Fixed14d", "MR_CONNORS": "SMA5", "MOM_V3": "Fixed90d", "MOM_STRICT": "TRAIL10", "BREAKOUT": "SMA10"}


def verdict(s, min_trades=20):
    if not s or s.get("trades", 0) < min_trades:
        return ("na", "few trades")
    if s["wr"] >= 55 and s["avg"] >= 1.0 and s["pf"] >= 1.3 and s["tstat"] >= 2.0:
        return ("win", "WIN")
    if s["avg"] < 0 and s["tstat"] <= -2.0:
        return ("lose", "LOSE")
    if s["avg"] < 0:
        return ("weak", "weak")
    return ("mixed", "mixed")


def pill(s, min_trades=20):
    cls, txt = verdict(s, min_trades)
    return f'<span class="pill {cls}">{txt}</span>'


def num(x, fmt="{:+.2f}%", cls=True):
    if x is None:
        return "–"
    c = "pos" if x > 0 else ("neg" if x < 0 else "")
    return f'<span class="{c}">{fmt.format(x)}</span>' if cls else fmt.format(x)


def cell(v, min_trades=15):
    if not v or v.get("trades", 0) == 0:
        return "<td class='dim'>–</td>"
    return f"<td>{num(v['avg'])} <small>{v['wr']:.0f}% · {v['trades']}t</small> {pill(v, min_trades)}</td>"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    R = json.load(open(a.results))
    W = R["windows"]
    B = R["benchmarks"]
    S = R["signal"]
    o = []
    P = o.append

    P("""<title>Regime · Strategy · Sector Simulation</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{--bg:#f7f6f2;--bg2:#efede6;--ink:#1c2230;--ink2:#4a5263;--mute:#7c8494;--line:#d9d6cc;--acc:#1f4e79;--win:#1e7a4f;--winbg:#e2f1e8;--lose:#a8342e;--losebg:#f6e3e0;--mix:#8a6d1f;--mixbg:#f3ead0;--card:#ffffff;}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#15181e;--bg2:#1c2028;--ink:#e8e6df;--ink2:#b8b6ad;--mute:#8b8f99;--line:#333842;--acc:#8fb6dc;--win:#6fcf97;--winbg:#1b3327;--lose:#f08a80;--losebg:#3d1f1c;--mix:#e0b94f;--mixbg:#3a3012;--card:#1c2028;}}
:root[data-theme="dark"]{--bg:#15181e;--bg2:#1c2028;--ink:#e8e6df;--ink2:#b8b6ad;--mute:#8b8f99;--line:#333842;--acc:#8fb6dc;--win:#6fcf97;--winbg:#1b3327;--lose:#f08a80;--losebg:#3d1f1c;--mix:#e0b94f;--mixbg:#3a3012;--card:#1c2028;}
body{background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:15px;line-height:1.5;margin:0}
main{max-width:1080px;margin:0 auto;padding:40px 24px 80px}
h1{font-family:"Source Serif 4",Georgia,serif;font-weight:600;font-size:2.1rem;line-height:1.15;margin:0 0 6px;text-wrap:balance}
h2{font-family:"Source Serif 4",Georgia,serif;font-weight:600;font-size:1.45rem;margin:48px 0 10px;text-wrap:balance}
h3{font-size:1rem;font-weight:600;margin:26px 0 8px;color:var(--ink2)}
.eyebrow{font-size:.74rem;letter-spacing:.09em;text-transform:uppercase;color:var(--mute);font-weight:600}
.lede{color:var(--ink2);max-width:68ch;margin:0 0 18px}
p{max-width:72ch}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:22px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:14px 16px}
.tile .k{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);font-weight:600}
.tile .v{font-family:"IBM Plex Mono",monospace;font-size:1.5rem;font-weight:500;margin:4px 0 2px}
.tile .s{font-size:.82rem;color:var(--ink2)}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top;white-space:nowrap}
th{font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;color:var(--mute);font-weight:600;background:var(--bg2);position:sticky;top:0}
td:first-child,th:first-child{text-align:left;white-space:normal;min-width:150px}
tr:last-child td{border-bottom:0}
td{font-family:"IBM Plex Mono",monospace;font-variant-numeric:tabular-nums}
td:first-child{font-family:"IBM Plex Sans",system-ui,sans-serif}
td small{color:var(--mute);font-size:.76rem}
.pos{color:var(--win)}.neg{color:var(--lose)}.dim{color:var(--mute)}
.pill{display:inline-block;font-family:"IBM Plex Sans",sans-serif;font-size:.66rem;font-weight:600;letter-spacing:.05em;padding:1px 7px;border-radius:10px;vertical-align:middle}
.pill.win{background:var(--winbg);color:var(--win)}.pill.lose{background:var(--losebg);color:var(--lose)}.pill.mixed,.pill.weak{background:var(--mixbg);color:var(--mix)}.pill.na{background:var(--bg2);color:var(--mute)}
.name{font-weight:600}.sub{display:block;color:var(--mute);font-size:.76rem;font-weight:400}
.callout{border-left:3px solid var(--acc);background:var(--bg2);padding:12px 16px;margin:18px 0;border-radius:0 6px 6px 0;max-width:80ch}
.vgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px 18px;margin-top:6px;font-family:"IBM Plex Mono",monospace;font-size:.86rem;font-variant-numeric:tabular-nums}
@media (max-width:720px){.vgrid{grid-template-columns:1fr}}
.callout.lose{border-color:var(--lose)}.callout.win{border-color:var(--win)}
ul{max-width:80ch;padding-left:20px}li{margin:6px 0;max-width:80ch}
.star{color:var(--acc);font-weight:600}
@media (max-width:720px){.tiles{grid-template-columns:1fr}}
</style>
<main>""")
    P(f'<div class="eyebrow">SuperApp · ATLAS backtest lab · data through {R["end_date"]}</div>')
    P("<h1>Regime · Strategy · Sector Simulation, last 30 / 60 / 90 days</h1>")
    P(f'<p class="lede">{R["universe_size"]} price series (repo universe + SPY/QQQ/IWM + sector ETFs), Tiingo adjusted daily bars. '
      "Every entry rule the repo defines, run with proper next-day-open entries and rule-based exits, then tagged by market regime, the stock's own regime, and sector. "
      "Unfinished trades are marked to market at the last close. Fees follow the broker schedule: 10 free actions a month, then $1.50 per action.</p>")

    # Tiles: per window, SPY vs best strategy
    P('<div class="tiles">')
    for w in ("30", "60", "90"):
        s = S[w]["live_by_strategy"]
        best = max(((k, v) for k, v in s.items() if v.get("trades", 0) >= 20), key=lambda kv: kv[1]["avg"])
        worst = min(((k, v) for k, v in s.items() if v.get("trades", 0) >= 20), key=lambda kv: kv[1]["avg"])
        regs = ", ".join(f"{k} {v}d" for k, v in sorted(S[w]["regime_days"].items(), key=lambda x: -x[1]))
        P(f'<div class="tile"><div class="k">{w}-day window · since {W[w]}</div><div class="v">SPY {num(B[w]["SPY"])}</div>'
          f'<div class="s">Best: <b>{best[0]}</b> {num(best[1]["avg"])} avg/trade ({best[1]["wr"]:.0f}% WR, {best[1]["trades"]}t)<br>'
          f'Worst: <b>{worst[0]}</b> {num(worst[1]["avg"])} ({worst[1]["wr"]:.0f}% WR)<br><span class="dim">{regs}</span></div></div>')
    P("</div>")

    # Executive summary (from summary.html next to results, if present)
    import os as _os
    sp = _os.path.join(_os.path.dirname(_os.path.abspath(a.results)), "summary.html")
    if _os.path.exists(sp):
        P(open(sp).read())

    # Verdict callouts
    P("<h2>Verdict</h2>")
    s90, s60, s30 = S["90"]["live_by_strategy"], S["60"]["live_by_strategy"], S["30"]["live_by_strategy"]
    for st in STRATS:
        vs = [(w, S[w]["live_by_strategy"].get(st)) for w in ("30", "60", "90")]
        cls = "win" if all(verdict(v)[0] in ("win", "na") for _, v in vs) and any(verdict(v)[0] == "win" for _, v in vs) else (
            "lose" if any(verdict(v)[0] == "lose" for _, v in vs) else "")
        line = "".join(f"<div><span class='dim'>{w}d</span> {num(v['avg'])} avg · {v['wr']:.0f}% WR · {v['trades']}t {pill(v)}</div>" if v else f"<div><span class='dim'>{w}d</span> –</div>" for w, v in vs)
        P(f'<div class="callout {cls}"><span class="name">{st}</span> <span class="sub">{DESC[st][1]}</span><div class="vgrid">{line}</div></div>')

    # Regime coverage
    P("<h2>What the market did</h2>")
    tl = R["regime_timeline"]
    dates = sorted(tl)
    lo = min(dates, key=lambda d: tl[d]["drawdown"])
    P(f"<p>SPY {tl[dates[0]]['spy']} → {tl[dates[-1]]['spy']} over 90 days. Deepest drawdown from the 52-week high was {tl[lo]['drawdown']:.1f}% on {lo} (VIX {tl[lo]['vix']}). "
      f"VIX stayed between {min(t['vix'] for t in tl.values()):.1f} and {max(t['vix'] for t in tl.values()):.1f}. "
      "No DANGER, CRISIS, WEAK, CORRECTION or BEAR days occurred, so nothing here says how these rules behave in a bear market.</p>")
    P('<div class="wrap"><table><tr><th>Window</th><th>api_v2 regime days</th><th>SPY trend days</th><th>SPY</th><th>QQQ</th><th>IWM</th>'
      + "".join(f"<th>{e}</th>" for e in ["XLK", "XLE", "XLF", "XLV", "XLY", "XLP", "XLU", "XLB", "XLI", "XLRE", "XLC"]) + "</tr>")
    for w in ("30", "60", "90"):
        rd = ", ".join(f"{k} {v}" for k, v in sorted(S[w]["regime_days"].items(), key=lambda x: -x[1]))
        td = ", ".join(f"{k} {v}" for k, v in sorted(S[w]["trend_regime_days"].items(), key=lambda x: -x[1]))
        P(f"<tr><td>{w}d</td><td style='text-align:left;white-space:normal'>{rd}</td><td style='text-align:left'>{td}</td>"
          + "".join(f"<td>{num(B[w][e], '{:+.1f}%')}</td>" for e in ["SPY", "QQQ", "IWM", "XLK", "XLE", "XLF", "XLV", "XLY", "XLP", "XLU", "XLB", "XLI", "XLRE", "XLC"]) + "</tr>")
    P("</table></div>")

    # Scoreboard
    P("<h2>Strategy scoreboard</h2><p>Each strategy with the exit it actually uses. Marked-to-market: every signal in the window counts, open trades valued at the last close. "
      "t-stat is mean ÷ standard error; beyond ±2 the sign is not noise.</p>")
    for w in ("30", "60", "90"):
        P(f"<h3>{w}-day window · signals since {W[w]}</h3>")
        P('<div class="wrap"><table><tr><th>Strategy</th><th>Trades</th><th>Win rate</th><th>Avg</th><th>Median</th><th>PF</th><th>t</th><th>Open</th><th>Closed-only avg / WR</th><th>Verdict</th></tr>')
        for st in STRATS:
            v = S[w]["live_by_strategy"].get(st)
            c = S[w]["live_by_strategy_closed_only"].get(st)
            co = f"{num(c['avg'])} / {c['wr']:.0f}% ({c['trades']}t)" if c and c.get("trades") else "–"
            if not v:
                P(f"<tr><td><span class='name'>{st}</span><span class='sub'>{DESC[st][1]}</span></td><td colspan=9 class='dim'>no signals</td></tr>")
                continue
            P(f"<tr><td><span class='name'>{st}</span><span class='sub'>{DESC[st][1]}</span></td><td>{v['trades']}</td><td>{v['wr']:.1f}%</td><td>{num(v['avg'])}</td>"
              f"<td>{num(v['median'])}</td><td>{v['pf']:.2f}</td><td>{v['tstat']:+.1f}</td><td>{v['open_pct']:.0f}%</td><td>{co}</td><td>{pill(v)}</td></tr>")
        P("</table></div>")

    # Portfolio
    if R.get("portfolio"):
        P("<h2>Portfolio simulation, live mechanics</h2>")
        P(f"<p>$10,000, max 6 slots, equal weight, api_v2 regime sizing (HEALTHY = 70% slot, DIP_BUY/PULLBACK = 100%), next-open entries, exits per rule, broker fee schedule. "
          f"<b>live</b> ranks by each stock's backtest expected value with the live veto, exactly how the evaluator ranks (10-year cache, cutoff {W['90']}; validated MR {R.get('stock_cache_validated', {}).get('mr', '?')}, MOM {R.get('stock_cache_validated', {}).get('mom', '?')} stocks). "
          "<b>deepest</b> ranks by deepest RSI(2) / strongest momentum score. <b>MC</b> is 100 random draws among qualifying signals: the band a 6-slot book can land in regardless of ranking luck.</p>")
        for w in ("30", "60", "90"):
            pw = R["portfolio"][w]
            P(f"<h3>{w}-day window · SPY buy &amp; hold {num(B[w]['SPY'])}</h3>")
            P('<div class="wrap"><table><tr><th>Portfolio</th><th>live rank</th><th>live closed (WR / avg)</th><th>open</th><th>deepest</th><th>MC median</th><th>MC p10 … p90</th><th>MC runs &gt; 0</th><th>MC avg max DD</th></tr>')
            rows = []
            for name, r in pw.items():
                if "random_mc" not in r:
                    continue
                lv, dp, mc = r["live"], r["deepest"], r["random_mc"]
                cs = lv["closed_stats"]
                lc = f"{cs['trades']} ({cs['wr']:.0f}% / {cs['avg']:+.1f}%)" if cs.get("trades") else "0"
                rows.append((mc["median"], f"<tr><td class='name'>{name}</td><td>{num(lv['return_pct'])}</td><td>{lc}</td><td>{len(lv['open_positions'])}</td><td>{num(dp['return_pct'])}</td>"
                             f"<td><b>{num(mc['median'])}</b></td><td>{mc['p10']:+.1f} … {mc['p90']:+.1f}</td><td>{mc['pct_positive']:.0f}%</td><td>{mc['avg_max_dd']:.1f}%</td></tr>"))
            for _, row in sorted(rows, key=lambda x: -x[0]):
                P(row)
            P("</table></div>")
            lv = pw["LIVE_MR+MOM"]["live"]
            if lv["closed"] or lv["open_positions"]:
                P(f"<h3>Live-ranked MR+MOM book, {w}d</h3><div class='wrap'><table><tr><th>Ticker</th><th>Rule</th><th>Signal</th><th>Entry</th><th>Exit</th><th>Return</th><th>Days</th></tr>")
                for c in lv["closed"]:
                    P(f"<tr><td class='name'>{c['ticker']}</td><td>{c['entry_rule']}</td><td>{c['signal_date']}</td><td>{c['entry_px']:.2f}</td><td>{c['exit_px']:.2f} <small>{c['exit_date']}</small></td><td>{num(c['ret'])}</td><td>{c['days_held']}</td></tr>")
                for x in lv["open_positions"]:
                    P(f"<tr><td class='name'>{x['ticker']}</td><td>{x['entry_rule']}</td><td>–</td><td>{x['entry_px']:.2f} <small>{x['entry_date']}</small></td><td>open @ {x['last_px']:.2f}</td><td>{num(x['ret'])}</td><td>{x['days_held']}</td></tr>")
                P("</table></div>")

    # Regimes
    P("<h2>By market regime</h2><p>api_v2's SPY/VIX regime on the signal date. Only three regimes occurred.</p>")
    for w in ("90", "60"):
        s = S[w]
        cells = defaultdict(dict)
        for k, v in s["by_market_regime"].items():
            st, reg = k.split("|")
            cells[st][reg] = v
        regs = sorted({reg for st in cells for reg in cells[st]}, key=lambda r: -s["regime_days"].get(r, 0))
        P(f"<h3>{w}-day window</h3><div class='wrap'><table><tr><th>Strategy</th>" + "".join(f"<th>{r} · {s['regime_days'].get(r, 0)}d</th>" for r in regs) + "</tr>")
        for st in STRATS:
            P(f"<tr><td class='name'>{st}</td>" + "".join(cell(cells[st].get(r)) for r in regs) + "</tr>")
        P("</table></div>")
    s = S["90"]
    for key, title, regs in (("by_trend_regime", "By SPY trend regime (atlas_v2 RegimeDetector), 90d", None),
                             ("by_stock_regime", "By the stock's own regime, 90d", ["BULL", "SIDEWAYS", "BEAR", "HIGH_VOL"])):
        cells = defaultdict(dict)
        for k, v in s[key].items():
            st, reg = k.split("|")
            cells[st][reg] = v
        regs = regs or sorted({reg for st in cells for reg in cells[st]})
        P(f"<h3>{title}</h3><div class='wrap'><table><tr><th>Strategy</th>" + "".join(f"<th>{r}</th>" for r in regs) + "</tr>")
        for st in STRATS:
            P(f"<tr><td class='name'>{st}</td>" + "".join(cell(cells[st].get(r)) for r in regs) + "</tr>")
        P("</table></div>")

    # Sectors
    P("<h2>By sector</h2><p>Finnhub industry mapped to GICS-style sectors; UNKNOWN is closed-end funds and SPACs that Finnhub does not classify. All strategies pooled first, then strategy × sector.</p>")
    for w in ("90", "60", "30"):
        s = S[w]
        P(f"<h3>{w}-day window · all strategies pooled</h3><div class='wrap'><table><tr><th>Sector</th><th>Trades</th><th>Win rate</th><th>Avg</th><th>Median</th><th>PF</th><th>t</th><th>Sector ETF</th><th>Verdict</th></tr>")
        etf = {"TECHNOLOGY": "XLK", "ENERGY": "XLE", "FINANCIALS": "XLF", "HEALTHCARE": "XLV", "CONSUMER_DISCRETIONARY": "XLY", "CONSUMER_STAPLES": "XLP",
               "UTILITIES": "XLU", "MATERIALS": "XLB", "INDUSTRIALS": "XLI", "REAL_ESTATE": "XLRE", "COMMUNICATION": "XLC"}
        for sec, v in sorted(s["sector_all_strategies"].items(), key=lambda x: -x[1]["avg"]):
            e = etf.get(sec)
            P(f"<tr><td class='name'>{sec}</td><td>{v['trades']}</td><td>{v['wr']:.1f}%</td><td>{num(v['avg'])}</td><td>{num(v['median'])}</td><td>{v['pf']:.2f}</td><td>{v['tstat']:+.1f}</td>"
              f"<td>{(e + ' ' + num(B[w][e], '{:+.1f}%')) if e else '–'}</td><td>{pill(v, 15)}</td></tr>")
        P("</table></div>")
        cells = defaultdict(dict)
        for k, v in s["by_sector"].items():
            st, sec = k.split("|")
            cells[st][sec] = v
        secs = [x for x in sorted({sec for st in cells for sec in cells[st]}) if x not in ("UNKNOWN", "OTHER")]
        P(f"<h3>{w}-day window · strategy × sector</h3><div class='wrap'><table><tr><th>Strategy</th>" + "".join(f"<th>{x.replace('CONSUMER_', 'CONS_')}</th>" for x in secs) + "</tr>")
        for st in STRATS:
            P(f"<tr><td class='name'>{st}</td>" + "".join(cell(cells[st].get(sec)) if cells[st].get(sec, {}).get("trades", 0) >= 5 else "<td class='dim'>–</td>" for sec in secs) + "</tr>")
        P("</table></div>")

    # Month + ATR
    s = S["90"]
    months = sorted({k.split("|")[1] for k in s["by_month"]})
    P("<h2>Month by month and volatility</h2>")
    P("<div class='wrap'><table><tr><th>Strategy</th>" + "".join(f"<th>{m}</th>" for m in months) + "</tr>")
    for st in STRATS:
        P(f"<tr><td class='name'>{st}</td>" + "".join(cell(s["by_month"].get(f"{st}|{m}")) for m in months) + "</tr>")
    P("</table></div>")
    buckets = ["ATR 3-5%", "ATR 5-8%", "ATR >8%"]
    P("<h3>Stock volatility at signal (ATR(14)% of price), 90d</h3><div class='wrap'><table><tr><th>Strategy</th>" + "".join(f"<th>{b}</th>" for b in buckets) + "</tr>")
    for st in STRATS:
        P(f"<tr><td class='name'>{st}</td>" + "".join(cell(s["by_atr_bucket"].get(f"{st}|{b}")) for b in buckets) + "</tr>")
    P("</table></div>")
    if s.get("mr_v3_biggest_day"):
        bd = s["mr_v3_biggest_day"]
        P(f"<div class='callout'>MR_V3 concentration: its biggest signal day ({bd['date']}) produced {bd['on_day']['trades']} trades at {bd['on_day']['avg']:+.2f}% avg ({bd['on_day']['wr']:.0f}% WR). "
          f"All other days: {bd['excluding_day']['trades']} trades, {bd['excluding_day']['avg']:+.2f}% avg, {bd['excluding_day']['wr']:.0f}% WR, t = {bd['excluding_day']['tstat']:+.1f}.</div>")

    # Exit grid
    P("<h2>Which exit worked for each entry, 90d</h2><p>Avg return / win rate per exit. <span class='star'>★</span> marks the exit the live system or documented model uses.</p>")
    grid = defaultdict(dict)
    for k, v in s["grid_entry_exit"].items():
        st, ex = k.split("|")
        grid[st][ex] = v
    exits = ["Fixed5d", "Fixed10d", "Fixed14d", "Fixed21d", "Fixed60d", "Fixed90d", "SMA5", "RSI65", "SMA10", "TRAIL10"]
    P("<div class='wrap'><table><tr><th>Entry</th>" + "".join(f"<th>{e}</th>" for e in exits) + "<th>Best (≥20t)</th></tr>")
    for st in STRATS:
        best = None
        row = []
        for ex in exits:
            v = grid[st].get(ex)
            if not v:
                row.append("<td class='dim'>–</td>")
                continue
            star = " <span class='star'>★</span>" if ex == LIVE_EXIT[st] else ""
            row.append(f"<td>{num(v['avg'])} <small>{v['wr']:.0f}%</small>{star}</td>")
            if v["trades"] >= 20 and (best is None or v["avg"] > best[1]["avg"]):
                best = (ex, v)
        P(f"<tr><td class='name'>{st}</td>" + "".join(row) + (f"<td class='name'>{best[0]} <small>{best[1]['avg']:+.2f}%, PF {best[1]['pf']:.2f}</small></td>" if best else "<td>–</td>") + "</tr>")
    P("</table></div>")

    # Holdings
    if R.get("open_positions_mtm"):
        P("<h2>Open positions in positions.db, marked to market</h2><p>Adjusted closes (split-safe); positions.db was last updated 2026-04-02 and may not be the current book.</p>")
        P("<div class='wrap'><table><tr><th>Ticker</th><th>Entry</th><th>Days</th><th>Since entry</th><th>90d</th><th>60d</th><th>30d</th></tr>")
        for x in R["open_positions_mtm"]:
            if "note" in x or "error" in x:
                continue
            P(f"<tr><td class='name'>{x['ticker']}</td><td>{x['entry_date']}</td><td>{x['days_held']}</td><td>{num(x['since_entry_pct'], '{:+.1f}%')}</td><td>{num(x['ret_90d'], '{:+.1f}%')}</td><td>{num(x['ret_60d'], '{:+.1f}%')}</td><td>{num(x['ret_30d'], '{:+.1f}%')}</td></tr>")
        P("</table></div>")

    # QA
    P("<h2>QA performed and caveats</h2><ul>")
    for li in [
        "Indicator math (simple-average RSI(2), SMA, ATR%) matched <code>backtest_precompute.py</code> to 1e-9; the MR_V3 full-history replay reproduced the precompute trade count exactly.",
        "Random trades re-derived by hand from raw DB prices (next-day open entry, exit close, fee): all matched. Zero duplicate and zero overlapping trades per ticker and rule.",
        "Portfolio mechanics: every simulated fill re-derived from raw prices, fee allowance verified per month, only cache-validated stocks with a same-day signal were bought.",
        "No look-ahead: entries use bars up to the signal day and execute at the next open; the ranking cache is built only from trades that exited before the 90-day window.",
        "Concentration: the June 8 selloff produced a large share of MR signals; the concentration check above separates that day from the rest.",
        "Fixed 60/90-day holds cannot complete inside a 30/60-day window; those rows are marked to market and the Open column says how much.",
        "Universe is the repo's Feb-2026 list (survivorship applies). No earnings or sentiment veto is applied. Only HEALTHY / DIP_BUY / PULLBACK regimes occurred.",
    ]:
        P(f"<li>{li}</li>")
    P("</ul></main>")
    open(a.out, "w").write("\n".join(o))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
