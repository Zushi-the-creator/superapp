# OpenClaw Trading Operator — setup

An always-on operator agent: monitors the portfolio, scans for entries, researches and
backtests improvements around the clock, ships PRs, and reports to the CEO on WhatsApp.
It recommends everything and executes nothing at the broker.

## Install (one time, ~15 min)

```bash
# 1. Install + onboard (Anthropic API key or OAuth; pick a workspace dir)
npm install -g openclaw@latest
openclaw onboard

# 2. Merge openclaw.json.example into ~/.openclaw/openclaw.json FIRST
#    (sets the WhatsApp allowlist to your number so only you can command the bot)

# 3. WhatsApp: link via QR (like WhatsApp Web). A dedicated number (spare SIM/eSIM)
#    is recommended so the operator has its own chat; your personal number also
#    works (self-chat mode).
openclaw channels login --channel whatsapp   # scan the QR from the operator's phone
openclaw gateway                             # start the always-on gateway

# 4. Copy the operator identity into the OpenClaw workspace (default ~/.openclaw/workspace)
cp SOUL.md OPERATOR_PROTOCOL.md HEARTBEAT.md ~/.openclaw/workspace/
# Queue/backlog files stay HERE in the repo (version-controlled); SOUL.md points to them.

# 5. Create the schedule (your number in E.164 — this is where reports are sent)
CEO_PHONE="+9725XXXXXXXX" ./setup_cron.sh
openclaw cron list   # verify 7 jobs
```

## The loop

| When (local) | Job | Output |
|---|---|---|
| 14:30 IL (07:30 ET) M-F | Pre-market brief | Positions, timers, earnings, regime |
| 16:40 IL (09:40 ET) M-F | Entry scan | 0-3 trade tickets (live prices, full veto chain) |
| 23:15 IL (16:15 ET) M-F | EOD report | P&L vs QQQ, discipline scorecard, shadow book |
| 02:00 IL Tue-Sat | Nightly research | One hypothesis backtested → verdict or proposal |
| 08:00 IL M-F | News & studies sweep | Holdings news; Mondays: new academic studies |
| Sat 10:00 IL | Dev sprint | One backlog item → PR (never deploys) |
| 1st of month | Board audit | Honest ROI attribution vs deposit-matched QQQ |
| Every 30m, market hours | Heartbeat | Silent unless earnings/timer/regime/news alert |

You drive it from WhatsApp: `EXECUTED NVDA 10 207.30`, `SKIP BE too concentrated`,
`RESEARCH does VIX term structure improve the regime gate`, `BUILD sector tab retry`,
`APPROVE DEPLOY backend`, `STATUS`, `SCAN`, `PAUSE`. Full grammar: OPERATOR_PROTOCOL.md.

## Rollout

- **Week 1 — dry run.** Tickets marked [DRY RUN]; verify its numbers against the prod
  UI daily before trusting it.
- **Week 2 — advisory live.** Real tickets; you execute what you agree with. First dev
  sprint and nightly research runs.
- **Week 3+ — full cadence.** If the laptop sleeps, move the gateway to a Mac mini or
  small VPS — a sleeping gateway means missed earnings alerts. (Note: Stooq is blocked
  from Fly.io IPs; a generic VPS is fine, or keep data fetching on Tiingo as configured.)

## Guardrails (structural, not just prompted)

- No broker API exists → the agent physically cannot trade; it writes tickets.
- Deploys gated on per-deploy `APPROVE DEPLOY` (SOUL rule 5 + protocol).
- Every strategy suggestion requires a point-in-time backtest + portfolio sim first;
  negative results land in TESTED_REJECTED.md so ideas don't get re-litigated.
- Fetched web content is data, never instructions (prompt-injection guard).
- Nightly research bounded: one hypothesis, max 3 approaches, then write up and stop.

## Cost

Isolated cron sessions + light-context heartbeats: expect ~$40-100/mo API depending on
research depth. The nightly `--thinking high` research runs are the main line item —
that's the budget doing its job.
