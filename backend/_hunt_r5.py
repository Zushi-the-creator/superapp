"""RESEARCH CYCLE — round 5: MULTI-ASSET PARAMETER SEARCH.

Rounds 1-4 established: within US equity, everything is beta. Stock-picking on a
survivor universe cannot be trusted (RELSTR10 collapsed below XLK once its 10
most-held names were banned). The only honest winner, LEVSAT40, ties XLK on
risk-adjusted return.

Literature says the remaining lever is NOT better selection, it is DIVERSIFICATION
and VOLATILITY SCALING across asset classes:
  - Hurst/Ooi/Pedersen, "A Century of Evidence on Trend-Following": time-series
    momentum works across asset classes for 137 years.
  - Man Group / Alpha Architect on vol targeting: Sharpe for US equity 0.40 -> 0.48-0.51,
    but ~zero benefit for bonds/FX/commodities. So vol-scale the EQUITY sleeve only.
  - Antonacci GEM / Accelerating Dual Momentum: absolute + relative momentum with a
    defensive asset. (Antonacci himself calls ADM's blended lookbacks data-mined ->
    treat blended lookbacks as a parameter to test, not a prior.)

SEARCH SPACE (full grid, every cell scored IS and OOS separately):
    universe    x  signal  x  lookback  x  top_k  x  weighting  x  defensive  x  rebalance
ANTI-OVERFIT PROTOCOL:
  1. Select the best cell on IS ONLY, then report its OOS. That is the honest number.
  2. Report the FULL grid distribution — a lone spike is an artifact, a plateau is real.
  3. Random-selector control must lose.
  4. Nothing promoted on a single cell.
"""
import sqlite3, numpy as np, pandas as pd, math, bisect, itertools, json
from collections import defaultdict

con = sqlite3.connect('data/stock_cache.db')
UNIV = ['SPY','QQQ','XLK','IWM','MDY','EFA','EEM','VGK','EWJ','VEU',
        'TLT','IEF','SHY','BIL','LQD','HYG','TIP','AGG','BND',
        'GLD','SLV','DBC','GSG','VNQ','XLE','XLU','XLP','XLV','XLF','XLI','XLY','XLB',
        'MTUM','QUAL','USMV','VLUE','SPLV','RSP','VTV','VUG']
q = ",".join(f"'{t}'" for t in UNIV)
df = pd.read_sql_query(f"SELECT ticker,date,close FROM daily_prices WHERE ticker IN ({q}) AND date>='2015-01-01'", con)
C = df.pivot(index='date', columns='ticker', values='close').astype(float)
C = C.dropna(axis=0, how='any')
dates = C.index.tolist(); ND = len(dates); COLS = list(C.columns)
P = C.values
print(f"multi-asset matrix: {ND} bars x {len(COLS)} ETFs   {dates[0]} -> {dates[-1]}")

IS0 = next(i for i, d in enumerate(dates) if d >= '2016-06-01')
OOS0 = next(i for i, d in enumerate(dates) if d >= '2023-01-03')
IX = {t: COLS.index(t) for t in COLS}
me = {i for i in range(ND - 1) if dates[i][:7] != dates[i + 1][:7]}
qe = {i for i in me if dates[i][5:7] in ('03', '06', '09', '12')}
EFEE, SLIP = 0.0005, 0.0005

RET = np.vstack([np.zeros(len(COLS))] + [P[i] / P[i - 1] - 1 for i in range(1, ND)])
VOL21 = pd.DataFrame(RET).rolling(21, min_periods=18).std().values
VOL63 = pd.DataFrame(RET).rolling(63, min_periods=55).std().values
SMA = {w: pd.DataFrame(P).rolling(w, min_periods=int(w * .9)).mean().values for w in (50, 100, 200)}
MOM = {l: np.vstack([np.full(len(COLS), np.nan)] * l + [P[i] / P[i - l] - 1 for i in range(l, ND)])
       for l in (21, 63, 126, 252)}

SETS = {
    'US-equity':      ['SPY','QQQ','XLK','IWM','MDY'],
    'global-equity':  ['SPY','QQQ','IWM','EFA','EEM','VGK','EWJ'],
    'equity+bond':    ['SPY','QQQ','XLK','IWM','EFA','EEM','TLT','IEF','LQD','HYG'],
    'multi-asset':    ['SPY','QQQ','XLK','IWM','EFA','EEM','TLT','IEF','LQD','HYG','GLD','DBC','VNQ'],
    'multi-asset+':   ['SPY','QQQ','XLK','IWM','MDY','EFA','EEM','VGK','TLT','IEF','LQD','HYG','TIP','GLD','SLV','DBC','VNQ','XLE','XLU','XLP'],
    'sectors':        ['XLK','XLV','XLF','XLI','XLY','XLP','XLU','XLB','XLE','VNQ'],
    'factors':        ['MTUM','QUAL','USMV','VLUE','SPLV','RSP','VTV','VUG','SPY'],
}
DEFENSIVE = {'cash': None, 'BIL': 'BIL', 'IEF': 'IEF', 'TLT': 'TLT', 'GLD': 'GLD'}
RATE = np.array([0.01 if d < '2022-06-01' else (0.03 if d < '2023-01-01' else 0.05) for d in dates])


