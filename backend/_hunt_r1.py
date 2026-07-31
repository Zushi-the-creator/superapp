"""RESEARCH CYCLE — round 1. Hunting for a strategy that beats MIX9-XLK.

Incumbent to beat (OOS 2023-01+, regime-fixed harness):
    MIX9-XLK   40.6% CAGR / -35.4% MDD / Sharpe 1.41
    RELSTR10   46.9% CAGR / -42.5% MDD / Sharpe 1.11   <- highest raw CAGR
    XLK        34.3% CAGR / -25.8% MDD / Sharpe 1.34   <- house benchmark

Round 1 tests structural dimensions never swept before, all on the canonical
harness (point-in-time sector map, prod-exact regimes, next-open, both-leg costs):
  A  basket size N sweep                    (is 10 right?)
  B  rebalance frequency                    (monthly vs quarterly vs 2-week)
  C  intra-basket weighting                 (equal vs inverse-vol vs rank)
  D  absolute-momentum / trend overlay      (dual momentum)
  E  regime parking                         (sit out DANGER/CRISIS in SPY)
  F  lottery-stock exclusion (Bali MAX)     (drop high max-daily-return names)
  G  blend of the two best sleeves          (RELSTR10 + LC12-1)

Every cell reports IS and OOS separately. IS-only winners are NOT promoted.
Tier B throughout (survivor universe = ceiling).
"""
exec(open('_master_harness3.py').read().split("STRATS=[")[0])
import numpy as np, math
from collections import defaultdict

IS0 = next(i for i, d in enumerate(dates) if d >= '2016-06-01')
OOS0 = next(i for i, d in enumerate(dates) if d >= '2023-01-03')
XLi = C.columns.get_loc('XLK'); SPi = C.columns.get_loc('SPY')

# realised daily vol (for inverse-vol weighting) and Bali MAX (lottery proxy)
_dret = C.pct_change(fill_method=None)
_vol63 = _dret.rolling(63, min_periods=55).std().values
_max21 = _dret.rolling(21, min_periods=18).max().values

# rebalance day sets
Q_ENDS = {i for i in me if dates[i][5:7] in ('03', '06', '09', '12')}
BW_ENDS = set(list(me) + [i for i in range(ND - 1)
                          if dates[i][8:10] <= '15' < dates[i + 1][8:10]])


def rot(sel, top_n, s0, rebal=None, weight='eq', park_regimes=None, trend_gate=False):
    """Generic monthly-ish rotation. Enters at next open, charges both legs.

    weight:        'eq' | 'ivol' (inverse 63d vol) | 'rank' (linear by rank)
    park_regimes:  set of regime names during which the book sits in SPY
    trend_gate:    only hold names above their own 200d SMA (absolute momentum)
    """
    rb = me if rebal is None else rebal
    fee = FEE + SLIP
    eq = 1.0; hold = {}; c = [1.0]; parked = False
    for i in range(s0, ND):
        if parked:
            a, b = Cf[i - 1, SPi], Cf[i, SPi]
            eq *= (b / a) if (np.isfinite(a) and np.isfinite(b) and a > 0) else 1.0
        elif hold:
            num = 0.0; wsum = 0.0
            for col, w in hold.items():
                if not (np.isfinite(Cv[i, col]) and np.isfinite(Cv[i - 1, col])
                        and Cv[i - 1, col] > 0 and i <= last_valid[col]):
                    continue
                num += w * (Cv[i, col] / Cv[i - 1, col] - 1); wsum += w
            eq *= (1 + num / wsum) if wsum > 0 else 1.0
        # regime parking decision (uses only today's regime, known at close)
        want_park = bool(park_regimes) and R[i] in park_regimes
        if want_park != parked:
            eq *= 1 - fee; parked = want_park
        if (i - 1 in rb) and not parked:
            j = i - 1
            new = sel(j, top_n)
            if trend_gate:
                new = [col for col in new
                       if np.isfinite(_s200[j, col]) and Cv[j, col] > _s200[j, col]]
            if new:
                if weight == 'ivol':
                    ws = np.array([1.0 / max(_vol63[j, col], 1e-4)
                                   if np.isfinite(_vol63[j, col]) else 0.0 for col in new])
                    if ws.sum() <= 0: ws = np.ones(len(new))
                elif weight == 'rank':
                    ws = np.arange(len(new), 0, -1, dtype=float)
                else:
                    ws = np.ones(len(new), dtype=float)
                ws = ws / ws.sum()
                ch = len(set(new) ^ set(hold))
                eq *= 1 - fee * 2 * (ch / max(len(new) + len(hold), 1))
                hold = {col: float(w) for col, w in zip(new, ws)}
        c.append(eq)
    return np.array(c)


