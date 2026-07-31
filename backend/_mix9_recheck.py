"""MIX9 re-check on CORRECTED data, exactly per its frozen registry rule.

Registry rule (roster 9, frozen 2026-07-31, sha
  "Daily regime read (prod _check_market_regime chain incl. VIX tiers). Map regime ->
   active strategy, FROZEN from IS-only (2016-06..2022-12) mean daily return per regime.
   Allocation: 70% active strategy + 30% XLK core, rebalanced monthly.
   GUARDRAIL: if the active strategy's own equity is >15% below its running peak, its
   70% sleeve sits in XLK until that strategy recovers. No position-level stops."

Why this re-run is needed: MIX9's registered numbers (OOS 40.7% CAGR / Sharpe 1.41)
were produced BEFORE the 2026 cache backfill and BEFORE the regime NaN-poison fix.
Both changed the inputs MIX9 depends on most (regime labels drive the switching).

Also runs the WINNER-EXCLUSION test that killed RELSTR10 and LC12-1 — MIX9's regime
map routes to RELSTR10 in DANGER/CORRECTION, RELSTR10-cap2 in BEAR_BOUNCE and LC12-1
in CRISIS, so it may inherit the same defect.

All figures on the SAME basis as _final_table.py:
  one continuous run from IS0=2016-06-01; YTD/OOS are SLICES of that run.
"""
exec(open('_strategy_mixing.py').read().split("RULES = [")[0])
import numpy as np, math
DNS = {}; exec(open('_dsr.py').read().split("if __name__")[0], DNS); dsr = DNS['dsr']

Y0 = next(i for i, d in enumerate(dates) if d >= '2026-01-02')
Y_T = Y0 - IS0                      # index into the IS0-based curves
print(f"\ncurve length n={n}   IS_T={IS_T} (OOS starts)   Y_T={Y_T} (2026 starts)")
print(f"regime map in force (IS-derived, frozen):")
for rg in sorted(REGMAP): print(f"    {rg:<13} -> {REGMAP[rg]}")


def mix9(core_r, core_w=0.30, dd_stop=0.15, ban_names=None):
    """Exactly the registry rule. ban_names re-runs the whole thing with those
    tickers removed from every underlying selector (winner-exclusion test)."""
    if ban_names:
        # rebuild component curves with the banned names excluded
        bancols = {C.columns.get_loc(t) for t in ban_names if t in C.columns}
        def strip(sel):
            return lambda j, k: [c for c in sel(j, k + len(bancols)) if c not in bancols][:k]
        cur = {}
        cur['TREND10']    = monthly_rot_g(strip(_trend_sel), 10, IS0)[1:]
        cur['RELSTR10']   = monthly_rot_g(strip(mk_relstr(99, 'XLK')), 10, IS0)[1:]
        cur['cap2+guard'] = monthly_rot_g(strip(mk_relstr(2, 'SPY')), 10, IS0, pos_stop=0.15, dd_guard=0.12)[1:]
        cur['LeadSector'] = monthly_rot_g(strip(_leadsec_sel), 10, IS0)[1:]
        cur['LC 12-1']    = monthly_rot(None, strip(lc121), 10, IS0)
        cur['MR-dips90']  = CUR['MR-dips90']
        cur['MOM-brk90']  = CUR['MOM-brk90']
        nn = min(len(v) for v in cur.values())
        rm = np.vstack([np.diff(np.asarray(cur[k], float)[:nn]) / np.asarray(cur[k], float)[:nn][:-1] for k in names])
        TT = rm.shape[1]
    else:
        rm = Rmat; TT = T
    eq = 1.0; out = [1.0]
    peaks = {k: 1.0 for k in names}; cur_e = {k: 1.0 for k in names}
    for t in range(TT):
        for i, k in enumerate(names):
            cur_e[k] *= (1 + rm[i, t]); peaks[k] = max(peaks[k], cur_e[k])
        k = REGMAP.get(regs[t], 'TREND10'); si = names.index(k); ra = rm[si, t]
        if dd_stop and cur_e[k] < peaks[k] * (1 - dd_stop): ra = core_r[t]
        eq *= (1 + (1 - core_w) * ra + core_w * core_r[t]); out.append(eq)
    return np.array(out)


def sl(c, a):
    x = np.asarray(c, float)[a:]; x = x / x[0]
    r = np.diff(x) / x[:-1]; pk = np.maximum.accumulate(x)
    cg = (x[-1] ** (252 / len(r)) - 1) * 100
    return (x[-1] - 1) * 100, cg, (x / pk - 1).min() * 100, (r.mean() / (r.std() + 1e-12)) * math.sqrt(252)


