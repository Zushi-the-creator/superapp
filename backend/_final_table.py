"""FINAL CONSOLIDATED TABLE — every strategy tested, one dataset, one window, one set of conventions.

Rounds 1-7 were run by different scripts with slightly different matrices (the main
harness gave XLK OOS 34.3%, the multi-asset script 35.2%, because it dropna'd across
40 ETFs and so started later). Those numbers are NOT directly comparable.

This script recomputes EVERYTHING inside the canonical harness namespace so that
every row shares:
    - the same price matrix (post-backfill, post-phantom-row-deletion)
    - the same IS/OOS boundaries (IS 2016-06-01..2022-12-30, OOS 2023-01-03..now)
    - the same cost model (stocks 0.30%+0.05%/side, ETFs 0.05%+0.05%, delist haircut 0.70)
    - the same next-day-open entry convention
    - the same statistics (CAGR, MDD, Sharpe, MAR, DSR)

Rows also carry the ROBUSTNESS verdict from rounds 2/4/7 — the tests that decide
whether a headline number means anything.
"""
exec(open('_master_harness3.py').read().split("STRATS=[")[0])
import numpy as np, math
DNS = {}; exec(open('_dsr.py').read().split("if __name__")[0], DNS); dsr = DNS['dsr']

IS0 = next(i for i, d in enumerate(dates) if d >= '2016-06-01')
OOS0 = next(i for i, d in enumerate(dates) if d >= '2023-01-03')
XLi = C.columns.get_loc('XLK'); SPi = C.columns.get_loc('SPY')
print(f"dataset: {ND} bars x {C.shape[1]} tickers  {dates[0]} -> {dates[-1]}")
print(f"IS {dates[IS0]} .. {dates[OOS0-1]} ({OOS0-IS0}d)   OOS {dates[OOS0]} .. {dates[-1]} ({ND-OOS0}d)")

Q_ENDS = {i for i in me if dates[i][5:7] in ('03', '06', '09', '12')}
_vol63 = C.pct_change(fill_method=None).rolling(63, min_periods=55).std().values
HAS = lambda t: t in C.columns


def rot(sel, top_n, s0, rebal=None, weight='eq'):
    rb = me if rebal is None else rebal
    fee = FEE + SLIP; eq = 1.0; hold = {}; c = [1.0]
    for i in range(s0, ND):
        if hold:
            num = wsum = 0.0
            for col, w in hold.items():
                if not (np.isfinite(Cv[i, col]) and np.isfinite(Cv[i-1, col])
                        and Cv[i-1, col] > 0 and i <= last_valid[col]): continue
                num += w * (Cv[i, col] / Cv[i-1, col] - 1); wsum += w
            eq *= (1 + num / wsum) if wsum > 0 else 1.0
        if (i - 1) in rb:
            j = i - 1; new = sel(j, top_n)
            if new:
                if weight == 'ivol':
                    ws = np.array([1.0 / max(_vol63[j, x], 1e-4) if np.isfinite(_vol63[j, x]) else 0.0 for x in new])
                    if ws.sum() <= 0: ws = np.ones(len(new))
                else: ws = np.ones(len(new), float)
                ws = ws / ws.sum()
                ch = len(set(new) ^ set(hold))
                eq *= 1 - fee * 2 * (ch / max(len(new) + len(hold), 1))
                hold = {x: float(w) for x, w in zip(new, ws)}
        c.append(eq)
    return np.array(c)


def levsat(s0, sat_frac=0.40, lev_tk='ROM', base_tk='XLK'):
    """REAL instrument version: core + actual levered ETF while core > SMA200."""
    bi = C.columns.get_loc(base_tk); li = C.columns.get_loc(lev_tk)
    A = Cf[:, bi]; L = Cf[:, li]
    sm = pd.Series(A).rolling(200, min_periods=180).mean().values
    eq = 1.0; c = [1.0]; inp = True
    for i in range(s0, ND):
        ra = (A[i]/A[i-1] - 1) if (np.isfinite(A[i]) and np.isfinite(A[i-1]) and A[i-1] > 0) else 0.0
        rl = (L[i]/L[i-1] - 1) if (np.isfinite(L[i]) and np.isfinite(L[i-1]) and L[i-1] > 0) else ra
        w = bool(np.isfinite(sm[i-1]) and A[i-1] > sm[i-1])
        if w != inp: eq *= 1 - sat_frac * (EFEE + SLIP); inp = w
        eq *= (1 + (1 - sat_frac) * ra + sat_frac * (rl if inp else ra))
        c.append(eq)
    return np.array(c)


