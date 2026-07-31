"""Three questions, answered with computation:
  Q1 is MIX9-SPY actually better than what we run today (PROD V3.6 MR-F42)?
  Q2 does that hold on DSR at honest trial counts?
  Q3 can the core be made DYNAMIC between SPY and XLK?

Q3 is the dangerous one: a dynamic core adds a NEW parameter after seeing the
static results, which is textbook overfitting. So every switch rule is scored
IS-only first, and only its OOS is reported. A dynamic core is only worth
deploying if it beats BOTH static cores out-of-sample AND the rule is simple
enough not to be curve-fit.
"""
exec(open('_strategy_mixing.py').read().split("RULES = [")[0])
import numpy as np, math, bisect
DNS = {}; exec(open('_dsr.py').read().split("if __name__")[0], DNS); dsr = DNS['dsr']

Y0 = next(i for i, d in enumerate(dates) if d >= '2026-01-02'); Y_T = Y0 - IS0
XLi = C.columns.get_loc('XLK'); SPi = C.columns.get_loc('SPY')
r_spy = np.diff(SPY) / SPY[:-1]

# ── core return series, including dynamic switch rules ──────────────────────
xl = np.array([Cf[IS0 + i, XLi] for i in range(n)])
sp = np.array([Cf[IS0 + i, SPi] for i in range(n)])
s200_x = pd.Series(xl).rolling(200, min_periods=180).mean().values
ETF_COST = EFEE + SLIP


def dyn_core(rule, lookback=63):
    """Returns (daily core return series, n_switches). Signal from bar t-1,
    applied to bar t — no lookahead. Switch cost charged on the core sleeve."""
    out = np.zeros(T); cur = 'SPY'; sw = 0
    for t in range(T):
        j = t - 1
        if j >= lookback:
            if rule == 'trend':          # XLK while XLK above its own 200SMA
                want = 'XLK' if (np.isfinite(s200_x[j]) and xl[j] > s200_x[j]) else 'SPY'
            elif rule == 'relstr':       # XLK while it is outrunning SPY
                want = 'XLK' if (xl[j] / xl[j - lookback]) > (sp[j] / sp[j - lookback]) else 'SPY'
            elif rule == 'both':
                a = np.isfinite(s200_x[j]) and xl[j] > s200_x[j]
                b = (xl[j] / xl[j - lookback]) > (sp[j] / sp[j - lookback])
                want = 'XLK' if (a and b) else 'SPY'
            else:
                want = cur
            if want != cur:
                cur = want; sw += 1
                out[t] -= ETF_COST
        out[t] += (xl[t + 1] / xl[t] - 1) if cur == 'XLK' else (sp[t + 1] / sp[t] - 1)
    return out, sw


def mix9(core_r, core_w=0.30, dd=0.15):
    eq = 1.0; out = [1.0]; pk = {k: 1.0 for k in names}; cu = {k: 1.0 for k in names}
    for t in range(T):
        for i, k in enumerate(names):
            cu[k] *= (1 + Rmat[i, t]); pk[k] = max(pk[k], cu[k])
        k = REGMAP.get(regs[t], 'TREND10'); si = names.index(k); ra = Rmat[si, t]
        if cu[k] < pk[k] * (1 - dd): ra = core_r[t]
        eq *= (1 + (1 - core_w) * ra + core_w * core_r[t]); out.append(eq)
    return np.array(out)


def sl(c, a, b=None):
    x = np.asarray(c, float)[a:(b if b is not None else len(c))]
    x = x / x[0]; r = np.diff(x) / x[:-1]; p = np.maximum.accumulate(x)
    return (x[-1] - 1) * 100, (x[-1] ** (252 / len(r)) - 1) * 100, (x / p - 1).min() * 100, \
           (r.mean() / (r.std() + 1e-12)) * math.sqrt(252)


def dsr_at(c, a, b=None, Ns=(1, 40, 120)):
    x = np.asarray(c, float)[a:(b if b is not None else len(c))]
    r = np.diff(x) / x[:-1]
    sh = (r.mean() / (r.std() + 1e-12)) * math.sqrt(252)
    sk = float(((r - r.mean()) ** 3).mean() / (r.std() ** 3 + 1e-12))
    ku = float(((r - r.mean()) ** 4).mean() / (r.std() ** 4 + 1e-12))
    return sh, [dsr(sh, len(r), N, sk, ku)[0] for N in Ns]


# PROD V3.6 — the incumbent, continuous run
prod = stock_sim_cash(lambda d: (('mr', MRS, 42) if NONPAUSE(d) else None), IS0)
prod = np.asarray(prod, float)

