"""MIX9 CORE — the selectors, regime map and DD-stop, shared by backtest and live.

THE POINT OF THIS MODULE: the live engine must run the *same code* that was
backtested. Re-implementing the selectors for production is how a validated
strategy silently becomes a different one. `_mix9_equiv_test.py` proves this
module returns byte-identical picks to `_master_harness3.py` on historical dates.

WHAT MIX9 IS (frozen rule, forward registry roster 9):
  Daily regime read (prod _check_market_regime chain incl. VIX tiers). Map
  regime -> one active strategy, using a map FROZEN from IS-only data
  (2016-06..2022-12) mean daily return per regime. Allocation: 70% active
  strategy + 30% core, rebalanced monthly. GUARDRAIL: if the active strategy's
  own equity is >15% below its running peak, its 70% sleeve sits in the core
  until that strategy recovers. No position-level stops.

DEPLOY VARIANT: core = XLK (chosen 2026-07-31), which MATCHES the registered
roster-9 rule. XLK core was picked over SPY for compounding: it wins 7/10
calendar years and turns $19,511 into $982K vs $737K over the decade. The
accepted costs are a worse 2022 (-27.4% vs -17.7%), a deeper OOS drawdown
(-25.7% vs -18.8%) and a lower luck-adjusted score (DSR@40 0.826 vs 0.869).
The ballast being 100% tech is a known, deliberate concentration.

DD-STOP STATE IS RECOMPUTED FROM INCEPTION ON EVERY RUN, never persisted.
Persisting it would let live state drift away from what the backtest produces;
recomputation is deterministic and costs ~1-2 minutes.
"""
from __future__ import annotations
import sqlite3, os, csv
from typing import Optional
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'data', 'stock_cache.db')

# ── frozen constants (must match the registry rule) ──────────────────────────
INCEPTION = '2016-06-01'
DD_STOP = 0.15            # strategy-level drawdown that parks the sleeve in core
CORE_WEIGHT = 0.30
SLEEVE_WEIGHT = 0.70
TOP_N = 10
FEE, SLIP, EFEE = 0.003, 0.0005, 0.0005

# regime -> active strategy. FROZEN from IS-only (2016-06..2022-12) mean daily
# return per regime. Do NOT re-fit this on newer data: re-deriving it after
# seeing 2023+ is exactly the lookahead the walk-forward was built to exclude.
REGMAP = {
    'HEALTHY':     'MOM-brk90',
    'PULLBACK':    'TREND10',
    'SHARP_DROP':  'TREND10',
    'FEAR':        'TREND10',
    'DANGER':      'RELSTR10',
    'CORRECTION':  'RELSTR10',
    'DIP_BUY':     'LeadSector',
    'WEAK':        'LeadSector',
    'BEAR_BOUNCE': 'cap2+guard',
    'CRISIS':      'LC 12-1',
    'BELOW200':    'TREND10',   # fallback; never emitted in the IS fit
}
STRATEGIES = ['TREND10', 'RELSTR10', 'cap2+guard', 'LeadSector', 'LC 12-1',
              'MR-dips90', 'MOM-brk90']
SPDR_LIST = ['XLK', 'XLV', 'XLF', 'XLE', 'XLI', 'XLP', 'XLY', 'XLU', 'XLB', 'XLRE']