def stats(c):
    c = np.asarray(c, float); c = c / c[0]
    r = np.diff(c) / c[:-1]; pk = np.maximum.accumulate(c)
    cg = (c[-1] ** (252 / len(r)) - 1) * 100
    md = (c / pk - 1).min() * 100
    sh = (r.mean() / (r.std() + 1e-12)) * math.sqrt(252)
    sk = float(((r - r.mean())**3).mean() / (r.std()**3 + 1e-12))
    ku = float(((r - r.mean())**4).mean() / (r.std()**4 + 1e-12))
    d40, _ = dsr(sh, len(r), 40, sk, ku)
    return cg, md, sh, (cg/abs(md) if md else 0), d40


RS = mk_relstr(99, 'XLK')
ROWS = []
def add(name, tier, fn, verdict):
    try:
        ci = fn(IS0)[:OOS0 - IS0]; co = fn(OOS0)
    except Exception as e:
        print(f"  SKIP {name}: {e}"); return
    i_ = stats(ci); o_ = stats(co)
    ROWS.append((name, tier, i_[0], o_[0], o_[1], o_[2], o_[3], o_[4], verdict))
    print(f"  ok  {name}", flush=True)

print("\ncomputing rows ...")
# ── benchmarks (Tier A) ──
add('XLK buy-hold  [THE BAR]', 'A', lambda s: bh(XL, s), 'benchmark')
add('QQQ buy-hold', 'A', lambda s: bh(QQ, s), 'benchmark')
add('SPY buy-hold', 'A', lambda s: bh(SP, s), 'benchmark')
# ── the Tier A winner ──
if HAS('ROM'):
    add('LEVSAT40: 60%XLK+40%ROM>SMA200', 'A', lambda s: levsat(s, 0.40), 'SURVIVED all stress; ties XLK risk-adj')
    add('LEVSAT30 (same, 30% sleeve)', 'A', lambda s: levsat(s, 0.30), 'plateau neighbour of LEVSAT40')
    add('LEVSAT20 (same, 20% sleeve)', 'A', lambda s: levsat(s, 0.20), 'plateau neighbour of LEVSAT40')
