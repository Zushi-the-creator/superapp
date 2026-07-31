"""RESEARCH CYCLE — round 2: ROBUSTNESS of the round-1 leaders.

Round 1 produced huge OOS numbers (RELSTR10-quarterly 81.9% CAGR, top5 85.2%).
Before promoting anything, the red flag has to be resolved:

    RELSTR10 IS CAGR 18.3%  vs  XLK IS 19.0%   -> LOSES in-sample
    RELSTR10 OOS CAGR 81.9% vs  XLK OOS 34.3%  -> 4.5x jump out-of-sample

A strategy whose entire edge lives in one era is era-exposure, not skill.
Round 2 runs the tests that can distinguish them:

  T1  ROLLING WALK-FORWARD      — 6-month windows across the whole decade
  T2  PER-YEAR DECOMPOSITION    — is the edge in every year or in 2023-25 only?
  T3  PARAMETER NEIGHBOURHOOD   — is quarterly/top5 a plateau or a lone spike?
  T4  CONCENTRATION / TURNOVER  — what is actually being held, and how often
  T5  SURVIVORSHIP STRESS       — re-run excluding the biggest winners
  T6  DSR at honest trial count

Tier B throughout. No promotion on T1 failure regardless of headline CAGR.
"""
exec(open('_master_harness3.py').read().split("STRATS=[")[0])
import numpy as np, math, bisect
from collections import Counter, defaultdict

IS0 = next(i for i, d in enumerate(dates) if d >= '2016-06-01')
OOS0 = next(i for i, d in enumerate(dates) if d >= '2023-01-03')
XLi = C.columns.get_loc('XLK'); SPi = C.columns.get_loc('SPY'); QQi = C.columns.get_loc('QQQ')
Q_ENDS = {i for i in me if dates[i][5:7] in ('03', '06', '09', '12')}
_vol63 = C.pct_change(fill_method=None).rolling(63, min_periods=55).std().values


def rot(sel, top_n, s0, s1=None, rebal=None, weight='eq', ban=None):
    rb = me if rebal is None else rebal
    fee = FEE + SLIP; end = (s1 if s1 is not None else ND - 1)
    eq = 1.0; hold = {}; c = [1.0]; picks = []
    for i in range(s0, end + 1):
        if hold:
            num = 0.0; wsum = 0.0
            for col, w in hold.items():
                if not (np.isfinite(Cv[i, col]) and np.isfinite(Cv[i - 1, col])
                        and Cv[i - 1, col] > 0 and i <= last_valid[col]):
                    continue
                num += w * (Cv[i, col] / Cv[i - 1, col] - 1); wsum += w
            eq *= (1 + num / wsum) if wsum > 0 else 1.0
        if (i - 1 in rb):
            j = i - 1
            new = sel(j, top_n)
            if ban: new = [x for x in new if C.columns[x] not in ban]
            if new:
                if weight == 'ivol':
                    ws = np.array([1.0 / max(_vol63[j, x], 1e-4) if np.isfinite(_vol63[j, x]) else 0.0 for x in new])
                    if ws.sum() <= 0: ws = np.ones(len(new))
                else:
                    ws = np.ones(len(new), dtype=float)
                ws = ws / ws.sum()
                ch = len(set(new) ^ set(hold))
                eq *= 1 - fee * 2 * (ch / max(len(new) + len(hold), 1))
                hold = {x: float(w) for x, w in zip(new, ws)}
                picks.append((j, [C.columns[x] for x in new]))
        c.append(eq)
    return np.array(c), picks


def cagr(c):
    c = np.asarray(c, float); return (c[-1] / c[0]) ** (252 / max(len(c) - 1, 1)) - 1


def mdd(c):
    c = np.asarray(c, float); pk = np.maximum.accumulate(c); return (c / pk - 1).min()


RS = mk_relstr(99, 'XLK')
CANDS = [
    ('RELSTR10 monthly top10', lambda a, b, ban=None: rot(RS, 10, a, b, ban=ban)),
    ('RELSTR10 QUARTERLY top10', lambda a, b, ban=None: rot(RS, 10, a, b, rebal=Q_ENDS, ban=ban)),
    ('RELSTR10 monthly top5', lambda a, b, ban=None: rot(RS, 5, a, b, ban=ban)),
    ('RELSTR10 monthly ivol', lambda a, b, ban=None: rot(RS, 10, a, b, weight='ivol', ban=ban)),
    ('LC12-1 monthly top10', lambda a, b, ban=None: rot(lc121, 10, a, b, ban=ban)),
]