def score_at(j, cols, sig, lb):
    if sig == 'mom':
        return {c: MOM[lb][j, c] for c in cols}
    if sig == 'blend':                       # ADM-style 1/3/6/12m weighted blend
        out = {}
        for c in cols:
            v = [MOM[l][j, c] for l in (21, 63, 126, 252)]
            if any(not np.isfinite(x) for x in v): out[c] = np.nan
            else: out[c] = 0.4 * v[0] + 0.3 * v[1] + 0.2 * v[2] + 0.1 * v[3]
        return out
    if sig == 'sharpe':                      # return / vol
        return {c: (MOM[lb][j, c] / (VOL63[j, c] * math.sqrt(252) + 1e-9))
                if np.isfinite(MOM[lb][j, c]) and np.isfinite(VOL63[j, c]) else np.nan for c in cols}
    return {c: np.nan for c in cols}


def build(uset, sig, lb, k, wt, dfns, rb, abs_gate=True, voltgt=None, s0=IS0, s1=None):
    cols = [IX[t] for t in SETS[uset] if t in IX]
    dcol = IX[DEFENSIVE[dfns]] if DEFENSIVE[dfns] else None
    rbs = me if rb == 'M' else qe
    end = s1 if s1 is not None else ND - 1
    eq = 1.0; hold = {}; c = [1.0]; prev_lev = 1.0
    for i in range(s0, end + 1):
        if hold:
            num = sum(w * RET[i, cc] for cc, w in hold.items() if np.isfinite(RET[i, cc]))
            wsum = sum(w for cc, w in hold.items() if np.isfinite(RET[i, cc]))
            r = num / wsum if wsum > 0 else 0.0
        else:
            r = RATE[i] / 252
        lev = 1.0
        if voltgt:
            pv = np.sqrt(sum((w / max(sum(hold.values()), 1e-9)) ** 2 * (VOL21[i - 1, cc] ** 2)
                             for cc, w in hold.items())) * math.sqrt(252) if hold else voltgt
            lev = float(np.clip(voltgt / pv, 0.0, 1.5)) if pv > 0 else 1.0
            if abs(lev - prev_lev) > 0.10: eq *= 1 - abs(lev - prev_lev) * (EFEE + SLIP); prev_lev = lev
            else: lev = prev_lev
            r = lev * r + max(1 - lev, 0) * RATE[i] / 252
        eq *= (1 + r)
        if (i - 1) in rbs:
            j = i - 1
            sc = score_at(j, cols, sig, lb)
            cand = [(v, cc) for cc, v in sc.items() if np.isfinite(v)]
            if abs_gate:
                cand = [(v, cc) for v, cc in cand
                        if v > 0 and np.isfinite(SMA[200][j, cc]) and P[j, cc] > SMA[200][j, cc]]
            cand.sort(reverse=True)
            sel = [cc for _, cc in cand[:k]]
            if not sel:
                new = {dcol: 1.0} if dcol is not None else {}
            else:
                if wt == 'ivol':
                    ws = np.array([1.0 / max(VOL63[j, cc], 1e-5) if np.isfinite(VOL63[j, cc]) else 0.0 for cc in sel])
                    if ws.sum() <= 0: ws = np.ones(len(sel))
                else:
                    ws = np.ones(len(sel), float)
                ws = ws / ws.sum()
                if dcol is not None and len(sel) < k:      # unfilled slots -> defensive
                    fill = (k - len(sel)) / k
                    ws = ws * (1 - fill)
                    new = {cc: float(w) for cc, w in zip(sel, ws)}
                    new[dcol] = new.get(dcol, 0.0) + fill
                else:
                    new = {cc: float(w) for cc, w in zip(sel, ws)}
            ch = sum(abs(new.get(x, 0) - hold.get(x, 0)) for x in set(new) | set(hold))
            eq *= 1 - (EFEE + SLIP) * ch
            hold = new
        c.append(eq)
    return np.array(c)


def stats(c):
    c = np.asarray(c, float); c = c / c[0]
    r = np.diff(c) / c[:-1]; pk = np.maximum.accumulate(c)
    cg = (c[-1] ** (252 / len(r)) - 1) * 100
    md = (c / pk - 1).min() * 100
    sh = (r.mean() / (r.std() + 1e-12)) * math.sqrt(252)
    return cg, md, sh, cg / abs(md) if md else 0


# ── benchmarks ──
def bh(t, a, b=None):
    b = b if b is not None else ND - 1
    return np.array([P[i, IX[t]] / P[a, IX[t]] for i in range(a, b + 1)])