add('80/20 QQQ+3x-trend (synthetic)', 'A', lambda s: etf_curve(0.20, 3, s), 'same family, synthetic leverage')
add('60/40 QQQ+2x-trend (synthetic)', 'A', lambda s: etf_curve(0.40, 2, s), 'same family, synthetic leverage')
add('Faber SMA200 QQQ', 'A', faber, 'insurance not alpha')
add('Sector top-2 SPDR monthly', 'A', lambda s: monthly_rot(None, sect, 2, s, stock=False), 'rejected r3')
# ── Tier B rotations ──
add('RELSTR10 monthly top10', 'B', lambda s: rot(RS, 10, s), 'KILLED r2: ban top-10 names -> 23.5%')
add('RELSTR10 quarterly top10', 'B', lambda s: rot(RS, 10, s, rebal=Q_ENDS), 'KILLED r2: same')
add('RELSTR10 monthly top5', 'B', lambda s: rot(RS, 5, s), 'KILLED r2: same')
add('RELSTR10 inverse-vol', 'B', lambda s: rot(RS, 10, s, weight='ivol'), 'KILLED r2: same')
add('RELSTR10 sector-cap2', 'B', lambda s: monthly_rot_g(mk_relstr(2, 'XLK'), 10, s), 'sector cap hurts')
add('LC 12-1 rotation top10', 'B', lambda s: rot(lc121, 10, s), 'KILLED r2: same mechanism')
add('LC 12-1 rotation top5', 'B', lambda s: rot(lc121, 5, s), 'KILLED r2: same mechanism')
add('TREND10 (>200SMA near 52wk-hi)', 'B', lambda s: monthly_rot_g(_trend_sel, 10, s), 'worst MDD of top group')
add('Leading-sector rotation', 'B', lambda s: monthly_rot_g(_leadsec_sel, 10, s), 'below QQQ')
add('V4BLEND 50%XLK+50%ROT10', 'B', lambda s: _blend(bh(XL, s), monthly_rot(None, lc121, 10, s), 0.5), 'half-diluted LC12-1')
add('50/50 RELSTR10 + XLK', 'B', lambda s: _blend(rot(RS, 10, s), bh(XL, s), 0.5), 'inherits r2 kill')
# ── production / MR family (Tier B) ──
add('PROD V3.6 MR alw-on F42 (LIVE)', 'B', lambda s: stock_sim_cash(lambda d: (('mr', MRS, 42) if NONPAUSE(d) else None), s), 'DEPLOYED — dead last')
add('PROD V3.4 MR always-on F60', 'B', lambda s: stock_sim(lambda d: (('mr', MRS, 60) if NONPAUSE(d) else None), s), 'superseded by F42')
add('PROD V3.2 MR always-on F30', 'B', lambda s: stock_sim(lambda d: (('mr', MRS, 30) if NONPAUSE(d) else None), s), 'superseded')
add('PROD V3.1 MR always-on Hyb21d', 'B', lambda s: stock_sim(lambda d: (('mr', MRS, 'hyb21') if NONPAUSE(d) else None), s), 'superseded')
add('MR dips-only Fixed42', 'B', lambda s: stock_sim(lambda d: (('mr', MRS, 42) if R[d] in DIP else None), s), 'best MR variant, still < QQQ')
add('MR short-exit RSI75cap21', 'B', lambda s: stock_sim(lambda d: (('mr', MRS, 'rsi75c21') if NONPAUSE(d) else None), s), 'rejected: no compounding')
add('MR stop-8% w42', 'B', lambda s: stock_sim(lambda d: (('mr', MRS, 'stop8w42') if NONPAUSE(d) else None), s), 'rejected: stops hurt MR')
add('MOM breakout r126 F90', 'B', lambda s: stock_sim(lambda d: (('mom', MOMS, 90) if R[d] in {'HEALTHY','PULLBACK','DIP_BUY'} else None), s), 'ok but < QQQ')
add('PROD tab MOM sleeve ret20xvr', 'B', lambda s: stock_sim(lambda d: (('mom', MSPK, 90) if R[d] not in {'DANGER','CRISIS'} else None), s), 'spike-chasing, rotted')
# ── controls ──
add('NULL CHECK (selector empty)', 'X', lambda s: monthly_rot_g(lambda j, n: [], 10, s), 'must be exactly 0.0%')
rng = np.random.default_rng(11)
def alive(j): return [c for c in range(C.shape[1]) if np.isfinite(Cv[j, c]) and Cv[j, c] >= 10 and last_valid[c] > j + 30]
add('RANDOM-PICK control (10 names)', 'X', lambda s: rot(lambda j, n: list(rng.choice(alive(j), size=min(n, len(alive(j))), replace=False)), 10, s), 'must lose')

print("\n" + "=" * 132)
print("FINAL TABLE — every strategy on ONE dataset, ONE window, ONE cost model")
print("=" * 132)
print(f"{'#':<3}{'strategy':<34}{'T':<2}{'IS CAGR':>8}{'OOS CAGR':>9}{'OOS MDD':>8}{'Shrp':>6}{'MAR':>6}{'DSR40':>7}  robustness verdict")
print("-" * 132)
xk = [r for r in ROWS if 'THE BAR' in r[0]][0]
for n, r in enumerate(sorted(ROWS, key=lambda x: -x[3]), 1):
    nm, t, ic, oc, om, sh, mar, d40, v = r
    mark = ' *' if (oc > xk[3] and mar > xk[6] and t == 'A') else '  '
    print(f"{n:<3}{nm:<34}{t:<2}{ic:>7.1f}%{oc:>8.1f}%{om:>7.1f}%{sh:>6.2f}{mar:>6.2f}{d40:>7.3f}{mark}{v}")
print("-" * 132)
print(f"T = evidence tier.  A = index/ETF universe fixed in advance (survivorship inflation impossible).")
print(f"                    B = stock-picking on a survivor universe (numbers are an UPPER BOUND).")
print(f"                    X = control (must behave exactly as stated or the harness is broken).")
print(f"DSR40 = Deflated Sharpe at 40 trials. >=0.95 passes. NOTHING here passes — including XLK ({xk[7]:.3f}).")
print(f"* = Tier A row beating XLK on BOTH OOS return and MAR.")

na = sum(1 for r in ROWS if r[1] == 'A' and r[3] > xk[3] and r[6] > xk[6])
print(f"\nTier A rows beating XLK on return AND MAR: {na}")
print(f"Rows passing DSR at N=40: {sum(1 for r in ROWS if r[7] >= 0.95)}")
