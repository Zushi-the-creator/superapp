"""RESEARCH CYCLE — round 3: TIER A ONLY (index/ETF, zero survivorship bias).

Round 2 killed the round-1 leaders. RELSTR10's apparent 65-85% OOS CAGR is:
  - a coin flip window-by-window (beat XLK 10/19 rolling windows)
  - a loser in 5 of 10 calendar years
  - DESTROYED by banning its 10 most-held names: 65.4% -> 23.5%, i.e. BELOW XLK's
    34.3%. In a survivor universe those 10 names (PLTR/NVDA/APP/HOOD/CVNA/MSTR...)
    are precisely the ones we know ex-post won.
  - failing DSR at any honest trial count

So stock-picking on a survivor universe cannot be trusted no matter how good the
number looks. Round 3 moves to strategies built ONLY on index/sector ETFs, where
the universe is fixed in advance and survivorship inflation is structurally
impossible. A weaker-looking Tier A number is worth more than a big Tier B one.

  S1  leveraged-trend satellite sweep  (Gayed family: core + levered sleeve on trend)
  S2  trend-signal robustness          (SMA100/150/200/250, dual-confirm)
  S3  core asset sweep                 (QQQ vs XLK vs SPY vs EW-sector)
  S4  vol-targeted index               (scale exposure to a target vol)
  S5  sector-ETF momentum rotation     (top-k of 11 SPDRs, various lookbacks)
  S6  best combos -> rolling walk-forward + DSR
"""
exec(open('_master_harness3.py').read().split("STRATS=[")[0])
import numpy as np, math, bisect

IS0 = next(i for i, d in enumerate(dates) if d >= '2016-06-01')
OOS0 = next(i for i, d in enumerate(dates) if d >= '2023-01-03')
IDX = {t: C.columns.get_loc(t) for t in ['QQQ', 'SPY', 'XLK'] if t in C.columns}
SPD = [s for s in ['XLK', 'XLV', 'XLF', 'XLE', 'XLI', 'XLP', 'XLY', 'XLU', 'XLB', 'XLRE'] if s in C.columns]
SPDi = [C.columns.get_loc(s) for s in SPD]
EWa = np.zeros(ND)
for i in range(1, ND):
    rs = [Cf[i, k] / Cf[i - 1, k] - 1 for k in SPDi
          if np.isfinite(Cf[i, k]) and np.isfinite(Cf[i - 1, k]) and Cf[i - 1, k] > 0]
    EWa[i] = np.mean(rs) if rs else 0.0
EW = np.cumprod(1 + EWa)

def series(name):
    if name == 'EW10': return EW
    return Cf[:, IDX[name]]

SMA = {}
for nm in list(IDX) + ['EW10']:
    s = pd.Series(series(nm))
    for w in (100, 150, 200, 250):
        SMA[(nm, w)] = s.rolling(w, min_periods=int(w * 0.9)).mean().values
VOLD = {nm: pd.Series(series(nm)).pct_change(fill_method=None).rolling(21, min_periods=18).std().values
        for nm in list(IDX) + ['EW10']}


def sat_curve(core, sat_frac, mult, s0, sma_w=200, er=0.0095, dual=False):
    """core index + levered satellite that is only invested while core > SMA."""
    A = series(core); m1 = SMA[(core, sma_w)]
    m2 = SMA[(core, 50)] if dual and (core, 50) in SMA else None
    eq = 1.0; c = [1.0]; inp = True
    for i in range(s0, ND):
        dg = (er + (mult - 1) * RATEA[i]) / 252
        a, b = A[i - 1], A[i]
        r = (b / a - 1) if (np.isfinite(a) and np.isfinite(b) and a > 0) else 0.0
        w = bool(np.isfinite(m1[i - 1]) and A[i - 1] > m1[i - 1])
        if dual and m2 is not None and np.isfinite(m2[i - 1]):
            w = w and A[i - 1] > m2[i - 1]
        if w != inp:
            eq *= 1 - sat_frac * (EFEE + SLIP); inp = w
        eq *= (1 + (1 - sat_frac) * r + sat_frac * ((mult * r - dg) if inp else 0.0))
        c.append(eq)
    return np.array(c)