BOOK = {
    'PROD V3.6 MR-F42 [LIVE]': prod,
    'MIX9-SPY  (deploy pick)': mix9(r_spy),
    'MIX9-XLK  (roster 9)':    mix9(rx),
    'XLK buy-hold':            XLK,
    'SPY buy-hold':            SPY,
}
for rule in ('trend', 'relstr', 'both'):
    cr, sw = dyn_core(rule)
    BOOK[f'MIX9-DYN[{rule}] ({sw} sw)'] = mix9(cr)

print("=" * 122)
print("Q1 + Q2 — MIX9-SPY vs the incumbent, with DSR at honest trial counts")
print("=" * 122)
print(f"{'strategy':<28}{'IS CAGR':>9}{'OOS CAGR':>10}{'OOS MDD':>9}{'OOS Shrp':>10}"
      f"{'DSR N=1':>9}{'DSR N=40':>10}{'DSR N=120':>11}{'YTD':>9}")
print("-" * 122)
rows = []
for nm, c in BOOK.items():
    L = min(len(c), n)
    c = np.asarray(c, float)[:L]
    _, ic, _, _ = sl(c, 0, IS_T + 1)
    _, oc, om, osh = sl(c, IS_T)
    yt, _, _, _ = sl(c, Y_T)
    sh, ds = dsr_at(c, IS_T)
    rows.append((nm, ic, oc, om, osh, ds, yt))
for nm, ic, oc, om, osh, ds, yt in sorted(rows, key=lambda x: -x[5][1]):
    print(f"{nm:<28}{ic:>8.1f}%{oc:>9.1f}%{om:>8.1f}%{osh:>10.2f}"
          f"{ds[0]:>9.3f}{ds[1]:>10.3f}{ds[2]:>11.3f}{yt:>+8.1f}%")
print("-" * 122)
print("DSR >= 0.95 passes. N=40 is the floor for this session's search; N=120 is nearer the truth.")

print("\n" + "=" * 122)
print("Q3 — DYNAMIC CORE, scored IS-ONLY then reported OOS (the honest protocol)")
print("=" * 122)
cands = {k: v for k, v in BOOK.items() if k.startswith('MIX9')}
print(f"{'variant':<28}{'IS CAGR':>9}{'IS Shrp':>9}{'-> OOS CAGR':>13}{'OOS MDD':>9}{'OOS Shrp':>10}{'YTD':>9}")
best_is = None
for nm, c in cands.items():
    L = min(len(c), n); c = np.asarray(c, float)[:L]
    _, ic, _, ish = sl(c, 0, IS_T + 1)
    _, oc, om, osh = sl(c, IS_T)
    yt, _, _, _ = sl(c, Y_T)
    print(f"{nm:<28}{ic:>8.1f}%{ish:>9.2f}{oc:>12.1f}%{om:>8.1f}%{osh:>10.2f}{yt:>+8.1f}%")
    if best_is is None or ish > best_is[1]: best_is = (nm, ish, oc, osh)
print(f"\n  best on IS Sharpe = {best_is[0]}  ->  its OOS CAGR {best_is[2]:.1f}% / OOS Sharpe {best_is[3]:.2f}")

print("\n--- rolling 6-month walk-forward: does the dynamic core help window-by-window? ---")
starts = []; y, mn = 2018, 1
while (y, mn) <= (2026, 1):
    starts.append(f"{y:04d}-{mn:02d}-01"); mn += 6
    if mn > 12: y, mn = y + 1, mn - 12
dp = lambda s: min(bisect.bisect_left(dates, s), ND - 1) - IS0
ks = ['MIX9-SPY  (deploy pick)', 'MIX9-XLK  (roster 9)'] + [k for k in BOOK if 'DYN' in k]
print(f"{'window':<12}" + "".join(f"{k.split('(')[0].strip()[:14]:>16}" for k in ks))
ser = {k: [] for k in ks}
for s in starts:
    a = dp(s)
    nx = f"{int(s[:4]) + (1 if s[5:7] == '07' else 0)}-{'01' if s[5:7] == '07' else '07'}-01"
    b = min(dp(nx), n - 1)
    if b - a < 60 or a < 0: continue
    line = f"{s:<12}"
    for k in ks:
        c = np.asarray(BOOK[k], float); r = c[b] / c[a] - 1
        ser[k].append(r); line += f"{r * 100:>+15.1f}%"
    print(line)
print('-' * (12 + 16 * len(ks)))
for lbl, f in [('compounded', lambda v: (np.prod(1 + np.array(v)) - 1) * 100),
               ('median', lambda v: np.median(v) * 100),
               ('worst', lambda v: min(v) * 100)]:
    print(f"{lbl:<12}" + "".join(f"{f(ser[k]):>+15.1f}%" for k in ks))
base = ser['MIX9-SPY  (deploy pick)']
print(f"{'beat SPY-core':<12}" + "".join(
    f"{sum(1 for i, v in enumerate(ser[k]) if v > base[i]):>12}/{len(base)}" for k in ks))