def mk_max_filter(base_sel, drop_frac=0.2):
    """Bali/Cakici/Whitelaw: drop the highest max-daily-return (lottery) names."""
    def f(j, n):
        wide = base_sel(j, int(n / (1 - drop_frac)) + 3)
        if not wide: return []
        scored = [(c, _max21[j, c] if np.isfinite(_max21[j, c]) else 9e9) for c in wide]
        scored.sort(key=lambda x: x[1])
        return [c for c, _ in scored[:n]]
    return f


def stats(c, a, b):
    seg = np.asarray(c, float)[a:b]; seg = seg / seg[0]
    r = np.diff(seg) / seg[:-1]; T = len(r)
    pk = np.maximum.accumulate(seg)
    cg = (seg[-1] ** (252 / T) - 1) * 100
    md = (seg / pk - 1).min() * 100
    sh = (r.mean() / (r.std() + 1e-12)) * math.sqrt(252)
    return cg, md, sh, cg / abs(md) if md else 0


RS = mk_relstr(99, 'XLK')
RESULTS = []


def run(label, fn, group):
    try:
        ci = fn(IS0)[:OOS0 - IS0]
        co = fn(OOS0)
    except Exception as e:
        print(f"  ERR {label}: {e}"); return
    i_c, i_m, i_s, _ = stats(ci, 0, len(ci))
    o_c, o_m, o_s, o_mar = stats(co, 0, len(co))
    RESULTS.append((group, label, i_c, o_c, o_m, o_s, o_mar))
    print(f"  {label:<44}{i_c:>8.1f}%{o_c:>9.1f}%{o_m:>8.1f}%{o_s:>7.2f}{o_mar:>7.2f}", flush=True)


HDR = f"  {'variant':<44}{'IS CAGR':>8}{'OOS CAGR':>9}{'OOS MDD':>8}{'Shrp':>7}{'MAR':>7}"

print("=" * 96); print("BASELINES"); print("=" * 96); print(HDR)
run('XLK buy-hold [bench]', lambda s: bh(XL, s), 'base')
run('RELSTR10 top10 eq monthly [incumbent]', lambda s: rot(RS, 10, s), 'base')
run('LC 12-1 top10 eq monthly', lambda s: rot(lc121, 10, s), 'base')
run('NULL CHECK', lambda s: rot(lambda j, n: [], 10, s), 'base')

print("\n" + "=" * 96); print("A — BASKET SIZE SWEEP"); print("=" * 96); print(HDR)
for n in (5, 8, 10, 15, 20, 30):
    run(f'RELSTR10 top{n}', lambda s, n=n: rot(RS, n, s), 'A')
for n in (5, 10, 20):
    run(f'LC12-1 top{n}', lambda s, n=n: rot(lc121, n, s), 'A')

print("\n" + "=" * 96); print("B — REBALANCE FREQUENCY"); print("=" * 96); print(HDR)
run('RELSTR10 quarterly', lambda s: rot(RS, 10, s, rebal=Q_ENDS), 'B')
run('RELSTR10 semi-monthly', lambda s: rot(RS, 10, s, rebal=BW_ENDS), 'B')
run('LC12-1 quarterly', lambda s: rot(lc121, 10, s, rebal=Q_ENDS), 'B')