def voltarget(core, tgt, s0, cap=2.0, er=0.0009):
    """scale index exposure so realised 21d vol ~= tgt (annualised). Idle earns cash."""
    A = series(core); v = VOLD[core]
    eq = 1.0; c = [1.0]; prev_w = 1.0
    for i in range(s0, ND):
        a, b = A[i - 1], A[i]
        r = (b / a - 1) if (np.isfinite(a) and np.isfinite(b) and a > 0) else 0.0
        rv = v[i - 1] * math.sqrt(252) if np.isfinite(v[i - 1]) and v[i - 1] > 0 else tgt
        w = float(np.clip(tgt / rv, 0.0, cap))
        if abs(w - prev_w) > 0.10:
            eq *= 1 - abs(w - prev_w) * (EFEE + SLIP); prev_w = w
        else:
            w = prev_w
        dg = (er + max(w - 1, 0) * RATEA[i]) / 252
        eq *= (1 + w * r - dg + max(1 - w, 0) * RATEA[i] / 252)
        c.append(eq)
    return np.array(c)


def spdr_rot(k, lb, s0, gate=False):
    """top-k of the 11 SPDR sectors by lb-day return, monthly. Optional SMA200 gate."""
    fee = EFEE + SLIP; eq = 1.0; hold = []; c = [1.0]
    s200 = {j: pd.Series(Cf[:, j]).rolling(200, min_periods=180).mean().values for j in SPDi}
    for i in range(s0, ND):
        if hold:
            rs = [Cf[i, j] / Cf[i - 1, j] - 1 for j in hold
                  if np.isfinite(Cf[i, j]) and np.isfinite(Cf[i - 1, j]) and Cf[i - 1, j] > 0]
            eq *= (1 + np.mean(rs)) if rs else 1.0
        if i - 1 in me:
            j0 = i - 1
            sc = [(Cf[j0, j] / Cf[j0 - lb, j] - 1, j) for j in SPDi
                  if j0 >= lb and np.isfinite(Cf[j0 - lb, j]) and Cf[j0 - lb, j] > 0]
            sc.sort(reverse=True)
            new = [j for _, j in sc[:k]]
            if gate:
                new = [j for j in new if np.isfinite(s200[j][j0]) and Cf[j0, j] > s200[j][j0]]
            ch = len(set(new) ^ set(hold))
            eq *= 1 - fee * 2 * (ch / max(len(new) + len(hold), 1))
            hold = new
        c.append(eq)
    return np.array(c)


def st(c, a, b):
    seg = np.asarray(c, float)[a:b]; seg = seg / seg[0]
    r = np.diff(seg) / seg[:-1]; pk = np.maximum.accumulate(seg)
    cg = (seg[-1] ** (252 / len(r)) - 1) * 100
    md = (seg / pk - 1).min() * 100
    return cg, md, (r.mean() / (r.std() + 1e-12)) * math.sqrt(252), cg / abs(md) if md else 0


RES = []
def run(lbl, grp, fn):
    try:
        ci = fn(IS0)[:OOS0 - IS0]; co = fn(OOS0)
    except Exception as e:
        print(f"  ERR {lbl}: {e}"); return
    ic, _, _, _ = st(ci, 0, len(ci)); oc, om, os_, mar = st(co, 0, len(co))
    RES.append((grp, lbl, ic, oc, om, os_, mar))
    print(f"  {lbl:<40}{ic:>8.1f}%{oc:>9.1f}%{om:>8.1f}%{os_:>7.2f}{mar:>7.2f}", flush=True)

H = f"  {'variant':<40}{'IS CAGR':>8}{'OOS CAGR':>9}{'OOS MDD':>8}{'Shrp':>7}{'MAR':>7}"
print("=" * 92); print("BASELINES (Tier A)"); print("=" * 92); print(H)
for nm in ['XLK', 'QQQ', 'SPY']:
    run(f'{nm} buy-hold', 'base', lambda s, nm=nm: np.array([series(nm)[i] / series(nm)[s] for i in range(s, ND)]))