class Mix9Data:
    """Price matrix + indicators. Mirrors _master_harness3.py exactly.

    Every rolling() carries min_periods: a bare rolling(N) lets one NaN bar
    poison the next N outputs, and because comparisons against NaN are False the
    signal gates silently DROP tickers rather than erroring.
    """

    def __init__(self, db_path: str = DB, vix_csv: Optional[str] = None):
        con = sqlite3.connect(db_path)
        quar = {r[0] for r in con.execute("SELECT ticker FROM ticker_quarantine")}
        df = pd.read_sql_query(
            "SELECT ticker,date,open,high,low,close,volume FROM daily_prices", con)
        con.close()
        df = df[~df.ticker.isin(quar) & ~df.ticker.str.endswith('USD') & (df.ticker != 'VIX')]
        C = df.pivot(index='date', columns='ticker', values='close').astype('float32')
        O = df.pivot(index='date', columns='ticker', values='open').astype('float32')
        H = df.pivot(index='date', columns='ticker', values='high').astype('float32')
        L = df.pivot(index='date', columns='ticker', values='low').astype('float32')
        V = df.pivot(index='date', columns='ticker', values='volume').astype('float32')
        del df
        self.C, self.O = C, O
        self.cols = list(C.columns)
        self.colix = {t: i for i, t in enumerate(self.cols)}
        self.dates = C.index.tolist()
        self.ND = len(self.dates)
        self.Cv, self.Ov = C.values, O.values
        self.Cf = C.ffill().values
        self.last_valid = C.apply(lambda s: s.last_valid_index()).map(
            lambda d: self.dates.index(d) if d is not None else -1).values

        sma50 = C.rolling(50, min_periods=45).mean()
        sma150 = C.rolling(150, min_periods=135).mean()
        sma200 = C.rolling(200, min_periods=180).mean()
        d1 = C.diff(); g = d1.clip(lower=0); l = (-d1).clip(lower=0)

        def rsi(p):
            a = g.ewm(alpha=1 / p, adjust=False, min_periods=p * 3).mean()
            b = l.ewm(alpha=1 / p, adjust=False, min_periods=p * 3).mean()
            return 100 - 100 / (1 + a / b.replace(0, np.nan))

        rsi2, rsi14 = rsi(2), rsi(14)
        pc = C.shift(1)
        TR = pd.concat([H - L, (H - pc).abs(), (L - pc).abs()]).groupby(level=0).max().reindex(C.index)
        atrp = TR.rolling(14, min_periods=12).mean() / C * 100
        vr = V / V.rolling(20, min_periods=18).mean()
        r20 = C.pct_change(20, fill_method=None) * 100
        r5 = C.pct_change(5, fill_method=None) * 100
        r126 = C.pct_change(126, fill_method=None) * 100
        d1p = C.pct_change(1, fill_method=None) * 100
        hi = C.rolling(252, min_periods=200).max()
        lo = C.rolling(252, min_periods=200).min()
        buf = (C / sma50 - 1) * 100

        self.mrg = ((C > sma50) & (atrp >= 3) & (atrp < 15) & (buf >= 5) & (vr >= 1.0)
                    & (rsi2 < 10) & (rsi14 < 60) & (C >= 10)).values
        a_ = atrp.values; r2v = rsi2.values; r20v = r20.values
        vrv = vr.values; bfv = buf.values; pv = C.values
        ap = np.select([a_ >= 15, a_ >= 10, a_ >= 8, a_ >= 6, a_ >= 5, a_ >= 4, a_ >= 3],
                       [-5, 35, 40, 35, 30, 20, 15], default=0)
        bp = np.where(a_ >= 15, 0, np.select([(r20v > 10) & (a_ >= 5), (r20v > 5) & (a_ >= 4)],
                                             [12, 8], default=0))
        vp = np.select([vrv < 0.5, vrv < 1.0, vrv < 1.5], [8, 0, 10], default=5)
        fp = np.select([bfv >= 5, bfv >= 0], [2, 1], default=0)
        pp = np.select([(pv >= 10) & (pv <= 25), pv <= 50, pv <= 100, pv <= 200, pv <= 500],
                       [10, 8, 5, 2, -3], default=-5)
        rp = np.select([r2v < 5, r2v < 10], [3, 2], default=0)
        self.MRS = np.where(self.mrg, np.clip(ap + rp + fp + bp + 4 + vp + pp, 0, 100), -1)
        self.momg = ((C >= 10) & (C <= 200) & (C > sma50) & (C > sma150) & (C > sma200)
                     & (sma50 > sma150) & (sma150 > sma200) & (C / hi - 1 > -0.05)
                     & (C / lo - 1 > 0.30) & (r20 > 5) & (d1p < 10) & (r5 <= 15)).values
        self.MOMS = np.where(self.momg, r126.values, -1e9)

        self.dvol = (C * V).rolling(63, min_periods=55).mean().values
        self._r252 = (C / C.shift(252) - 1).values
        self._r63 = (C / C.shift(63) - 1).values
        self._r126m = (C / C.shift(126) - 1).values
        self._s200 = sma200.values
        self._s50h = sma50.values
        self._hi252 = hi.values

        self.month_end = {i for i in range(self.ND - 1)
                          if self.dates[i][:7] != self.dates[i + 1][:7]}
        self._spdr = [s for s in SPDR_LIST if s in self.colix]
        self._spi = {s: self.colix[s] for s in self._spdr}
        self._rets = C.pct_change(fill_method=None)
        self._seccache = {}

        # ── regime inputs: mirror prod _check_market_regime (dropna + min(252,len)) ──
        # VIX MUST come from a source that exists in production. /tmp/vix.csv is a
        # local research artifact; on Fly it does not exist, vixmap would be empty,
        # every VIX read would be 0.0 and the CRISIS (>40) and FEAR (>30) branches
        # would NEVER fire — silently changing the regime series, the component
        # curves and therefore the DD-stop. Ship the history as tracked data
        # (data/vix.csv) so prod and the backtest read identical inputs, and top it
        # up from the cache DB for any recent bars the file predates.
        vixmap = {}
        for path in ([vix_csv] if vix_csv else
                     [os.path.join(HERE, 'data', 'vix.csv'), '/tmp/vix.csv']):
            try:
                for row in csv.reader(open(path)):
                    try: vixmap[row[0]] = float(row[1])
                    except Exception: pass
                if vixmap: break
            except FileNotFoundError:
                continue
        try:
            con2 = sqlite3.connect(db_path)
            for d_, v_ in con2.execute(
                    "SELECT date, close FROM daily_prices WHERE ticker='VIX'"):
                if v_ and float(v_) > 0 and d_ not in vixmap:
                    vixmap[d_] = float(v_)
            con2.close()
        except Exception:
            pass
        vix = np.array([vixmap.get(d, 0.0) for d in self.dates])
        for i in range(1, len(vix)):
            if vix[i] <= 0: vix[i] = vix[i - 1]     # carry forward; 0 would disable CRISIS/FEAR
        self.vix = vix
        spy = C['SPY'].ffill()
        self._dd = ((spy / spy.rolling(252, min_periods=20).max()) - 1).values * 100
        self._g200 = ((spy / spy.rolling(200, min_periods=20).mean()) - 1).values * 100
        self._g50 = ((spy / spy.rolling(50, min_periods=10).mean()) - 1).values * 100
        self._sr5 = (spy.pct_change(5, fill_method=None) * 100).values

        self.mr_sig, self.mom_sig = {}, {}
        gr, gc = np.where(self.mrg)
        for i, c in zip(gr, gc): self.mr_sig.setdefault(i, []).append(c)
        gr, gc = np.where(self.momg)
        for i, c in zip(gr, gc): self.mom_sig.setdefault(i, []).append(c)

    # ── regime ──────────────────────────────────────────────────────────────
    def regime_at(self, i: int) -> str:
        """Prod-exact branch chain. ORDER MATTERS (PULLBACK before DIP_BUY)."""
        d, gg, g5x, rr, v = self._dd[i], self._g200[i], self._g50[i], self._sr5[i], self.vix[i]
        if np.isnan(d) or np.isnan(gg): return 'HEALTHY'
        if -15 <= d <= -7: return 'DANGER'
        if v > 40: return 'CRISIS'
        if -2 < gg < 0: return 'WEAK'
        if -20 <= d < -15: return 'CORRECTION'
        if d < -20: return 'BEAR_BOUNCE'
        if gg < -2: return 'BELOW200'
        if g5x < 0: return 'PULLBACK'
        if d <= -3: return 'DIP_BUY'
        if rr < -2: return 'SHARP_DROP'
        if v > 30: return 'FEAR'
        return 'HEALTHY'

    # ── universe + sectors ──────────────────────────────────────────────────
    def liquid(self, j: int, n: int = 300):
        ok = (np.isfinite(self.Cv[j]) & (self.Cv[j] >= 15)
              & np.isfinite(self.dvol[j]) & (self.dvol[j] > 3e6))
        e = np.where(ok)[0]
        return e[np.argsort(-self.dvol[j, e])][:n] if len(e) else np.array([], int)

    def sectors_at(self, j: int):
        """Point-in-time: trailing 504d max-correlation to the SPDRs, cached per quarter."""
        key = j // 63
        if key in self._seccache: return self._seccache[key]
        a = max(0, j - 504)
        w = self._rets.iloc[a:j + 1]
        etf = w[self._spdr]
        sub = w.dropna(axis=1, thresh=int((j - a) * 0.6))
        out = {}
        for tk in sub.columns:
            if tk in self._spdr:
                out[self.colix[tk]] = tk; continue
            s = sub[tk]; best = None; bv = -9.0
            for e in self._spdr:
                cc = s.corr(etf[e])
                if cc == cc and cc > bv: bv = cc; best = e
            if best and bv > 0.25: out[self.colix[tk]] = best
        self._seccache[key] = out
        return out

    # ── the five stock selectors (identical to _master_harness3.py) ─────────
    def sel_relstr(self, j: int, n: int, cap: int = 99, bench: str = 'XLK'):
        if j < 252: return []
        bi = self.colix[bench]
        u = self.liquid(j)
        if not len(u): return []
        b252 = self.Cf[j, bi] / self.Cf[j - 252, bi] - 1
        b63 = self.Cf[j, bi] / self.Cf[j - 63, bi] - 1
        cand = [c for c in u
                if np.isfinite(self._r252[j, c]) and self._r252[j, c] > b252
                and np.isfinite(self._r63[j, c]) and self._r63[j, c] > b63]
        cand.sort(key=lambda c: -self._r252[j, c])
        if cap >= 99: return cand[:n]
        sec = self.sectors_at(j); out = []; cnt = {}
        for c in cand:
            s = sec.get(c, '?')
            if cnt.get(s, 0) >= cap: continue
            out.append(c); cnt[s] = cnt.get(s, 0) + 1
            if len(out) == n: break
        return out

    def sel_trend(self, j: int, n: int):
        u = self.liquid(j)
        ok = [c for c in u
              if np.isfinite(self._s200[j, c]) and self.Cv[j, c] > self._s200[j, c]
              and np.isfinite(self._s50h[j, c]) and self.Cv[j, c] > self._s50h[j, c]
              and np.isfinite(self._hi252[j, c]) and self.Cv[j, c] / self._hi252[j, c] > 0.90
              and np.isfinite(self._r126m[j, c])]
        return sorted(ok, key=lambda c: -self._r126m[j, c])[:n]

    def sel_leadsector(self, j: int, n: int):
        u = self.liquid(j)
        if not len(u): return []
        sm = {s: (self.Cf[j, self._spi[s]] / self.Cf[j - 126, self._spi[s]] - 1) if j >= 126 else -9
              for s in self._spdr}
        lead = [s for s, _ in sorted(sm.items(), key=lambda kv: -kv[1])[:5]]
        sec = self.sectors_at(j); per = max(1, n // len(lead)); out = []
        for s in lead:
            mem = [c for c in u if sec.get(c) == s and np.isfinite(self._r126m[j, c])]
            mem.sort(key=lambda c: -self._r126m[j, c])
            out += mem[:per]
        return out[:n]

    def sel_lc121(self, j: int, n: int):
        if j < 252: return []
        m = self.Cv[j - 21] / self.Cv[j - 252] - 1
        ok = (np.isfinite(m) & np.isfinite(self.Cv[j]) & (self.Cv[j] >= 20)
              & np.isfinite(self.dvol[j]) & (m <= 2.0))
        e = np.where(ok)[0]
        if not len(e): return []
        td = e[np.argsort(-self.dvol[j, e])][:200]
        return list(td[np.argsort(-m[td])][:n])

    def selector(self, name: str):
        return {
            'TREND10':    lambda j, n: self.sel_trend(j, n),
            'RELSTR10':   lambda j, n: self.sel_relstr(j, n, 99, 'XLK'),
            'cap2+guard': lambda j, n: self.sel_relstr(j, n, 2, 'SPY'),
            'LeadSector': lambda j, n: self.sel_leadsector(j, n),
            'LC 12-1':    lambda j, n: self.sel_lc121(j, n),
        }.get(name)

    def index_of_date(self, d: str) -> int:
        import bisect
        return min(bisect.bisect_right(self.dates, d) - 1, self.ND - 1)
