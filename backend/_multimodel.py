"""MULTI-MODEL cross-sector rotation with guardrails.

Attacks RELSTR10's failure mode (8/10 names in one sector, no exit, -40% from peak):
  A  sector-capped (max K names per sector)          -> diversification
  B  benchmark = SPY (any sector can lead, not tech) -> cross-sector
  C  leading-sector rotation (top names from the strongest sectors)
  D  + position guardrail: trailing stop from position peak
  E  + portfolio guardrail: equity -X% from peak -> park in SPY until recovery

Sector classification: trailing 504d correlation to SPDR sector ETFs, refreshed
quarterly (point-in-time, no lookahead). Monthly rebalance, next-open execution,
0.30%+0.05% per side. Tier B (survivor universe) — numbers are ceilings.
"""
import sqlite3, bisect
import numpy as np, pandas as pd

FEE = 0.003; SLIP = 0.0005
con = sqlite3.connect('data/stock_cache.db')
quar = {r[0] for r in con.execute("SELECT ticker FROM ticker_quarantine")}
df = pd.read_sql_query("SELECT ticker,date,open,close,volume FROM daily_prices", con)
df = df[~df.ticker.isin(quar) & ~df.ticker.str.endswith('USD') & (df.ticker != 'VIX')]
C = df.pivot(index='date', columns='ticker', values='close').astype('float64')
O = df.pivot(index='date', columns='ticker', values='open').astype('float64')
V = df.pivot(index='date', columns='ticker', values='volume').astype('float64')
del df
dates = C.index.tolist(); ND = len(dates)
Cv = C.values; Ov = O.values; Cf = C.ffill().values
cols = list(C.columns)
last_valid = C.apply(lambda s: s.last_valid_index()).map(lambda d: dates.index(d) if d else -1).values
dv = (C * V).rolling(63, min_periods=55).mean().values
r252 = (C / C.shift(252) - 1).values
r126 = (C / C.shift(126) - 1).values
r63 = (C / C.shift(63) - 1).values
rets = C.pct_change(fill_method=None)

SPDR = [s for s in ['XLK','XLV','XLF','XLE','XLI','XLP','XLY','XLU','XLB','XLRE'] if s in C.columns]
SP_I = {s: cols.index(s) for s in SPDR}
XL = cols.index('XLK'); SPY = cols.index('SPY')
mo = [d[:7] for d in dates]
MEset = {i for i in range(ND-1) if mo[i] != mo[i+1]}

_sec_cache = {}
def sectors_at(j):
    """Point-in-time sector map: max-correlation to SPDRs over trailing 504d.
    Cached per ~quarter (j//63) so the classification is stable and cheap."""
    key = j // 63
    if key in _sec_cache:
        return _sec_cache[key]
    a = max(0, j - 504)
    w = rets.iloc[a:j+1]
    etf = w[SPDR]
    sub = w.dropna(axis=1, thresh=int((j - a) * 0.6))
    out = {}
    for tk in sub.columns:
        if tk in SPDR:
            out[cols.index(tk)] = tk; continue
        s = sub[tk]; best = None; bv = -9.0
        for e in SPDR:
            c = s.corr(etf[e])
            if c == c and c > bv:
                bv = c; best = e
        if best and bv > 0.25:
            out[cols.index(tk)] = best
    _sec_cache[key] = out
    return out

def liquid(j, n=300):
    ok = np.isfinite(Cv[j]) & (Cv[j] >= 15) & np.isfinite(dv[j]) & (dv[j] > 3e6)
    e = np.where(ok)[0]
    return e[np.argsort(-dv[j, e])][:n] if len(e) else np.array([], int)