def dsr40(c):
    c = np.asarray(c, float); r = np.diff(c) / c[:-1]
    sh = (r.mean() / (r.std() + 1e-12)) * math.sqrt(252)
    sk = float(((r - r.mean())**3).mean() / (r.std()**3 + 1e-12))
    ku = float(((r - r.mean())**4).mean() / (r.std()**4 + 1e-12))
    return dsr(sh, len(r), 40, sk, ku)[0]


M9 = mix9(rx)
XK = XLK

print("\n" + "=" * 104)
print("MIX9 RE-CHECK on corrected data — same basis as the final table")
print("=" * 104)
print(f"{'series':<18}{'window':<12}{'total':>10}{'CAGR':>9}{'MDD':>9}{'Sharpe':>8}{'DSR40':>8}")
for nm, c in [('MIX9', M9), ('XLK', XK)]:
    for wl, a in [('FULL 2016-06', 0), ('IS 2016-22', 0), ('OOS 2023+', IS_T), ('YTD 2026', Y_T)]:
        cc = c[:IS_T + 1] if wl.startswith('IS') else c
        tot, cg, md, sh = sl(cc, a if not wl.startswith('IS') else 0)
        print(f"{nm:<18}{wl:<12}{tot:>+9.1f}%{cg:>8.1f}%{md:>8.1f}%{sh:>8.2f}{dsr40(np.asarray(cc,float)[a:] if not wl.startswith('IS') else cc):>8.3f}")
    print()

print("=" * 104)
print("WINNER-EXCLUSION TEST — the test that killed RELSTR10 and LC12-1")
print("MIX9 routes to RELSTR10 (DANGER/CORRECTION), RELSTR10-cap2 (BEAR_BOUNCE), LC12-1 (CRISIS).")
print("=" * 104)
from collections import Counter
_, picks = None, None
# most-held names across MIX9's own component selectors over OOS
cnt = Counter()
for j in sorted(mset):
    jj = IS0 + j
    if jj < 252: continue
    if jj < OOS0: continue
    for sel in (_trend_sel, mk_relstr(99, 'XLK'), _leadsec_sel):
        for c_ in sel(jj, 10): cnt[C.columns[c_]] += 1
top = [t for t, _ in cnt.most_common(10)]
print(f"MIX9's 10 most-selected names (OOS): {top}\n")
print(f"{'banned':<34}{'OOS CAGR':>10}{'OOS MDD':>10}{'Sharpe':>9}{'vs XLK':>9}")
_, xc, xm, xs = sl(XK, IS_T)
print(f"{'XLK benchmark':<34}{xc:>9.1f}%{xm:>9.1f}%{xs:>9.2f}{'--':>9}")
for k in (0, 3, 5, 10):
    ban = top[:k]
    c = mix9(rx, ban_names=ban) if k else M9
    _, cg, md, sh = sl(c, IS_T)
    lbl = 'none' if k == 0 else f"top-{k}: {','.join(ban[:3])}{'...' if k > 3 else ''}"
    print(f"{lbl:<34}{cg:>9.1f}%{md:>9.1f}%{sh:>9.2f}{cg-xc:>+8.1f}")

print("\n" + "=" * 104)
print("REGISTERED vs RE-CHECKED (what the backfill + regime fix changed)")
print("=" * 104)
_, ocg, omd, osh = sl(M9, IS_T)
_, ycg, _, _ = sl(M9, Y_T)
ytot = sl(M9, Y_T)[0]; xytot = sl(XK, Y_T)[0]
print(f"{'metric':<22}{'registered':>13}{'re-checked':>13}{'delta':>10}")
for lbl, reg, new in [('OOS CAGR', 40.7, ocg), ('OOS Sharpe', 1.41, osh),
                      ('OOS MDD', -35.4, omd), ('2026 YTD', 23.6, ytot),
                      ('DSR @ N=40', 0.680, dsr40(np.asarray(M9, float)[IS_T:]))]:
    print(f"{lbl:<22}{reg:>13.2f}{new:>13.2f}{new-reg:>+10.2f}")
print(f"\nXLK on same basis: OOS CAGR {xc:.1f}%  MDD {xm:.1f}%  Sharpe {xs:.2f}  YTD {xytot:+.1f}%")
