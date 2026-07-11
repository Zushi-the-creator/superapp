# RESEARCH_QUEUE.md — hypothesis backlog (operator maintains, CEO can inject with `RESEARCH <idea>`)

Rules for every study: point-in-time (no lookahead), next-day open entry, 0.30% fee,
PROD-gated signals, IS/OOS split, then a capacity-constrained portfolio sim (N=4-7
slots) before declaring a winner. Per-trade averages alone are NOT a result.
Negative results go to TESTED_REJECTED.md with the numbers — they are deliverables.

## Queue (top = next)
1. **Skipped-ticket shadow book** — track forward returns of every ticket the CEO
   skipped vs executed. Quantifies the cost/benefit of discretion. (Cheap: bookkeeping
   + monthly report, no backtest harness needed.)
2. **Entry-day timing** — does entering at next-day open beat 10:00/close entry for
   MR signals? (We assume open; verify it's not leaving edge on the table.)
3. **Composite-score weight re-fit, walk-forward** — current weights are hand-set
   (ATR 40 / analyst 15 / BOTH 12 / sentiment 10 / volume 10 / price 10 / minor 5).
   Fit on pre-2023, test 2023+. Only ship if OOS top-3 forward return beats current
   composite's +4.43%.
4. **Slot count N sweep** — portfolio sim at N=4..10 with current gates. We trade
   top-N concentrated; the entry-validation memory says top-10 beat top-5. Find the
   capacity-adjusted sweet spot with today's account size (~$21K).
5. **Cash drag policy** — when regime pauses entries, does parking in SPY/BIL beat
   cash? (Point-in-time, regime-gated periods only.)
6. **Earnings-drift re-entry** — after a holding is exited for earnings <7d, is there
   a validated re-entry edge post-print? (Currently we just walk away.)
7. **Academic sweep (recurring)** — monthly scan of SSRN/arXiv q-fin for new
   short-horizon mean-reversion / momentum papers on US equities. Summarize only
   ideas that are testable with our data; queue the testable ones here.

## In flight
(none)

## Done → see TESTED_REJECTED.md / CLAUDE.md validation history
- Zone-based sizing/exits (IC≈0), all early-exit policies, trailing stops for MR,
  BWR as primary sort, dual-bucket defensive RSI<10, HonestDyn exits — all REJECTED
  with data. Do not re-test without new information.
