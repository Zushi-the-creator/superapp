# HEARTBEAT.md — periodic monitoring checklist

Keep runs cheap: check cached/local state first, hit APIs only when a check is due.
If nothing needs attention, reply HEARTBEAT_OK.

tasks:
  - every: 30m  # active during US market hours (config activeHours)
    - Earnings check: any holding with earnings <7 days (Finnhub FORWARD calendar
      only — the news-based detector is a known false-positive source)? → ALERT
      with exit ticket.
    - Timer check: any position at trading day ≥58/60 (MR/BOTH) or ≥88/90 (MOM)?
      → ALERT: prepare exit-and-replace ticket for a GREEN day.
    - Regime check: /api/v2 regime — flipped to DANGER/CRISIS/WEAK since last check?
      → ALERT.
    - Holdings news sweep (Google News RSS): stock-specific negative on any holding?
      → ALERT. Market-wide noise → ignore.
  - every: 4h
    - Production health: prod API responding? universe data fresh (data_end current)?
      quote overlay live? → if broken, ALERT with diagnosis.
  - every: 1d
    - Memory hygiene: yesterday's decisions, skips, and research outcomes written to
      memory files? Research queue reprioritized?
