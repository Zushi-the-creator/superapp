"""REGIME-CONDITIONAL BACKTEST — which strategy wins in the CURRENT regime?

Builds full daily equity curves (2016+) for each strategy using the canonical
harness machinery, then measures each strategy's FORWARD 21/42/63d return
conditioned on the regime observed that day. Point-in-time throughout: the
curve at day d only reflects decisions made with data <= d.

Current regime is PULLBACK (SPY below SMA50, drawdown < 7%, no VIX crisis)
with a tech-led unwind (QQQ -8.4%, XLK -11.3% from peak).
"""
exec(open('_master_harness3.py').read().split("def m(c):")[0])
import numpy as np

IS = next(i for i, d in enumerate(dates) if d >= '2016-06-01')
NP_ = lambda d: R[d] not in {'DANGER', 'WEAK', 'CRISIS'}
DIPS = {'DIP_BUY', 'SHARP_DROP', 'BEAR_BOUNCE', 'CORRECTION'}
UP = {'HEALTHY', 'PULLBACK', 'DIP_BUY'}
XLi = C.columns.get_loc('XLK'); QQi = C.columns.get_loc('QQQ'); SPi = C.columns.get_loc('SPY')

def bh_curve(ix, s0):
    return np.array([Cf[i, ix] / Cf[s0, ix] for i in range(s0, ND)])

CURVES = {}
CURVES['XLK buy-hold']        = bh_curve(XLi, IS)
CURVES['QQQ buy-hold']        = bh_curve(QQi, IS)
CURVES['SPY buy-hold']        = bh_curve(SPi, IS)
CURVES['RELSTR10']            = monthly_rot_g(mk_relstr(99, 'XLK'), 10, IS)[1:]
CURVES['RELSTR10 cap2']       = monthly_rot_g(mk_relstr(2, 'XLK'), 10, IS)[1:]
CURVES['RELSTR10 cap2+guard'] = monthly_rot_g(mk_relstr(2, 'SPY'), 10, IS, pos_stop=0.15, dd_guard=0.12)[1:]
CURVES['TREND10']             = monthly_rot_g(_trend_sel, 10, IS)[1:]
CURVES['Leading-sector rot']  = monthly_rot_g(_leadsec_sel, 10, IS)[1:]
CURVES['LC 12-1 rotation']    = monthly_rot(None, lc121, 10, IS)
CURVES['MR-dips F90']         = stock_sim_cash(lambda d: (('mr', MRS, 90, 5)[:3] if R[d] in DIPS else None), IS) \
    if False else stock_sim_cash(lambda d: (('mr', MRS, 90) if R[d] in DIPS else None), IS)
CURVES['MR always-on F42 (PROD)'] = stock_sim_cash(lambda d: (('mr', MRS, 42) if NP_(d) else None), IS)
CURVES['MOM breakout F90']    = stock_sim_cash(lambda d: (('mom', MOMS, 90) if R[d] in UP else None), IS)

n = min(len(v) for v in CURVES.values())
for k in CURVES:
    CURVES[k] = np.asarray(CURVES[k])[:n]
reg_series = [R[IS + i] for i in range(n)]
dts = [dates[IS + i] for i in range(n)]

def fwd(curve, i, h):
    j = i + h
    return (curve[j] / curve[i] - 1) * 100 if j < len(curve) else np.nan

TARGET = 'PULLBACK'
idx = [i for i in range(n) if reg_series[i] == TARGET]
print(f"CURRENT REGIME: {TARGET}   (as of {dates[ND-1]}: SPY dd -2.4%, below SMA50; QQQ -8.4%, XLK -11.3% from peak)")
print(f"historical {TARGET} days in sample: {len(idx)} of {n}\n")
print(f"{'strategy':<26}{'fwd21d':>9}{'fwd42d':>9}{'fwd63d':>9}{'win42%':>9}{'worst42':>9}")
print('-' * 71)
rows = []
for k, cv in CURVES.items():
    f21 = np.array([fwd(cv, i, 21) for i in idx]); f21 = f21[np.isfinite(f21)]
    f42 = np.array([fwd(cv, i, 42) for i in idx]); f42 = f42[np.isfinite(f42)]
    f63 = np.array([fwd(cv, i, 63) for i in idx]); f63 = f63[np.isfinite(f63)]
    rows.append((k, f21.mean(), f42.mean(), f63.mean(), (f42 > 0).mean() * 100, f42.min()))
for k, a, b, c, w, mn in sorted(rows, key=lambda r: -r[2]):
    print(f"{k:<26}{a:>+8.2f}%{b:>+8.2f}%{c:>+8.2f}%{w:>8.0f}%{mn:>+8.1f}%")

print(f"\n=== same table, ALL regimes (baseline for comparison) ===")
print(f"{'strategy':<26}{'fwd21d':>9}{'fwd42d':>9}{'fwd63d':>9}{'win42%':>9}")
allrows = []
for k, cv in CURVES.items():
    f21 = np.array([fwd(cv, i, 21) for i in range(n)]); f21 = f21[np.isfinite(f21)]
    f42 = np.array([fwd(cv, i, 42) for i in range(n)]); f42 = f42[np.isfinite(f42)]
    f63 = np.array([fwd(cv, i, 63) for i in range(n)]); f63 = f63[np.isfinite(f63)]
    allrows.append((k, f21.mean(), f42.mean(), f63.mean(), (f42 > 0).mean() * 100))
for k, a, b, c, w in sorted(allrows, key=lambda r: -r[2]):
    print(f"{k:<26}{a:>+8.2f}%{b:>+8.2f}%{c:>+8.2f}%{w:>8.0f}%")

print(f"\n=== what FOLLOWS a PULLBACK: next regime observed (transition counts) ===")
from collections import Counter
nxt = Counter()
for i in idx:
    for j in range(i + 1, min(i + 43, n)):
        if reg_series[j] != TARGET:
            nxt[reg_series[j]] += 1; break
tot = sum(nxt.values()) or 1
for r_, c_ in nxt.most_common():
    print(f"  {r_:<14}{c_:>5}  ({c_/tot*100:>4.0f}%)")