# ───────────────────────── T1 ROLLING WALK-FORWARD ─────────────────────────
print("=" * 104)
print("T1 — ROLLING WALK-FORWARD: 6-month windows, whole decade. No window is 'out of sample' in a")
print("     special era; a real edge shows up in most of them.")
print("=" * 104)
starts = []
y, mn = 2017, 1
while (y, mn) <= (2026, 1):
    starts.append(f"{y:04d}-{mn:02d}-01"); mn += 6
    if mn > 12: y, mn = y + 1, mn - 12
dpos = lambda s: min(bisect.bisect_left(dates, s), ND - 1)

print(f"{'window':<11}" + "".join(f"{n.replace('RELSTR10 ','R10-').replace('monthly ','m-'):>17}" for n, _ in CANDS) + f"{'XLK':>9}")
wins = {n: 0 for n, _ in CANDS}; series = {n: [] for n, _ in CANDS}; bser = []
for s in starts:
    a = dpos(s)
    nxt = f"{int(s[:4]) + (1 if s[5:7] == '07' else 0)}-{'01' if s[5:7] == '07' else '07'}-01"
    b = min(dpos(nxt), ND - 1)
    if b - a < 60: continue
    bx = Cf[b, XLi] / Cf[a, XLi] - 1; bser.append(bx)
    line = f"{s:<11}"
    for n, f in CANDS:
        r = f(a, b)[0][-1] - 1
        series[n].append(r)
        if r > bx: wins[n] += 1
        line += f"{r * 100:>+16.1f}%"
    print(line + f"{bx * 100:>+8.1f}%")
print("-" * 104)
nw = len(bser)
for lbl, fn in [('compounded', lambda v: (np.prod(1 + np.array(v)) - 1) * 100),
                ('median', lambda v: np.median(v) * 100),
                ('worst', lambda v: np.min(v) * 100)]:
    print(f"{lbl:<11}" + "".join(f"{fn(series[n]):>+16.1f}%" for n, _ in CANDS) + f"{fn(bser):>+8.1f}%")
print(f"{'beat XLK':<11}" + "".join(f"{wins[n]:>13}/{nw}" for n, _ in CANDS))

# ───────────────────────── T2 PER-YEAR ─────────────────────────
print("\n" + "=" * 104)
print("T2 — PER-YEAR: where does the edge actually live?")
print("=" * 104)
print(f"{'year':<7}" + "".join(f"{n.replace('RELSTR10 ','R10-').replace('monthly ','m-'):>17}" for n, _ in CANDS) + f"{'XLK':>9}")
for yy in range(2017, 2027):
    a = dpos(f'{yy}-01-01'); b = min(dpos(f'{yy + 1}-01-01'), ND - 1)
    if b - a < 60: continue
    bx = Cf[b, XLi] / Cf[a, XLi] - 1
    line = f"{yy}{'*' if yy == 2026 else ' '}   "
    for n, f in CANDS:
        line += f"{(f(a, b)[0][-1] - 1) * 100:>+16.1f}%"
    print(line + f"{bx * 100:>+8.1f}%")

# ───────────────────────── T3 PARAMETER NEIGHBOURHOOD ─────────────────────────
print("\n" + "=" * 104)
print("T3 — PARAMETER NEIGHBOURHOOD (OOS CAGR %). A real effect is a plateau; an artifact is a spike.")
print("=" * 104)
BW = set(list(me) + [i for i in range(ND - 1) if dates[i][8:10] <= '15' < dates[i + 1][8:10]])
FREQ = [('semi-mo', BW), ('monthly', me), ('quarterly', Q_ENDS)]
NS = [3, 5, 8, 10, 15, 20]
print(f"{'freq':<11}" + "".join(f"{'top' + str(n):>11}" for n in NS))
grid = {}
for fn_, rb in FREQ:
    row = f"{fn_:<11}"
    for n in NS:
        v = cagr(rot(RS, n, OOS0, rebal=rb)[0]) * 100
        grid[(fn_, n)] = v; row += f"{v:>10.1f}%"
    print(row)