run('EW 10-sector buy-hold', 'base', lambda s: np.array([EW[i] / EW[s] for i in range(s, ND)]))

print("\n" + "=" * 92); print("S1 — LEVERAGED-TREND SATELLITE SWEEP"); print("=" * 92); print(H)
for core in ['QQQ', 'XLK']:
    for sf in (0.15, 0.20, 0.30, 0.40):
        for mu in (2, 3):
            run(f'{core} core + {int(sf*100)}% {mu}x-trend', 'S1',
                lambda s, c=core, f=sf, m=mu: sat_curve(c, f, m, s))

print("\n" + "=" * 92); print("S2 — TREND-SIGNAL ROBUSTNESS (QQQ 20% 3x)"); print("=" * 92); print(H)
for w in (100, 150, 200, 250):
    run(f'QQQ 20% 3x, SMA{w}', 'S2', lambda s, w=w: sat_curve('QQQ', 0.20, 3, s, sma_w=w))

print("\n" + "=" * 92); print("S3 — CORE ASSET SWEEP (20% 3x satellite)"); print("=" * 92); print(H)
for core in ['QQQ', 'XLK', 'SPY']:
    run(f'{core} 20% 3x-trend', 'S3', lambda s, c=core: sat_curve(c, 0.20, 3, s))

print("\n" + "=" * 92); print("S4 — VOL-TARGETED INDEX"); print("=" * 92); print(H)
for core in ['QQQ', 'XLK']:
    for tg in (0.15, 0.20, 0.25):
        run(f'{core} vol-target {int(tg*100)}%', 'S4', lambda s, c=core, t=tg: voltarget(c, t, s))

print("\n" + "=" * 92); print("S5 — SECTOR-ETF MOMENTUM ROTATION"); print("=" * 92); print(H)
for k in (2, 3, 4):
    for lb in (63, 126, 252):
        run(f'SPDR top{k} {lb}d mom', 'S5', lambda s, k=k, l=lb: spdr_rot(k, l, s))
run('SPDR top3 126d + SMA200 gate', 'S5', lambda s: spdr_rot(3, 126, s, gate=True))

print("\n" + "=" * 92)
print("TIER A LEADERBOARD — ranked by OOS MAR. Zero survivorship bias in ANY of these.")
print("=" * 92)
print(f"{'grp':<5}{'variant':<40}{'IS':>8}{'OOS':>9}{'MDD':>8}{'Shrp':>7}{'MAR':>7}")
xk = [r for r in RES if r[1] == 'XLK buy-hold'][0]
for g, l, ic, oc, om, os_, mar in sorted(RES, key=lambda x: -x[6])[:15]:
    f = ''
    if mar > xk[6] and oc > xk[3]: f = '  <-- beats XLK on BOTH return and MAR'
    elif mar > xk[6]: f = '  <-- better MAR, lower return'
    print(f"{g:<5}{l:<40}{ic:>7.1f}%{oc:>8.1f}%{om:>7.1f}%{os_:>7.2f}{mar:>7.2f}{f}")
print(f"\nXLK reference: OOS {xk[3]:.1f}% / MDD {xk[4]:.1f}% / Sharpe {xk[5]:.2f} / MAR {xk[6]:.2f}")
print(f"variants this round: {len(RES)}")

