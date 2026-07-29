#!/usr/bin/env python3
"""Deflated Sharpe Ratio + overfitting guards (Bailey & Lopez de Prado 2014).

Answers: "given how many strategy variants we tried, is this Sharpe real?"

  PSR  — Probabilistic Sharpe Ratio: P(true SR > SR_benchmark) given skew/kurtosis.
  E[maxSR] — expected best Sharpe among N unskilled trials (the luck bar).
  DSR  — PSR evaluated against E[maxSR]: >0.95 = survives multiple testing.

Usage:
  python3 _dsr.py --sr 1.10 --t 900 --n 38                 # annual SR, daily obs count, trials
  python3 _dsr.py --returns-csv curve.csv --n 38           # daily equity curve, one col
References: Bailey & Lopez de Prado (2014) "The Deflated Sharpe Ratio";
Harvey-Liu-Zhu (2016) t>3 for new factors; McLean-Pontiff 58% decay haircut.
"""
import argparse, math, sys
from statistics import NormalDist

ND = NormalDist()
EULER = 0.5772156649015329

def psr(sr_hat, sr_star, T, skew=0.0, kurt=3.0):
    """P(true SR > sr_star). sr_hat/sr_star in PER-PERIOD units matching T obs."""
    denom = math.sqrt(max(1e-12, 1 - skew*sr_hat + (kurt-1)/4*sr_hat**2))
    z = (sr_hat - sr_star) * math.sqrt(T - 1) / denom
    return ND.cdf(z)

def expected_max_sr(n_trials, var_sr=None, T=None):
    """E[max SR] across n unskilled trials (per-period units).
    var_sr defaults to 1/T (iid-normal SR estimator variance)."""
    if var_sr is None:
        var_sr = 1.0/max(T, 2)
    n = max(n_trials, 2)
    return math.sqrt(var_sr) * ((1-EULER)*ND.inv_cdf(1-1.0/n) + EULER*ND.inv_cdf(1-1.0/(n*math.e)))

def dsr(sr_hat_annual, T, n_trials, skew=0.0, kurt=3.0, periods=252):
    sr_p = sr_hat_annual / math.sqrt(periods)          # per-period SR
    if n_trials <= 1:
        # single pre-registered strategy: no selection -> plain PSR vs SR*=0
        return psr(sr_p, 0.0, T, skew, kurt), 0.0
    sr_star = expected_max_sr(n_trials, T=T)
    return psr(sr_p, sr_star, T, skew, kurt), sr_star*math.sqrt(periods)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--sr', type=float, help='annualized Sharpe of the candidate')
    p.add_argument('--t', type=int, help='number of daily observations')
    p.add_argument('--n', type=int, required=True, help='number of strategy variants tried (be honest)')
    p.add_argument('--skew', type=float, default=0.0)
    p.add_argument('--kurt', type=float, default=3.0, help='RAW kurtosis (normal=3). pandas .kurt() is EXCESS: add 3.')
    p.add_argument('--returns-csv', help='csv of daily equity values (one column) — computes sr/t/skew/kurt')
    a = p.parse_args()
    if a.returns_csv:
        vals = []
        for x in open(a.returns_csv):
            try: vals.append(float(x.strip().split(',')[-1]))
            except ValueError: pass  # skip headers/blank
        rets = [(vals[i]/vals[i-1]-1) for i in range(1, len(vals))]
        T = len(rets); mu = sum(rets)/T
        var = sum((r-mu)**2 for r in rets)/T; sd = math.sqrt(var)
        a.skew = sum((r-mu)**3 for r in rets)/T/sd**3
        a.kurt = sum((r-mu)**4 for r in rets)/T/sd**4
        a.sr = mu/sd*math.sqrt(252); a.t = T
    if a.sr is None or a.t is None:
        sys.exit('need --sr and --t (or --returns-csv)')
    mode = 'PSR (no selection, N=1)' if a.n <= 1 else f'DSR (selection among N={a.n})' 
    d, luck_bar = dsr(a.sr, a.t, a.n, a.skew, a.kurt)
    print(f"mode: {mode}   [var_sr=1/T iid-null assumption]")
    print(f"candidate SR (annual):     {a.sr:.2f}   over T={a.t} daily obs, N={a.n} trials")
    print(f"luck bar E[maxSR] annual:  {luck_bar:.2f}   (best Sharpe pure chance produces at N={a.n})")
    print(f"Deflated Sharpe (DSR):     {d:.3f}   {'PASS (>0.95: skill likely real)' if d>0.95 else 'FAIL — indistinguishable from selection luck'}")
    print(f"McLean-Pontiff haircut:    expect ~42% of the backtest edge to survive live")
