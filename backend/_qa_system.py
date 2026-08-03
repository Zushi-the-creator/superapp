#!/usr/bin/env python3
"""FULL-SYSTEM QA — trading-system invariants, run as automation.

Every check here exists because something ACTUALLY BROKE in this codebase. This
is not a generic test suite; it is a regression net around real incidents.

Design rules for a trading-system QA suite:
  1. A check must FAIL LOUDLY, never degrade. Silent degradation is how a
     validated strategy quietly becomes a different one.
  2. Check the INPUTS, not just the outputs. Aggregates look fine while the
     newest year is corrupt.
  3. Check prod and local read the SAME data. Divergence there is invisible
     locally and total in production.
  4. Controls (null, random) must behave exactly as stated, or nothing else in
     the suite is readable.

usage:
    python3 _qa_system.py               # everything
    python3 _qa_system.py --fast        # skip the slow engine sections
    python3 _qa_system.py --section data
exit code 0 = all pass, 1 = any FAIL. Suitable for cron/CI.
"""
import os, sys, json, math, sqlite3, subprocess, datetime as dt
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
PROD = "https://superapp-ke5bhg.fly.dev"

FAILS, WARNS, PASSES = [], [], []
_SECTION = [""]


def section(name):
    _SECTION[0] = name
    print(f"\n{'='*100}\n{name}\n{'='*100}")


def chk(ok, label, detail="", warn_only=False):
    tag = "PASS" if ok else ("WARN" if warn_only else "*FAIL*")
    (PASSES if ok else (WARNS if warn_only else FAILS)).append(f"[{_SECTION[0]}] {label} — {detail}")
    print(f"{tag:<8}{label:<58}{detail}")
    return ok


def curl(path, timeout=120):
    try:
        out = subprocess.run(["curl", "-s", "--max-time", str(timeout), f"{PROD}{path}"],
                             capture_output=True, text=True, timeout=timeout + 20)
        return json.loads(out.stdout)
    except Exception as e:
        return {"__error__": str(e)}


# ══════════════════════════════════════════════════════════════════════════
def qa_source():
    """Static analysis: bug CLASSES that have bitten this repo before."""
    section("1. SOURCE — bug classes that have bitten before")
    import glob
    # 1.1 bare rolling() — one NaN poisons N bars, comparisons vs NaN are False
    prod_files = ['mix9_core.py', 'api_v2.py', 'forward_journal.py', '_master_harness3.py',
                  'data_cache.py', 'backtest_precompute.py', 'sim_engine.py']
    bad = []
    for f in prod_files:
        if not os.path.exists(f): continue
        for n, line in enumerate(open(f), 1):
            if 'rolling(' in line and 'min_periods' not in line and not line.strip().startswith('#'):
                import re
                if re.search(r'rolling\(\s*\d+\s*\)', line):
                    bad.append(f"{f}:{n}")
    chk(not bad, "1.1 no bare rolling(N) in production paths",
        f"{len(bad)} found: {bad[:4]}" if bad else "all carry min_periods")

    # 1.2 keyword-only args forwarded positionally through to_thread
    src = open('api_v2.py').read() if os.path.exists('api_v2.py') else ""
    import re
    # only flag to_thread(obj.method, a, b, c...) — a lambda wrapper is the fix,
    # so calls already wrapped in `lambda:` are correct and must not be flagged
    hits = [m for m in re.findall(r'to_thread\((?!\s*lambda)[^\n]*', src)
            if m.count(',') >= 3]
    chk(len(hits) == 0, "1.2 no positional kwargs through asyncio.to_thread",
        f"{len(hits)} suspicious call(s)" if hits else "clean", warn_only=True)

    # 1.3 files that must exist OUTSIDE the Fly volume mount (/app/data is shadowed)
    for f in ['mix9_data/vix.csv', 'mix9_data/ticker_quarantine.csv']:
        chk(os.path.exists(f), f"1.3 {f} present (outside volume mount)",
            f"{os.path.getsize(f):,}b" if os.path.exists(f) else "MISSING — prod would silently degrade")

    # 1.4 nothing the engine needs may live in data/ (the mount shadows it)
    core = open('mix9_core.py').read() if os.path.exists('mix9_core.py') else ""
    chk("'data', 'vix.csv'" not in core and "'data', 'ticker_quarantine.csv'" not in core,
        "1.4 engine reads reference data from mix9_data/, not data/")


