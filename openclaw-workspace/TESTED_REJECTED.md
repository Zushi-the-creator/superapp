# TESTED_REJECTED.md — validated negative results. Do NOT re-test without new information.

| Idea | Result | Source |
|---|---|---|
| Per-stock RSI-zone expected returns (sizing/exits) | IC ≈ 0.00 on 5,481 point-in-time samples — pure noise; everything converges to base rate +2-4%/60d | `_zonecalib_bt.py`, 2026-07-04 |
| MR trailing stop 8% | Median affected trade -3.0%; OOS WR 51%→49% | `_exit_policy_bt.py`, 32,607 trades |
| Stop-loss -8% | Exit cohorts 22-39% WR — hurts | hold-vs-exit mega-validation |
| Exit on SMA50 break | -2.7pp/trade; 90% of MR entries break SMA50 mid-hold (that's the dip) | mega-validation 2026-06/07 |
| Model-EXIT signal (both WR zones <65) | -2.5pp/trade flagged cohort (OOS -1.9pp) | mega-validation |
| Composite rotation (gap>15) / rotate-losers | -13 to -24 CAGR pts vs HOLD | mega-validation |
| Pace-rotation (cut behind-pace day D) | No robust winner; the one good combo is an isolated overfit spike | mega-validation |
| Buffered WR as PRIMARY sort | Composite top-3 fwd +4.43% vs BWR +2.79% (OOS +5.77% vs +3.56%) | `_rank_backtest.py`, 2026-06-18 |
| Analyst-target veto (price>target) | -0.40% edge — rejected higher-return signals | 2026-04-24 |
| Sentiment veto <-0.3 (MR) | -0.43% edge | 2026-04-24 |
| Dual-bucket defensive RSI<10 | Bucket A beat B and C in every regime incl. CRISIS | V3.3 validation |
| HonestDyn regime-adaptive exits | Beaten by Fixed60d once capacity constraints applied | 13-window walk-forward, 2026-06-17 |
| Fixed30d exit (MR) | OOS-2024 +6.3% CAGR / MDD -35% vs Fixed60d +23.2% / -11.6% | 2026-06-17 |
| Demoting ATR 8-15% in composite | Lowers realized ROI — edge is tail-driven, tail lives in high ATR | `_composite_ab_test.py` |
