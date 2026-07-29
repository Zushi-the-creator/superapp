---
name: forward-test
description: Pre-register, run, and evaluate forward tests of strategies - the only evidence that can promote a backtested strategy to live capital. Use when registering a new strategy roster, checking forward results, or deciding promotion/demotion.
allowed-tools: Bash(python3 *) Bash(cd *) Bash(curl *) Read Write
argument-hint: [register <name> | status | evaluate <name>]
---

# Forward Test — pre-registration protocol

**Why this skill exists:** backtests here can never be fully clean (survivor
universe + selection contamination). The ONLY evidence that promotes a strategy
to real capital is a pre-registered forward test. Live case study: the 12-1
rotation looked +17.8pp OOS in backtest, then lost −13.7pp to QQQ in its first
19 live-tracked days (July 2026 momentum crash). Backtests propose; forward
tests decide.

## Infrastructure
- **`backend/data/forward_registry.json`** — the pre-registration ledger (rules
  frozen at registration; append-only).
- **Signal tracker V2** (`signal_tracker_update.py`, prod loop) — nightly top-20
  snapshot, forward returns at 7/14/21/42/60d, QQQ benchmark columns, regime.
- **Paper simulator** (`sim_engine_loop`, prod) — autonomous $100k paper book,
  hourly during RTH + close snapshots: fills, slippage, position accounting.
- FREE data check: every evaluation states its data-freshness (cache date).

## Pre-registration rules (non-negotiable)
1. **Freeze before you watch.** A registration entry must contain: full entry
   rule, ranking, exit rule, sizing, regime gates, benchmark, and the DATE — all
   fixed BEFORE the first tracked bar. Editing rules mid-test = new registration,
   old one keeps running to its verdict (no silent replacement).
2. **State the promotion criterion at registration**, e.g.: "beats XLK on
   42-day rolling return in ≥55% of windows over ≥60 trading days AND survives
   its declared MDD tolerance." No post-hoc metric shopping.
3. **Minimum sample before ANY verdict:** 60 trading days AND ≥20 closed
   positions (whichever is later). Early peeks are logged as peeks, not verdicts.
4. **Benchmarks always tracked in parallel:** XLK (account core), QQQ, SPY.
5. **Every registered strategy gets a kill criterion too** (e.g. "−20% vs
   benchmark at any point = demote to archive") — decided up front.
6. **No survivor editing.** Failed registrations stay in the ledger with their
   outcome. The ledger IS the track record.

## Currently registered rosters (2026-07-29 cohort)
| Name | Rule frozen | Benchmark | Promotion bar |
|---|---|---|---|
| ROT10 | 12-1 top-10 monthly (dv200, cap200%, px≥20), hold-through-DANGER | XLK | >benchmark 55% of 42d windows, 6mo |
| MOMBRK5 | Minervini+r126 top-5, Fixed90, uptrend regimes | XLK | same |
| MRDIP | MR composite top-5, Fixed42, DIP/SHARP_DROP/BEAR_BOUNCE only | XLK | positive vs benchmark in its deployment windows |
| V4BLEND | 50% core + 50% ROT10 + MRDIP overlay, DANGER freeze | XLK | beats core with ≤1.3x its MDD |
| BASELINE | XLK / QQQ / SPY buy-hold | — | reference |

## Evaluation standard (when sample minimums are met)
- Rolling 42d returns vs benchmark: win fraction, mean edge, worst window.
- Deflated check: `python3 backend/_dsr.py --returns-csv <curve> --n <cohort size>`
  — N = number of strategies registered in the cohort (selection among
  registrations is still selection).
- Regime attribution: performance split by regime at entry (a strategy may be
  promoted for specific regimes only — that becomes its deployment gate).
- Costs: paper sim fills include fees; tracker returns are gross — say which.

## Verdict vocabulary (use exactly)
- **PROMOTED** — met its pre-registered criterion; eligible for real sizing
  (start ≤20% of book).
- **CONTINUE** — sample below minimums.
- **DEMOTED** — hit kill criterion or failed at full sample; archived, never
  silently re-registered with tweaked params (that's a NEW entry, tagged v2).

## Ops
- **Nightly journal (the authoritative record): `cd backend && python3 forward_journal.py`**
  — appends each registered roster's picks at the latest completed bar
  (idempotent per day). A roster without journal rows has NO evidence.
- Status: read `backend/data/forward_registry.json` + latest tracker report:
  `python3 backend/signal_tracker_update.py --report`
- Paper book: `curl -s https://superapp-ke5bhg.fly.dev/api/v2/sim/state` (also
  `/sim/decisions`, `/sim/history`), or `sim_engine_loop` output in fly logs.
- Register new: append a frozen-rule entry to the registry JSON with date,
  promotion bar, and kill bar. Never edit existing entries.