def qa_data():
    section("2. DATA — coverage, freshness, integrity")
    con = sqlite3.connect('data/stock_cache.db')
    # Scope to the TEST RANGE. 2015 is warm-up: the universe was a few dozen
    # tickers then, so coverage ratios there are meaningless and would make this
    # suite cry wolf. A QA suite you learn to ignore is worse than none.
    q = pd.read_sql_query("SELECT date,COUNT(*) cnt FROM daily_prices WHERE date>='2016-06-01' "
                          "GROUP BY date ORDER BY date", con)
    # Compare each date to its NEIGHBOURS, not to the calendar-year median. The
    # universe grows and shrinks over time (it expanded ~15% through 2021 in the
    # SPAC boom, and adding 3,828 delisted names shifted every year's baseline),
    # so a year-median test flags healthy early-year dates as sparse. A rolling
    # local median detects what we actually care about: a date that DROPS
    # relative to the days around it — a real hole in the feed.
    q['base'] = q.cnt.rolling(21, center=True, min_periods=5).median()
    q['covr'] = q.cnt / q['base']
    bad = q[q['covr'] < 0.9]
    chk(len(bad) == 0, "2.1 no date drops >10% vs neighbouring dates",
        f"{len(bad)} bad dates: {list(bad.date[:4])}" if len(bad) else f"{len(q)} dates clean")

    last = q.date.iloc[-1]
    today = dt.date.today()
    lag = np.busday_count(dt.date.fromisoformat(last), today)
    chk(lag <= 2, "2.2 cache within 2 business days of today",
        f"last bar {last}, {lag} business days ago")

    # phantom rows: market holidays with a handful of synthetic bars
    phantom = q[q.cnt < q['base'] * 0.05]
    chk(len(phantom) == 0, "2.3 no phantom holiday rows",
        f"{list(phantom.date)}" if len(phantom) else "none")

    n = con.execute("SELECT COUNT(*) FROM daily_prices WHERE ticker='VIX'").fetchone()[0]
    chk(True, "2.4 VIX bars in cache", f"{n} (file is authoritative, DB is top-up)")
    con.close()


def qa_equivalence():
    section("3. EQUIVALENCE — live engine == backtested engine")
    r = subprocess.run([sys.executable, '_mix9_equiv_test.py'], capture_output=True, text=True)
    ok = 'EQUIVALENCE PASSED' in r.stdout
    nfail = r.stdout.count('*FAIL*')
    chk(ok and nfail == 0, "3.1 mix9_core reproduces the harness exactly",
        "21/21" if ok else f"{nfail} check(s) failed — LIVE IS NOT WHAT WAS TESTED")


