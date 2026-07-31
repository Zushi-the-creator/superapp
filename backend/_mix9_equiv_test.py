"""EQUIVALENCE GATE: mix9_core.py must reproduce _master_harness3.py EXACTLY.

If the live engine's selectors differ from the backtested ones by even one name,
we are not running the strategy we validated. This test compares picks on many
historical dates and fails loudly on any mismatch.

Run this after ANY change to either file. It is the contract between research
and production.
"""
import numpy as np
from mix9_core import Mix9Data, REGMAP

print("loading harness ...", flush=True)
H = {}
exec(open('_master_harness3.py').read().split("STRATS=[")[0], H)
print("loading mix9_core ...", flush=True)
D = Mix9Data()

fails = []


def chk(ok, label, detail=""):
    if not ok: fails.append(f"{label} {detail}")
    print(f"{'PASS' if ok else '*FAIL*':<8}{label:<46}{detail}")


# ── 0. the matrices themselves must line up ──
chk(D.ND == H['ND'], "0.1 same bar count", f"core {D.ND} vs harness {H['ND']}")
chk(D.dates == H['dates'], "0.2 same date index")
chk(D.cols == list(H['C'].columns), "0.3 same ticker set", f"{len(D.cols)} tickers")
chk(np.array_equal(D.Cv, H['Cv'], equal_nan=True), "0.4 identical close matrix")
chk(np.array_equal(D.Ov, H['Ov'], equal_nan=True), "0.5 identical open matrix")
chk(np.array_equal(D.mrg, H['mrg']), "0.6 identical MR signal gate")
chk(np.array_equal(D.momg, H['momg']), "0.7 identical MOM signal gate")
chk(np.allclose(D.MRS, H['MRS'], equal_nan=True), "0.8 identical MR scores")
chk(np.allclose(D.MOMS, H['MOMS'], equal_nan=True), "0.9 identical MOM scores")
chk(np.array_equal(D.last_valid, H['last_valid']), "0.10 identical last_valid")
chk(D.month_end == H['me'], "0.11 identical month-end set")

# ── 1. regime chain, every bar ──
i0 = next(i for i, d in enumerate(D.dates) if d >= '2016-06-01')
mism = [i for i in range(i0, D.ND) if D.regime_at(i) != H['R'][i]]
chk(not mism, "1.1 regime label identical on every bar",
    f"{len(mism)} mismatches" + (f" first={D.dates[mism[0]]}" if mism else ""))

# ── 2. selectors, on every month-end (the only days that matter) ──
HSEL = {
    'TREND10':    H['_trend_sel'],
    'RELSTR10':   H['mk_relstr'](99, 'XLK'),
    'cap2+guard': H['mk_relstr'](2, 'SPY'),
    'LeadSector': H['_leadsec_sel'],
    'LC 12-1':    H['lc121'],
}
mends = sorted(j for j in H['me'] if j >= i0)
print(f"\ncomparing {len(HSEL)} selectors across {len(mends)} month-ends "
      f"({D.dates[mends[0]]} .. {D.dates[mends[-1]]}) ...", flush=True)
for name, hf in HSEL.items():
    cf = D.selector(name)
    bad = 0; first = None
    for j in mends:
        a = list(hf(j, 10)); b = list(cf(j, 10))
        if a != b:
            bad += 1
            if first is None:
                first = (D.dates[j], [H['C'].columns[x] for x in a], [D.cols[x] for x in b])
    chk(bad == 0, f"2.{name} identical picks on every month-end",
        f"{bad}/{len(mends)} differ" + (f"  first {first[0]}: harness={first[1]} core={first[2]}" if first else ""))

# ── 3. sector map ──
smis = 0
for j in mends[::6]:
    if D.sectors_at(j) != H['_sectors_at'](j): smis += 1
chk(smis == 0, "3.1 point-in-time sector map identical", f"{smis} quarters differ")

# ── 4. frozen regime map matches what the IS fit produces ──
chk(REGMAP.get('HEALTHY') == 'MOM-brk90', "4.1 REGMAP HEALTHY frozen correctly", REGMAP.get('HEALTHY'))
chk(set(REGMAP) >= {'DANGER', 'CRISIS', 'WEAK', 'CORRECTION', 'BEAR_BOUNCE',
                    'PULLBACK', 'DIP_BUY', 'SHARP_DROP', 'FEAR', 'HEALTHY'},
    "4.2 REGMAP covers every emittable regime")
unseen = {r for r in set(H['R'][i0:]) if r not in REGMAP}
chk(not unseen, "4.3 no regime can be emitted without a mapping", str(unseen))

print("\n" + "=" * 78)
if fails:
    print(f"EQUIVALENCE FAILED — {len(fails)} check(s):")
    for f in fails: print("   " + f)
    raise SystemExit(1)
print("EQUIVALENCE PASSED — mix9_core.py reproduces the harness exactly.")
print("The live engine will run the code that was backtested.")