vals = np.array(list(grid.values()))
best = max(grid, key=grid.get)
neigh = [grid[k] for k in grid if k != best]
print(f"\nbest cell {best} = {grid[best]:.1f}%   rest: mean {np.mean(neigh):.1f}% / min {np.min(neigh):.1f}%")
print(f"spike ratio (best / median of grid) = {grid[best] / np.median(vals):.2f}x   (>1.5x = suspect single-cell artifact)")

# ───────────────────────── T4 CONCENTRATION / TURNOVER ─────────────────────────
print("\n" + "=" * 104)
print("T4 — WHAT IS IT ACTUALLY HOLDING? (OOS 2023+)")
print("=" * 104)
for n, f in CANDS[:3]:
    _, picks = f(OOS0, ND - 1)
    flat = [t for _, ts in picks for t in ts]
    cnt = Counter(flat)
    swaps = np.mean([len(set(picks[i][1]) ^ set(picks[i - 1][1])) / 2 for i in range(1, len(picks))]) if len(picks) > 1 else 0
    print(f"\n  {n}:  {len(picks)} rebalances, {swaps:.1f} name-swaps each, {len(cnt)} distinct names")
    print(f"    top holdings: " + ", ".join(f"{t}({c})" for t, c in cnt.most_common(10)))
    top5share = sum(c for _, c in cnt.most_common(5)) / max(len(flat), 1) * 100
    print(f"    top-5 names = {top5share:.0f}% of all slot-months")

# ───────────────────────── T5 SURVIVORSHIP / WINNER STRESS ─────────────────────────
print("\n" + "=" * 104)
print("T5 — WINNER-EXCLUSION STRESS: ban the names it leaned on. If the edge is a process,")
print("     it survives; if it was one or two stocks, it collapses.")
print("=" * 104)
_, picks = CANDS[0][1](OOS0, ND - 1)
top_names = [t for t, _ in Counter(t for _, ts in picks for t in ts).most_common(10)]
print(f"most-held OOS names: {top_names}")
print(f"\n{'banned':<28}" + "".join(f"{n.replace('RELSTR10 ','R10-').replace('monthly ','m-'):>17}" for n, _ in CANDS[:4]))
for k in (0, 1, 3, 5, 10):
    ban = set(top_names[:k])
    row = f"{('none' if k == 0 else 'top-' + str(k) + ': ' + ','.join(top_names[:min(k,3)]) + ('...' if k > 3 else '')):<28}"
    for n, f in CANDS[:4]:
        row += f"{cagr(f(OOS0, ND - 1, ban)[0]) * 100:>16.1f}%"
    print(row)

# ───────────────────────── T6 DSR ─────────────────────────
print("\n" + "=" * 104)
print("T6 — DEFLATED SHARPE at honest trial counts (same-window moments)")
print("=" * 104)
DNS = {}; exec(open('_dsr.py').read().split("if __name__")[0], DNS); dsr = DNS['dsr']
print(f"{'candidate':<28}{'OOS CAGR':>10}{'MDD':>8}{'Sharpe':>8}{'N=1':>8}{'N=40':>8}{'N=80':>8}  verdict")
for n, f in CANDS + [('XLK buy-hold', lambda a, b, ban=None: (np.array([Cf[i, XLi] / Cf[a, XLi] for i in range(a, b + 1)]), []))]:
    c = np.asarray(f(OOS0, ND - 1)[0], float)
    r = np.diff(c) / c[:-1]; Tn = len(r)
    sh = (r.mean() / (r.std() + 1e-12)) * math.sqrt(252)
    sk = float(((r - r.mean()) ** 3).mean() / (r.std() ** 3 + 1e-12))
    ku = float(((r - r.mean()) ** 4).mean() / (r.std() ** 4 + 1e-12))
    d1, _ = dsr(sh, Tn, 1, sk, ku); d40, _ = dsr(sh, Tn, 40, sk, ku); d80, _ = dsr(sh, Tn, 80, sk, ku)
    v = "PASS@80" if d80 >= .95 else ("PASS@40" if d40 >= .95 else ("PASS@1" if d1 >= .95 else "FAIL"))
    print(f"{n:<28}{cagr(c) * 100:>9.1f}%{mdd(c) * 100:>7.1f}%{sh:>8.2f}{d1:>8.3f}{d40:>8.3f}{d80:>8.3f}  {v}")
