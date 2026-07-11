# OPERATOR_PROTOCOL.md — Telegram command grammar

Every CEO message is a work order. Parse intent loosely (natural language is fine),
but these keywords have exact meanings. Always confirm what you understood before
long-running work.

## Trade flow
- You send a TRADE TICKET:
  `TICKET #<n> BUY <TICKER> — <shares> sh @ ~$<live px> = $<cost> | WR <x>% (<n> trades) | composite <score> | thesis: <1 line> | data as of <timestamp>`
- CEO replies:
  - `EXECUTED <ticker> [shares] [price]` → record the fill EVERYWHERE it must live
    (production API positions, local positions.db, CLAUDE.md positions table — all
    three, per the buy/sell sync rule). Confirm the recorded state back.
  - `SKIP <ticker> [reason]` → log the skip + reason to memory (skips are data:
    compare skipped-ticket forward returns vs executed in the monthly audit).
  - `SOLD <ticker> [shares] [price]` → record exit in all three places, compute
    realized P&L including $1.50 fee (10 free trades/month, then $1.50).

## Approvals
- `APPROVE PR <#|link>` → merge the PR. Does NOT authorize deploy.
- `APPROVE DEPLOY <backend|frontend>` → deploy that one target once
  (fly deploy / vercel + re-alias superapp-blue). Never reuse an old approval.
- `REJECT <thing> [reason]` → stop, log reason to memory.

## Work orders
- `RESEARCH <idea>` → add to RESEARCH_QUEUE.md at top priority; run it in the next
  research window (or immediately if asked).
- `BUILD <feature/fix>` → add to BACKLOG.md; implement in next dev window → PR.
- `STATUS` → portfolio snapshot + timers + regime + open PRs + research in flight.
- `SCAN` → run the entry scan now (regime gate → deep scanner → veto chain → tickets).
- `AUDIT` → run the honest monthly audit now (vs deposit-matched QQQ).
- `PAUSE` / `RESUME` → stop/restart all proactive work (crons keep firing but only
  report "paused"). Confirm state change.

## Anything else
Free-form questions → answer from verified data. If the answer needs a backtest or a
live fetch, say "checking" and come back with the verified number — never guess first.

## Escalation rules (message the CEO immediately, outside scheduled reports)
- Holding's earnings moved to <7 days out (exit ticket attached)
- Exit timer fires within 2 trading days (exit-and-replace ticket attached)
- Regime flips to DANGER / CRISIS / WEAK
- Stock-specific negative news on a holding (downgrade, miss, guidance cut)
- A research result that changes live strategy materially (validated, not preliminary)
- Anything broken in production (API down, stale universe, scan failures)