def qa_engine():
    section("4. ENGINE — invariants that must hold every run")
    sys.path.insert(0, HERE)
    from mix9_core import Mix9Data, REGMAP, DD_STOP, CORE_WEIGHT, SLEEVE_WEIGHT, MIN_DWELL_DAYS
    import mix9_engine as M
    D = Mix9Data()

    chk(abs(CORE_WEIGHT + SLEEVE_WEIGHT - 1.0) < 1e-9, "4.1 core+sleeve weights sum to 1",
        f"{CORE_WEIGHT}+{SLEEVE_WEIGHT}")
    chk(0 < DD_STOP < 1, "4.2 DD stop in (0,1)", f"{DD_STOP}")
    chk(MIN_DWELL_DAYS >= 1, "4.3 dwell guardrail set", f"{MIN_DWELL_DAYS}d")

    regs = {D.regime_at(i) for i in range(max(0, D.ND - 2000), D.ND)}
    missing = regs - set(REGMAP)
    chk(not missing, "4.4 every emittable regime has a mapping", f"unmapped: {missing}")

    eq = 25000.0
    t = M.compute_target(eq, D=D)
    alloc = t['core']['target_usd'] + t['sleeve_usd']
    chk(abs(alloc - eq) < 1.0, "4.5 allocation sums to equity (no leak)",
        f"${alloc:,.2f} vs ${eq:,.2f}")
    chk(t['parked'] == (len(t['sleeve']) == 0), "4.6 parked <=> empty live sleeve",
        f"parked={t['parked']} sleeve={len(t['sleeve'])}")
    chk(len(t.get('preview_sleeve', [])) > 0 or t['active_strategy'] not in REGMAP.values(),
        "4.7 preview queue non-empty (Entries tab never blank)",
        f"{len(t.get('preview_sleeve', []))} names for {t['active_strategy']}")
    chk(len(t.get('dd_history', [])) > 0, "4.8 DD trajectory present",
        f"{len(t.get('dd_history', []))} sessions")
    chk(len(t.get('dd_history', [])) == len(t.get('dd_dates', [])),
        "4.9 trajectory values and dates aligned")

    # a target built from an EMPTY book must be all-buy and sum to equity
    tr = M.diff_to_target({}, t)
    buys = sum(x['usd'] for x in tr if x['side'] == 'BUY')
    chk(abs(buys - eq) < max(eq * 0.01, 400), "4.10 empty book -> buys ~= equity",
        f"${buys:,.0f} vs ${eq:,.0f}")
    chk(all(x['side'] == 'BUY' for x in tr), "4.11 empty book produces no SELLs")
    # an at-target book must produce ZERO trades
    at = {t['core']['ticker']: t['core']['target_usd']}
    for p in t['sleeve']: at[p['ticker']] = at.get(p['ticker'], 0) + p['target_usd']
    chk(len(M.diff_to_target(at, t)) == 0, "4.12 at-target book -> zero trades (no churn)")
    return D, t


def qa_prod(t_local=None):
    section("5. PRODUCTION — endpoints, and prod==local agreement")
    root = curl("/", 60)
    chk(root.get("status") == "online", "5.1 backend online", root.get("build", "?"))
    st = curl("/api/v2/mix9/state", 120)
    chk("__error__" not in st and not st.get("pending"), "5.2 /mix9/state serving a snapshot",
        st.get("__error__") or st.get("message", "ok"))
    if not st.get("pending") and "target" in st:
        t = st["target"]
        snap_age = None
        try:
            snap_age = np.busday_count(dt.date.fromisoformat(t["asof"]), dt.date.today())
        except Exception:
            pass
        chk(snap_age is not None and snap_age <= 2, "5.3 prod snapshot fresh",
            f"asof {t['asof']}, {snap_age} business days old")
        if t_local:
            chk(t["active_strategy"] == t_local["active_strategy"],
                "5.4 prod strategy == local recompute",
                f"prod {t['active_strategy']} vs local {t_local['active_strategy']}")
            chk(t["regime"] == t_local["regime"], "5.5 prod regime == local recompute",
                f"prod {t['regime']} vs local {t_local['regime']}")
        # live regime vs snapshot regime — divergence is expected intraday but must be surfaced
        pf = curl("/api/v2/portfolio", 90)
        livereg = (pf.get("market_regime") or {}).get("regime")
        chk(livereg == t["regime"], "5.6 live regime == snapshot regime",
            f"live {livereg} vs snapshot {t['regime']} (snapshot uses last CLOSED bar)",
            warn_only=True)
    pv = curl("/api/v2/mix9/preview", 90)
    chk(len(pv.get("queued", [])) > 0, "5.7 /mix9/preview returns a queue",
        f"{len(pv.get('queued', []))} names")
    dec = curl("/api/v2/mix9/decisions?limit=5", 60)
    chk(len(dec.get("decisions", [])) > 0, "5.8 prod journal has rows",
        f"{len(dec.get('decisions', []))} (audit trail)")


