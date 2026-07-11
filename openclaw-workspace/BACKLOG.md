# BACKLOG.md — dev backlog (operator maintains, CEO injects with `BUILD <thing>`)

Every item ships as a PR with evidence (tests, screenshots, or backtest) in the
description. Deploy only on explicit `APPROVE DEPLOY`.

## Next up
1. **Skipped-ticket shadow tracker** — small table + endpoint logging every ticket
   (sent/executed/skipped) with entry-day price; nightly forward-return backfill.
   Feeds monthly audit. (Pairs with research item #1.)
2. **Redeploy prod to V3.4 Fixed60d** — prod UI still shows stale Fixed30d "EXIT NOW"
   on NVDA. Code is already fixed locally; needs CEO deploy approval.
3. **`response_model=` on the hot endpoints** — /scan/combined, /analyze, /portfolio
   first (27 of 31 endpoints lack output validation).
4. **OpportunitiesTab poller fix** — force-refresh can stack 5s pollers (use a ref).
5. **SectorsTab error/retry state** — failed first load currently shows "No sector
   data" until remount.
6. **AllocationChart.tsx** — dead code? Wire it into the Portfolio tab or delete it.
7. **Telegram-ticket → positions sync helper** — one script that records an EXECUTED
   fill into prod API + local positions.db in one shot (reduces the three-way drift
   that keeps happening).

## Done
(move items here with PR link + deploy date)
