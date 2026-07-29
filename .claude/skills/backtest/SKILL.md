---
name: backtest
description: Run standards-compliant backtests through the canonical harness - strategy comparison, single-stock, or cache refresh. Use when validating ANY strategy claim before it can be proposed, deployed, or ranked.
allowed-tools: Bash(python3 *) Bash(cd *) Bash(curl *) Read Write
argument-hint: [strategy-question | TICKER | refresh]
---

# Backtest — canonical harness + market-standard checklist

**Engine: `backend/_master_harness3.py` is the ONLY sanctioned harness** for strategy
comparisons. Never write a fresh ad-hoc backtest for a strategy claim — extend the
harness (add a row to `STRATS`) so every strategy faces identical rules. Ad-hoc
scripts are exploration only; their numbers may not be quoted as evidence.

## Live rules (validate against THESE or numbers are meaningless)
- Exits: **Fixed42d** (MR/BOTH, V3.6 2026-07-22) / **Fixed90d** (Momentum). NO stops,
  NO trailing, NO targets (32,607-trade study: stops hurt MR).
- Entries tab sorts composite_score; MR/BOTH ranked above MOMENTUM (V3.6).
- Benchmark = the core the account actually holds (**XLK** since 2026-07; QQQ for
  research comparability — 0.97-correlated; XLK CAGR 23.7% vs QQQ 20.4% 2016-26).

## The 10-point standards checklist (every result must state all 10)
1. **Point-in-time signals** — indicators at day d use only bars ≤ d. Prove with a
   delay test: lag the signal 1-2 days; a real edge survives.
2. **Next-day-open execution** — signal at close t, trade at open t+1. Monthly
   rotations: rank at month-end close, execute next open.
3. **Costs** — stocks 0.30% fee + 0.05% slippage/side; ETF legs 0.05%+0.05%;
   charge the FUNDING leg too (sell core → buy stock = both legs pay).
4. **Slot-limited portfolio sim** (N=5 default) — no overlapping same-ticker
   re-entry. Per-trade stats without slot limits ≠ strategy returns.
5. **IS/OOS split** — IS 2016-06→2022-12, OOS 2023-01→now. Anything designed while
   looking at the full period is contaminated: label "in-sample-searched"; it
   cannot be promoted without /forward-test evidence.
6. **Survivorship tier label — mandatory on every number**: Tier A = index/ETF
   data (clean). Tier B = stock-picking on today's universe (inflated). Tier-B
   mitigations required: exits at last REAL bar (never ffill), −30% delist haircut
   when a series ends >10d before cache end.
7. **Regime replication** — prod-exact `_check_market_regime` chain INCLUDING VIX
   tiers (FRED: `curl -sL "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS" -o /tmp/vix.csv`).
   Chain ORDER matters (PULLBACK is tested before DIP_BUY).
8. **Sanity/null check** — run with the strategy disabled (null config — e.g. satellite weight 0 in the sim being used); must
   reproduce the benchmark within ~1%. This exact check caught two catastrophic
   sim bugs (cash-vaporizing rebalance; NaN-bar phantom drawdowns, 2026-07).
9. **Multiple-testing correction** — count EVERY variant tried, honestly, then
   `python3 backend/_dsr.py --sr <annualSR> --t <dailyObs> --n <variants>`.
   DSR < 0.95 ⇒ the edge is selection luck; report it as such (Bailey-López de
   Prado deflated Sharpe; Harvey-Liu-Zhu: t>3 for anything novel).
10. **Decay haircut** — discovered edges deliver ~42% of backtest live
    (McLean-Pontiff). Report expected-live next to backtest numbers; a
    live-audited analog (e.g. SPMO for momentum rotation) is the floor.

## Robustness minimums before proposing any strategy
- Parameter neighborhood ±1 step on every knob — no isolated spikes.
- Start-offset stability (0-4 days) + year-by-year table vs benchmark.
- Hold/exit changes: rolling walk-forward windows (pattern: `_wf_exit_bt.py`,
  17 windows, 6mo OOS steps).
- Always report MDD + worst window next to CAGR.

## Known structural limits (state in every report)
- No point-in-time universe (CRSP-style) — Tier-B numbers are ceilings.
- Taxes (25% CGT) unmodeled — turnover-heavy results overstate after-tax.
- Zone-based expected returns are NOISE (IC≈0) — never rank on them.
- Per-trade winner ≠ portfolio winner — capacity sim decides.

## Cost convention
This skill/harness convention (0.30%+0.05% slip per side, funding leg charged)
SUPERSEDES older docs that say "0.30% per trade" — numbers across conventions
are not comparable; always state which convention a quoted number used.

## Quick ops
- Refresh cache: `cd backend && python3 backtest_precompute.py` (hold-length
  changes need force=True — cache has no hold-days key).
- Single stock vs live rules: `curl -s "https://superapp-ke5bhg.fly.dev/api/v2/analyze/$ARGUMENTS"`
- Full comparison: add a `STRATS` row in `_master_harness3.py`, run, present the
  ranked table: IS CAGR | OOS CAGR | OOS MDD | vs benchmark | tier | DSR | verdict.