def pick(j, mode, n=10, cap=3, bench='XLK'):
    u = liquid(j)
    if not len(u):
        return []
    sec = sectors_at(j)
    if mode == 'C':                       # leading-sector rotation
        sm = {s: (Cf[j, SP_I[s]] / Cf[j-126, SP_I[s]] - 1) if j >= 126 else -9 for s in SPDR}
        lead = [s for s, _ in sorted(sm.items(), key=lambda kv: -kv[1])[:5]]
        per = max(1, n // len(lead)); out = []
        for s in lead:
            mem = [c for c in u if sec.get(c) == s and np.isfinite(r126[j, c])]
            mem.sort(key=lambda c: -r126[j, c]); out += mem[:per]
        return out[:n]
    bi = XL if bench == 'XLK' else SPY    # relative-strength modes
    if j < 252:
        return []
    b252 = Cf[j, bi] / Cf[j-252, bi] - 1
    b63 = Cf[j, bi] / Cf[j-63, bi] - 1
    cand = [c for c in u
            if np.isfinite(r252[j, c]) and r252[j, c] > b252
            and np.isfinite(r63[j, c]) and r63[j, c] > b63]
    cand.sort(key=lambda c: -r252[j, c])
    out = []; cnt = {}
    for c in cand:
        s = sec.get(c, '?')
        if cnt.get(s, 0) >= cap:
            continue
        out.append(c); cnt[s] = cnt.get(s, 0) + 1
        if len(out) == n:
            break
    return out

def run(a, b, mode, n=10, cap=3, bench='XLK', pos_stop=None, dd_guard=None):
    """hold: col -> (entry_px, peak_px). Returns (final_equity, daily_curve)."""
    eq = 1.0; hold = {}; peak_eq = 1.0; parked = False; curve = []
    for i in range(a, b + 1):
        if parked:
            eq *= Cf[i, SPY] / Cf[i-1, SPY]
        elif hold:
            rs = []
            for c, (ep, pk) in list(hold.items()):
                if not (np.isfinite(Cv[i, c]) and np.isfinite(Cv[i-1, c])
                        and Cv[i-1, c] > 0 and i <= last_valid[c]):
                    continue
                rs.append(Cv[i, c] / Cv[i-1, c] - 1)
                hold[c] = (ep, max(pk, Cv[i, c]))
            eq *= (1 + np.mean(rs)) if rs else 1
        peak_eq = max(peak_eq, eq); curve.append(eq)
        if pos_stop and hold and not parked:      # position guardrail
            drop = [c for c, (ep, pk) in hold.items()
                    if np.isfinite(Cv[i, c]) and Cv[i, c] < pk * (1 - pos_stop)]
            if drop:
                eq *= 1 - (FEE + SLIP) * (len(drop) / max(len(hold), 1))
                for c in drop:
                    hold.pop(c, None)
        if dd_guard:                              # portfolio guardrail
            if not parked and eq < peak_eq * (1 - dd_guard):
                eq *= 1 - (FEE + SLIP); hold = {}; parked = True
            elif parked and eq > peak_eq * (1 - dd_guard / 2):
                parked = False
        if i in MEset and i + 1 <= b and not parked:
            new = pick(i, mode, n, cap, bench)
            if new:
                ch = len(set(new) ^ set(hold))
                eq *= 1 - (FEE + SLIP) * 2 * (ch / max(len(new) + len(hold), 1))
                hold = {}
                for c in new:
                    p = Ov[i+1, c] if (np.isfinite(Ov[i+1, c]) and Ov[i+1, c] > 0) else Cv[i, c]
                    hold[c] = (p, p)
    return eq, np.array(curve)

starts = []; y, mn = 2018, 1
while (y, mn) <= (2026, 1):
    starts.append(f"{y:04d}-{mn:02d}-01"); mn += 6
    if mn > 12: y, mn = y + 1, mn - 12
def dp(s): return min(bisect.bisect_left(dates, s), ND - 1)
wins = [(s, dp(s), dp(f"{int(s[:4]) + (1 if s[5:7]=='07' else 0)}-{'01' if s[5:7]=='07' else '07'}-01"))
        for s in starts]
wins = [w for w in wins if w[2] - w[1] >= 60]
A0 = next(i for i, d in enumerate(dates) if d >= '2017-01-03')
Y0 = next(i for i, d in enumerate(dates) if d >= '2026-01-02')

CFG = [
    ('RELSTR10 baseline (no cap)', 'A', 10, 99, 'XLK', None, None),
    ('A: sector-cap 3',            'A', 10, 3,  'XLK', None, None),
    ('A: sector-cap 2',            'A', 10, 2,  'XLK', None, None),
    ('B: bench=SPY, cap 2',        'B', 10, 2,  'SPY', None, None),
    ('C: leading-sector rotation', 'C', 10, 3,  'SPY', None, None),
    ('D: SPY cap2 + stop -15%',    'B', 10, 2,  'SPY', 0.15, None),
    ('D: SPY cap2 + stop -20%',    'B', 10, 2,  'SPY', 0.20, None),
    ('E: cap2 + stop15 + DD12%',   'B', 10, 2,  'SPY', 0.15, 0.12),
    ('E: cap2 + DD-guard 12%',     'B', 10, 2,  'SPY', None, 0.12),
]
print(f"{'strategy':<30}{'WFcomp':>9}{'WFmed':>8}{'worst':>8}{'pos%':>6}{'decade$100K':>13}{'2026YTD':>9}{'last30d':>9}")
print('-' * 92)
for lbl, mode, n, cap, bench, ps, dg in CFG:
    v = np.array([run(a, b, mode, n, cap, bench, ps, dg)[0] - 1 for _, a, b in wins])
    dec = run(A0, ND - 1, mode, n, cap, bench, ps, dg)[0] * 100_000
    fy, cy = run(Y0, ND - 1, mode, n, cap, bench, ps, dg)
    l30 = (cy[-1] / cy[-31] - 1) * 100 if len(cy) > 31 else float('nan')
    print(f"{lbl:<30}{(np.prod(1+v)-1)*100:>8.1f}%{np.median(v)*100:>7.1f}%{v.min()*100:>7.1f}%"
          f"{(v>0).mean()*100:>5.0f}%{dec:>13,.0f}{(fy-1)*100:>+8.1f}%{l30:>+8.1f}%")
for nm, ix in (('XLK buy-hold', XL), ('SPY buy-hold', SPY)):
    bv = np.array([(Cf[b, ix] / Cf[a, ix] - 1) for _, a, b in wins])
    print(f"{nm:<30}{(np.prod(1+bv)-1)*100:>8.1f}%{np.median(bv)*100:>7.1f}%{bv.min()*100:>7.1f}%"
          f"{(bv>0).mean()*100:>5.0f}%{100_000*Cf[ND-1,ix]/Cf[A0,ix]:>13,.0f}"
          f"{(Cf[ND-1,ix]/Cf[Y0,ix]-1)*100:>+8.1f}%{(Cf[ND-1,ix]/Cf[ND-31,ix]-1)*100:>+8.1f}%")