print("\n" + "=" * 100); print("BENCHMARKS"); print("=" * 100)
print(f"{'':<24}{'IS CAGR':>9}{'OOS CAGR':>10}{'OOS MDD':>9}{'OOS Shrp':>10}{'OOS MAR':>9}")
BM = {}
for t in ['XLK', 'QQQ', 'SPY']:
    i_ = stats(bh(t, IS0, OOS0)); o_ = stats(bh(t, OOS0))
    BM[t] = o_
    print(f"{t + ' buy-hold':<24}{i_[0]:>8.1f}%{o_[0]:>9.1f}%{o_[1]:>8.1f}%{o_[2]:>10.2f}{o_[3]:>9.2f}")

# ── FULL GRID ──
print("\n" + "=" * 100)
print("MULTI-PARAMETER GRID SEARCH")
print("=" * 100)
GRID = list(itertools.product(
    SETS.keys(), ['mom', 'blend', 'sharpe'], [63, 126, 252], [2, 3, 5],
    ['eq', 'ivol'], ['cash', 'IEF', 'TLT', 'GLD'], ['M', 'Q']))
GRID = [g for g in GRID if not (g[1] == 'blend' and g[2] != 252)]   # blend ignores lb
print(f"cells: {len(GRID)}  (scored on IS, then OOS reported for the IS-chosen winner)")

rows = []
for n, (u, sg, lb, k, wt, dfn, rb) in enumerate(GRID):
    try:
        ci = build(u, sg, lb, k, wt, dfn, rb, s0=IS0, s1=OOS0)
        co = build(u, sg, lb, k, wt, dfn, rb, s0=OOS0)
    except Exception:
        continue
    i_ = stats(ci); o_ = stats(co)
    rows.append(dict(u=u, sig=sg, lb=lb, k=k, wt=wt, dfn=dfn, rb=rb,
                     is_cagr=i_[0], is_mar=i_[3], is_sh=i_[2],
                     oos_cagr=o_[0], oos_mdd=o_[1], oos_sh=o_[2], oos_mar=o_[3]))
    if (n + 1) % 200 == 0: print(f"  {n+1}/{len(GRID)}", flush=True)
R = pd.DataFrame(rows)
R.to_csv('/tmp/r5_grid.csv', index=False)
print(f"\ncompleted {len(R)} cells")

print("\n--- GRID DISTRIBUTION (is the family good, or one lucky cell?) ---")
print(f"{'metric':<14}{'min':>9}{'p25':>9}{'median':>9}{'p75':>9}{'max':>9}")
for m in ['is_cagr', 'oos_cagr', 'oos_mar', 'oos_sh']:
    v = R[m]
    print(f"{m:<14}{v.min():>8.1f}{v.quantile(.25):>9.1f}{v.median():>9.1f}{v.quantile(.75):>9.1f}{v.max():>9.1f}")
print(f"\ncells beating XLK OOS MAR ({BM['XLK'][3]:.2f}): {(R.oos_mar > BM['XLK'][3]).sum()}/{len(R)}")
print(f"cells beating XLK OOS Sharpe ({BM['XLK'][2]:.2f}): {(R.oos_sh > BM['XLK'][2]).sum()}/{len(R)}")

print("\n--- HONEST SELECTION: pick best on IS MAR, report its OOS ---")
for crit in ['is_mar', 'is_sh', 'is_cagr']:
    b = R.loc[R[crit].idxmax()]
    print(f"  best by {crit:<8} -> {b.u}/{b.sig}/lb{b.lb}/k{b.k}/{b.wt}/{b.dfn}/{b.rb}"
          f"   IS {b.is_cagr:.1f}%  ->  OOS {b.oos_cagr:.1f}% / MDD {b.oos_mdd:.1f}% / Sharpe {b.oos_sh:.2f} / MAR {b.oos_mar:.2f}")

print("\n--- top 15 by OOS Sharpe (IN-SAMPLE-BLIND view, for diagnosis only) ---")
print(f"{'universe':<14}{'sig':<7}{'lb':>4}{'k':>3}{'wt':>6}{'def':>5}{'rb':>3}{'ISc':>8}{'OOSc':>8}{'MDD':>8}{'Shrp':>6}{'MAR':>6}")
for _, r in R.sort_values('oos_sh', ascending=False).head(15).iterrows():
    print(f"{r.u:<14}{r.sig:<7}{r.lb:>4}{r.k:>3}{r.wt:>6}{r.dfn:>5}{r.rb:>3}"
          f"{r.is_cagr:>7.1f}%{r.oos_cagr:>7.1f}%{r.oos_mdd:>7.1f}%{r.oos_sh:>6.2f}{r.oos_mar:>6.2f}")

print("\n--- WHICH PARAMETER ACTUALLY MATTERS? (mean OOS Sharpe by level) ---")
for p in ['u', 'sig', 'k', 'wt', 'dfn', 'rb', 'lb']:
    g = R.groupby(p).oos_sh.agg(['mean', 'max', 'count']).sort_values('mean', ascending=False)
    print(f"\n  {p}:")
    for idx, rr in g.iterrows():
        print(f"    {str(idx):<14} mean {rr['mean']:>5.2f}   best {rr['max']:>5.2f}   n={int(rr['count'])}")