# ── S6 rolling walk-forward + DSR on the Tier A leaders ──
print("\n" + "=" * 92)
print("S6 — ROLLING WALK-FORWARD (6-month windows) on the top Tier A candidates")
print("=" * 92)
TOP = [(l, g) for g, l, *_ in sorted(RES, key=lambda x: -x[6])[:4] if g != 'base']
FN = {}
for l, g in TOP:
    if 'vol-target' in l:
        c0, t0 = l.split()[0], int(l.split()[-1].strip('%')) / 100
        FN[l] = lambda a, b, c0=c0, t0=t0: voltarget(c0, t0, a)[:b - a + 1]
    elif 'SPDR' in l:
        k0 = int(l.split()[1][3:]); l0 = int(l.split()[2][:-1])
        FN[l] = lambda a, b, k0=k0, l0=l0: spdr_rot(k0, l0, a)[:b - a + 1]
    elif 'SMA' in l:
        w0 = int(l.split('SMA')[1]); FN[l] = lambda a, b, w0=w0: sat_curve('QQQ', 0.20, 3, a, sma_w=w0)[:b - a + 1]
    else:
        p = l.split(); c0 = p[0]; sf0 = int(p[2].strip('%')) / 100 if '%' in p[2] else 0.20
        mu0 = 3 if '3x' in l else 2
        FN[l] = lambda a, b, c0=c0, sf0=sf0, mu0=mu0: sat_curve(c0, sf0, mu0, a)[:b - a + 1]
FN['XLK buy-hold'] = lambda a, b: np.array([Cf[i, IDX['XLK']] / Cf[a, IDX['XLK']] for i in range(a, b + 1)])
starts = []; y, mn = 2017, 1
while (y, mn) <= (2026, 1):
    starts.append(f"{y:04d}-{mn:02d}-01"); mn += 6
    if mn > 12: y, mn = y + 1, mn - 12
dpos = lambda s: min(bisect.bisect_left(dates, s), ND - 1)
ks = list(FN)
print(f"{'window':<11}" + "".join(f"{k[:22]:>24}" for k in ks))
ser = {k: [] for k in ks}
for s in starts:
    a = dpos(s)
    nx = f"{int(s[:4]) + (1 if s[5:7] == '07' else 0)}-{'01' if s[5:7] == '07' else '07'}-01"
    b = min(dpos(nx), ND - 1)
    if b - a < 60: continue
    line = f"{s:<11}"
    for k in ks:
        r = FN[k](a, b)[-1] - 1; ser[k].append(r); line += f"{r * 100:>+23.1f}%"
    print(line)
print("-" * (11 + 24 * len(ks)))
bx = ser['XLK buy-hold']
for lbl, f in [('compounded', lambda v: (np.prod(1 + np.array(v)) - 1) * 100),
               ('median', lambda v: np.median(v) * 100), ('worst', lambda v: np.min(v) * 100)]:
    print(f"{lbl:<11}" + "".join(f"{f(ser[k]):>+23.1f}%" for k in ks))
print(f"{'beat XLK':<11}" + "".join(f"{sum(1 for i, v in enumerate(ser[k]) if v > bx[i]):>20}/{len(bx)}" for k in ks))

print("\n" + "=" * 92); print("DSR (OOS window, honest trial counts)"); print("=" * 92)
DNS = {}; exec(open('_dsr.py').read().split("if __name__")[0], DNS); dsr = DNS['dsr']
print(f"{'candidate':<30}{'Sharpe':>8}{'N=1':>8}{'N=40':>8}{'N=80':>8}  verdict")
for k in ks:
    c = np.asarray(FN[k](OOS0, ND - 1), float)
    r = np.diff(c) / c[:-1]; sh = (r.mean() / (r.std() + 1e-12)) * math.sqrt(252)
    sk = float(((r - r.mean()) ** 3).mean() / (r.std() ** 3 + 1e-12))
    ku = float(((r - r.mean()) ** 4).mean() / (r.std() ** 4 + 1e-12))
    d1, _ = dsr(sh, len(r), 1, sk, ku); d40, _ = dsr(sh, len(r), 40, sk, ku); d80, _ = dsr(sh, len(r), 80, sk, ku)
    v = "PASS@80" if d80 >= .95 else ("PASS@40" if d40 >= .95 else ("PASS@1" if d1 >= .95 else "FAIL"))
    print(f"{k:<30}{sh:>8.2f}{d1:>8.3f}{d40:>8.3f}{d80:>8.3f}  {v}")