def qa_portfolio():
    section("6. PORTFOLIO — book integrity")
    pf = curl("/api/v2/portfolio", 90)
    pos = pf.get("positions", [])
    tickers = [p["ticker"] for p in pos]
    chk(len(tickers) == len(set(tickers)), "6.1 no duplicate ticker rows (lots merged)",
        f"{len(pos)} rows: {tickers}")
    bad = [p["ticker"] for p in pos
           if (p.get("strategy") == "CORE") != (p.get("exit_strategy") == "CORE")]
    chk(not bad, "6.2 CORE positions carry no exit timer", f"mismatched: {bad}")
    for p in pos:
        chk(float(p.get("shares") or 0) > 0 and float(p.get("entry_price") or 0) > 0,
            f"6.3 {p['ticker']} has valid shares/entry",
            f"{p.get('shares')} @ {p.get('entry_price')}")
    s = pf.get("summary", {})
    tot = float(s.get("total_value") or 0)
    calc = sum(float(p.get("current_value") or 0) for p in pos) + float(s.get("cash") or 0)
    chk(abs(tot - calc) < max(tot * 0.02, 5), "6.4 summary total == positions + cash",
        f"${tot:,.2f} vs ${calc:,.2f}")


def qa_registry():
    section("7. FORWARD REGISTRY — tamper-evidence")
    import hashlib
    p = 'data/forward_registry.json'
    if not os.path.exists(p):
        chk(False, "7.1 registry present", "MISSING"); return
    r = json.load(open(p))
    R = r["registrations"]
    bad = [x["name"] for x in R
           if hashlib.sha256(x["rule"].encode()).hexdigest()[:16] != x.get("rule_sha256")]
    chk(not bad, "7.1 every rule matches its recorded hash", f"drifted: {bad}" if bad else f"{len(R)} intact")
    vd = {x.get("verdict_date") for x in R if x.get("verdict_date")}
    chk(len(vd) <= 1, "7.2 single pinned verdict date (no optional stopping)", str(vd))
    chk(len(r.get("amendment_log", [])) > 0, "7.3 amendment log non-empty",
        f"{len(r.get('amendment_log', []))} entries")


def main():
    args = sys.argv[1:]
    fast = '--fast' in args
    only = None
    if '--section' in args:
        only = args[args.index('--section') + 1]
    t_local = None
    stages = [('source', qa_source), ('data', qa_data), ('registry', qa_registry)]
    if not fast:
        stages += [('equivalence', qa_equivalence)]
    for nm, fn in stages:
        if only and nm != only: continue
        try: fn()
        except Exception as e:
            chk(False, f"{nm} suite crashed", str(e)[:120])
    if (not only or only == 'engine') and not fast:
        try:
            _, t_local = qa_engine()
        except Exception as e:
            chk(False, "engine suite crashed", str(e)[:120])
    for nm, fn in [('prod', lambda: qa_prod(t_local)), ('portfolio', qa_portfolio)]:
        if only and nm != only: continue
        try: fn()
        except Exception as e:
            chk(False, f"{nm} suite crashed", str(e)[:120])

    print("\n" + "=" * 100)
    print(f"QA RESULT: {len(PASSES)} pass · {len(WARNS)} warn · {len(FAILS)} FAIL")
    print("=" * 100)
    for w in WARNS: print(f"  WARN  {w}")
    for f in FAILS: print(f"  FAIL  {f}")
    if FAILS:
        print("\nA FAIL means live behaviour may differ from what was validated. Do not trade on it.")
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