print("\n" + "=" * 96); print("C — INTRA-BASKET WEIGHTING"); print("=" * 96); print(HDR)
run('RELSTR10 inverse-vol', lambda s: rot(RS, 10, s, weight='ivol'), 'C')
run('RELSTR10 rank-weight', lambda s: rot(RS, 10, s, weight='rank'), 'C')
run('LC12-1 inverse-vol', lambda s: rot(lc121, 10, s, weight='ivol'), 'C')

print("\n" + "=" * 96); print("D — ABSOLUTE-MOMENTUM (TREND) GATE"); print("=" * 96); print(HDR)
run('RELSTR10 + own-200SMA gate', lambda s: rot(RS, 10, s, trend_gate=True), 'D')
run('LC12-1 + own-200SMA gate', lambda s: rot(lc121, 10, s, trend_gate=True), 'D')

print("\n" + "=" * 96); print("E — REGIME PARKING (sit out in SPY)"); print("=" * 96); print(HDR)
for nm, rg in [('DANGER+CRISIS', {'DANGER', 'CRISIS'}),
               ('DANGER+CRISIS+WEAK', {'DANGER', 'CRISIS', 'WEAK'}),
               ('CRISIS only', {'CRISIS'})]:
    run(f'RELSTR10 park {nm}', lambda s, rg=rg: rot(RS, 10, s, park_regimes=rg), 'E')
run('LC12-1 park DANGER+CRISIS', lambda s: rot(lc121, 10, s, park_regimes={'DANGER', 'CRISIS'}), 'E')

print("\n" + "=" * 96); print("F — LOTTERY-STOCK EXCLUSION (Bali MAX)"); print("=" * 96); print(HDR)
run('RELSTR10 drop top-20% MAX', lambda s: rot(mk_max_filter(RS, 0.2), 10, s), 'F')
run('LC12-1 drop top-20% MAX', lambda s: rot(mk_max_filter(lc121, 0.2), 10, s), 'F')

print("\n" + "=" * 96); print("G — SLEEVE BLENDS"); print("=" * 96); print(HDR)
run('50/50 RELSTR10 + LC12-1', lambda s: _blend(rot(RS, 10, s), rot(lc121, 10, s), 0.5), 'G')
run('70/30 RELSTR10 + XLK', lambda s: _blend(rot(RS, 10, s), bh(XL, s), 0.3), 'G')
run('50/50 RELSTR10 + XLK', lambda s: _blend(rot(RS, 10, s), bh(XL, s), 0.5), 'G')
run('40/30/30 RELSTR+LC+XLK',
    lambda s: _blend(_blend(rot(RS, 10, s), rot(lc121, 10, s), 0.43), bh(XL, s), 0.3), 'G')

print("\n" + "=" * 96)
print("ROUND 1 LEADERBOARD — ranked by OOS MAR (CAGR / |MDD|), the risk-adjusted bar")
print("=" * 96)
print(f"{'grp':<4}{'variant':<44}{'IS':>8}{'OOS':>9}{'MDD':>8}{'Shrp':>7}{'MAR':>7}")
xlk = [r for r in RESULTS if 'XLK buy-hold' in r[1]][0]
for g, l, ic, oc, om, os_, mar in sorted(RESULTS, key=lambda x: -x[6])[:18]:
    flag = ''
    if oc > 40.6 and mar > xlk[6]: flag = '  <-- beats MIX9 CAGR + XLK MAR'
    elif mar > xlk[6]: flag = '  <-- beats XLK MAR'
    print(f"{g:<4}{l:<44}{ic:>7.1f}%{oc:>8.1f}%{om:>7.1f}%{os_:>7.2f}{mar:>7.2f}{flag}")
print(f"\nreference: XLK MAR {xlk[6]:.2f} | MIX9-XLK OOS 40.6% / -35.4% / MAR 1.15 / Sharpe 1.41")
print(f"variants tested this round: {len(RESULTS)} (adds to the DSR trial count)")
