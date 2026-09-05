# 30 / 60 / 90-Day Strategy Simulation — by Regime, Strategy, Sector

Data through **2026-09-04** (Tiingo adjusted daily bars, 2980 series from `data/us_stock_universe.txt` + SPY/QQQ/IWM/sector ETFs, VIX from FMP). Windows: 30d from 2026-08-05, 60d from 2026-07-06, 90d from 2026-06-06 (signal date within window).

Method: signal at close, **entry at next-day open**, exit per rule on closes, unfinished trades **marked-to-market at the last close** ("Open" column = share of trades still open). Fees: broker schedule (10 free actions/month then $1.50/action) in the portfolio simulation; worst-case 0.18% round-trip on a $1,667 slot in the signal-level tables. Non-overlapping trades per ticker per rule. No earnings/sentiment veto applied (pure price rules).

## Executive summary

**Mean reversion won, momentum and breakouts lost, and the sector mattered more than the strategy.** Data through 2026-09-04; SPY +0.05% / +2.52% / +4.46% over 30 / 60 / 90 days; only HEALTHY, PULLBACK and DIP_BUY regimes occurred (no bear or high-VIX days).

- **Clear winner, most consistent: MR_V24** (RSI(2)<10, above SMA50, volume >1.5x, Fixed14d). Positive in every month (Jun +3.0%, Jul +0.8%, Aug +0.8%), 59% WR / +1.46% per trade over 90d (t=+5.0). As a 6-slot portfolio it beat SPY in all three windows with 96–98% of random draws positive: MC median +3.8% (30d), +2.9% (60d), +10.2% (90d); live-ranked +4.8% / +4.0% / +13.0%.
- **Biggest per-trade edge: MR_V3** (the live V3.0 MR entry, Fixed60d): +5.19% per trade, 57.8% WR, t=+9.3 on 1,841 trades. Caveats: 68% of those trades are still open (marked to market), and 551 of them fired on the 2026-06-08 selloff. Excluding that day it is still +4.0% / 56% WR (t=+7.0). Its weak spot is stocks with ATR >8% (183 trades, 32% WR, −8.85%); capping ATR at 8% would have lifted the average to about +6.7%.
- **Clear losers: MOM_STRICT** (lost in all three windows, 31–33% WR, t ≤ −2.8), **BREAKOUT** (36–39% WR, negative in every window), and **MOM_V3** (flat at +0.03% over 90d, −2.58% in the last 30d, and −13.9% in Technology). Momentum only worked on DIP_BUY days (+4.0%, 61% WR) and in Energy / Financials / Healthcare.
- **Sectors that won across every strategy: Healthcare (+3.97%, 64% WR), Energy (+2.95%, 67% WR), Financials (+1.69%, 64% WR).** MR_V3 in Energy was +14.4% / 83% WR, in Healthcare +16.0% / 74% WR. **Sectors that lost: Industrials (−1.67%, t=−7.7), Real Estate, Technology, Utilities**, in every window and for every strategy.
- **Regime:** in HEALTHY (51 of 63 days) mean reversion won (MR_V3 +6.6%, MR_V24 +2.1%) and momentum lost (MOM_STRICT −2.1%, BREAKOUT −0.5%). On the 4 DIP_BUY days the picture flipped: Connors-style dips 69% WR, momentum +4.0%, but MR_V3 flat (it was buying the second leg down). By the **stock's own regime**, MR_V3 made money on stocks in SIDEWAYS/BEAR trends (+8.4% / +10.4%) and lost on stocks already in BULL trends (−1.8%, 44% WR).
- **Exits:** longer holds won for mean reversion (Fixed60d/90d best for all three MR entries); no exit rescues momentum. The live Fixed60d for MR is the right choice; the M1 trailing stop is the worst of MOM_STRICT's exits.
- **The live MR+MOM 6-slot book, ranked the way the evaluator ranks, trailed SPY in all three windows (−1.8%, −1.9%, −0.4%)**, dragged by its momentum slots and by 60/90-day holds that lock in one batch of picks. The same book with MR only or with MR_V24 rules was positive.

**What to change:** keep mean reversion, cap ATR at 8%, drop or shrink the momentum sleeve in HEALTHY regimes, and weight Healthcare / Energy / Financials over Industrials / Real Estate / Tech. All numbers below are marked-to-market unless the table says closed-only.


## 1. What the market did (regime coverage)

| Window | api_v2 regime days | Trend regime days (SPY) | SPY | QQQ | IWM |
|---|---|---|---:|---:|---:|
| 30d | HEALTHY 23 | BULL 23 | +0.05% | +0.23% | -1.25% |
| 60d | HEALTHY 38, PULLBACK 7 | BULL 38, SIDEWAYS 7 | +2.52% | -0.53% | -0.97% |
| 90d | HEALTHY 51, PULLBACK 8, DIP_BUY 4 | BULL 55, SIDEWAYS 8 | +4.46% | +0.51% | +4.43% |

SPY ran 737.34 → 770.19 over the 90 days; deepest drawdown from 52-week high was -4.5% on 2026-06-10 (VIX 22.22). VIX range 14.2–22.2. No DANGER / CRISIS / WEAK / CORRECTION / BEAR days occurred, so those regimes cannot be evaluated on this period.

Sector ETF returns (benchmark for the sector tables):

| Window | XLK | XLE | XLF | XLV | XLY | XLP | XLU | XLB | XLI | XLRE | XLC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30d | +0.7% | +11.8% | +0.2% | +4.4% | -3.1% | -0.9% | -1.3% | -0.4% | -6.0% | -2.8% | +1.1% |
| 60d | +2.0% | +20.6% | +3.5% | +5.9% | -2.6% | +0.6% | -4.9% | +0.9% | -5.5% | -0.8% | +1.6% |
| 90d | +1.8% | +10.6% | +12.2% | +12.8% | -0.2% | +2.5% | -0.4% | +5.4% | +1.2% | +0.6% | +1.1% |

## 2. Strategy scoreboard (each strategy with its own live exit)

Marked-to-market basis (all signals in window, open trades valued at last close). t-stat = mean / standard error; |t| ≥ 2 is a real edge, not noise.


### 30-day window (signals since 2026-08-05)

| Strategy | Trades | Win rate | Avg ret | Median | PF | t-stat | Open (MTM) | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| MR_V3 — RSI(2)<10 + ATR>=3% (live V3.0 MR), Fixed60d | 75 | 56.0% | +1.32% | +0.51% | 1.71 | +1.7 | 100% | mixed |
| MR_V24 — RSI(2)<10 + >SMA50 + vol>1.5x (ATLAS V2.4), Fixed14d | 338 | 53.3% | +0.47% | +0.16% | 1.22 | +1.3 | 57% | mixed |
| MR_CONNORS — RSI(2)<10 + >SMA200, exit close>SMA5 (max 10d) | 4114 | 55.8% | -0.05% | +0.30% | 0.97 | -0.6 | 9% | weak |
| MOM_V3 — Minervini 6/6 + 20d ret>5% (live V3.0 MOM), Fixed90d | 97 | 32.0% | -2.58% | -1.76% | 0.41 | -2.8 | 100% | **LOSE** |
| MOM_STRICT — Minervini 6/6 + 20d ret>15% + vol>1.5x, trail -10%/SMA50 | 122 | 31.1% | -3.13% | -4.00% | 0.37 | -4.4 | 56% | **LOSE** |
| BREAKOUT — 20d-high breakout + vol>1.5x + >SMA50, exit close<SMA10 | 498 | 38.6% | -0.68% | -1.35% | 0.77 | -2.0 | 19% | weak |

Closed trades only (exit rule actually triggered — for time exits this is biased toward the earliest signals, for stop-style exits toward the losers):

| Strategy (closed only) | Trades | Win rate | Avg ret | Median | PF | t-stat | Open (MTM) |
|---|---:|---:|---:|---:|---:|---:|---:|
| MR_V3 | 0 | – | – | – | – | – | – |
| MR_V24 | 145 | 53.1% | +0.34% | +0.35% | 1.11 | +0.5 | 57% |
| MR_CONNORS | 3740 | 60.2% | +0.27% | +0.50% | 1.22 | +3.2 | 9% |
| MOM_V3 | 0 | – | – | – | – | – | – |
| MOM_STRICT | 54 | 3.7% | -8.83% | -9.52% | 0.04 | -11.7 | 56% |
| BREAKOUT | 401 | 32.2% | -1.44% | -2.15% | 0.59 | -3.9 | 19% |

### 60-day window (signals since 2026-07-06)

| Strategy | Trades | Win rate | Avg ret | Median | PF | t-stat | Open (MTM) | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| MR_V3 — RSI(2)<10 + ATR>=3% (live V3.0 MR), Fixed60d | 300 | 57.0% | +2.16% | +0.83% | 1.68 | +2.8 | 100% | **WIN** |
| MR_V24 — RSI(2)<10 + >SMA50 + vol>1.5x (ATLAS V2.4), Fixed14d | 677 | 55.4% | +0.86% | +0.31% | 1.38 | +2.7 | 29% | mixed |
| MR_CONNORS — RSI(2)<10 + >SMA200, exit close>SMA5 (max 10d) | 8032 | 59.3% | +0.14% | +0.50% | 1.11 | +2.5 | 5% | mixed |
| MOM_V3 — Minervini 6/6 + 20d ret>5% (live V3.0 MOM), Fixed90d | 337 | 49.9% | +0.45% | -0.03% | 1.11 | +0.7 | 100% | mixed |
| MOM_STRICT — Minervini 6/6 + 20d ret>15% + vol>1.5x, trail -10%/SMA50 | 215 | 33.0% | -2.09% | -4.03% | 0.59 | -2.8 | 48% | **LOSE** |
| BREAKOUT — 20d-high breakout + vol>1.5x + >SMA50, exit close<SMA10 | 1005 | 36.3% | -0.65% | -1.45% | 0.78 | -2.6 | 10% | **LOSE** |

Closed trades only (exit rule actually triggered — for time exits this is biased toward the earliest signals, for stop-style exits toward the losers):

| Strategy (closed only) | Trades | Win rate | Avg ret | Median | PF | t-stat | Open (MTM) |
|---|---:|---:|---:|---:|---:|---:|---:|
| MR_V3 | 0 | – | – | – | – | – | – |
| MR_V24 | 484 | 56.2% | +0.98% | +0.45% | 1.39 | +2.3 | 29% |
| MR_CONNORS | 7658 | 61.6% | +0.31% | +0.61% | 1.25 | +5.4 | 5% |
| MOM_V3 | 0 | – | – | – | – | – | – |
| MOM_STRICT | 111 | 7.2% | -7.85% | -9.15% | 0.09 | -11.9 | 48% |
| BREAKOUT | 907 | 33.2% | -1.03% | -1.90% | 0.67 | -4.0 | 10% |

### 90-day window (signals since 2026-06-06)

| Strategy | Trades | Win rate | Avg ret | Median | PF | t-stat | Open (MTM) | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| MR_V3 — RSI(2)<10 + ATR>=3% (live V3.0 MR), Fixed60d | 1841 | 57.8% | +5.19% | +3.32% | 1.85 | +9.3 | 68% | **WIN** |
| MR_V24 — RSI(2)<10 + >SMA50 + vol>1.5x (ATLAS V2.4), Fixed14d | 1037 | 59.3% | +1.46% | +0.78% | 1.64 | +5.0 | 19% | **WIN** |
| MR_CONNORS — RSI(2)<10 + >SMA200, exit close>SMA5 (max 10d) | 10906 | 59.0% | +0.10% | +0.48% | 1.07 | +2.1 | 3% | mixed |
| MOM_V3 — Minervini 6/6 + 20d ret>5% (live V3.0 MOM), Fixed90d | 1229 | 50.9% | +0.03% | +0.23% | 1.00 | +0.1 | 100% | mixed |
| MOM_STRICT — Minervini 6/6 + 20d ret>15% + vol>1.5x, trail -10%/SMA50 | 434 | 32.9% | -1.53% | -3.70% | 0.70 | -2.8 | 28% | **LOSE** |
| BREAKOUT — 20d-high breakout + vol>1.5x + >SMA50, exit close<SMA10 | 1768 | 38.7% | -0.26% | -1.15% | 0.90 | -1.4 | 6% | weak |

Closed trades only (exit rule actually triggered — for time exits this is biased toward the earliest signals, for stop-style exits toward the losers):

| Strategy (closed only) | Trades | Win rate | Avg ret | Median | PF | t-stat | Open (MTM) |
|---|---:|---:|---:|---:|---:|---:|---:|
| MR_V3 | 584 | 62.8% | +8.72% | +7.78% | 2.22 | +7.0 | 68% |
| MR_V24 | 844 | 60.7% | +1.67% | +1.08% | 1.67 | +4.8 | 19% |
| MR_CONNORS | 10532 | 60.7% | +0.22% | +0.56% | 1.16 | +4.5 | 3% |
| MOM_V3 | 0 | – | – | – | – | – | – |
| MOM_STRICT | 314 | 20.4% | -4.55% | -6.17% | 0.30 | -8.6 | 28% |
| BREAKOUT | 1670 | 37.1% | -0.45% | -1.39% | 0.84 | -2.4 | 6% |

## 3. Portfolio simulation — what the live system would have done

$10,000 start, max 6 slots, equal weight, api_v2 regime sizing (HEALTHY = 70% slot size, DIP_BUY/PULLBACK = 100%), next-open entries, exits per strategy rule, broker fee schedule (10 free actions/month, then $1.50). Open positions valued at the last close.

Three ways of choosing which signals fill the 6 slots:

- **live**: rank by each stock's backtest expected value (Bayesian WR × avg return) with the live VETO (≥5 trades, WR ≥ 55%, avg ≥ 3% MR / 2% MOM) — this is how `strategy_evaluator.py` ranks. Cache source: data/simulation_30_60_90/stock_cache.json (10-year Tiingo history, trades exited before 2026-06-06 only); validated stocks: {'mr': 969, 'mom': 828}.
- **deepest**: MR by deepest RSI(2) then SMA50 buffer, momentum by 20d return × volume ratio (the M1 scanner score).
- **random**: 100 Monte Carlo runs picking uniformly among qualifying signals — the strategy's expected portfolio result independent of ranking luck. With 6 slots over ≤ 63 trading days, any single run is dominated by a handful of names; read the median and the p10–p90 band, not one number.


### 30-day window — SPY buy & hold +0.05%

| Portfolio | live rank | live closed (WR / avg) | live open | deepest rank | MC median | MC p10 … p90 | MC % runs > 0 | MC avg MaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MR_V24_14d | +4.81% | 6 (67% / +2.0%) | 6 | +2.85% | **+3.82%** | +1.8 … +6.8 | 96% | -1.6% |
| MR_V24_21d | +2.62% | 6 (67% / +3.7%) | 0 | +2.86% | **+2.68%** | +0.2 … +5.6 | 91% | -1.7% |
| BREAKOUT_SMA10 | +3.62% | 12 (58% / +2.8%) | 6 | -1.56% | **+0.66%** | -3.9 … +6.0 | 56% | -5.2% |
| MR_V3_SMA5 | -4.46% | 28 (64% / -1.4%) | 5 | +6.17% | **+0.45%** | -5.6 … +4.8 | 53% | -4.3% |
| MR_V3_only | -5.71% | 0 | 6 | -1.78% | **+0.28%** | -5.1 … +4.1 | 54% | -3.8% |
| MR_CONNORS_SMA5 | -2.81% | 30 (67% / -0.6%) | 5 | +2.00% | **-0.06%** | -3.6 … +4.6 | 49% | -3.1% |
| LIVE_MR+MOM | -1.83% | 0 | 6 | -6.46% | **-0.74%** | -5.5 … +3.1 | 41% | -4.2% |
| MR_V3_10d | -9.42% | 12 (25% / -6.9%) | 0 | -3.14% | **-1.56%** | -5.2 … +3.0 | 37% | -5.2% |
| MOM_V3_only | +1.40% | 0 | 6 | -10.37% | **-2.06%** | -5.6 … +1.8 | 20% | -5.0% |
| MOM_STRICT_TRAIL | +0.36% | 1 (0% / -15.7%) | 6 | -10.49% | **-2.68%** | -6.9 … +0.9 | 21% | -5.2% |

Live MR+MOM without regime sizing (always 100% slot size): -2.62% (max DD -6.02%).

Live-ranked MR+MOM trades in the 30d window:

| Ticker | Rule | Signal | Entry | Exit | Ret | Days | Regime |
|---|---|---|---:|---:|---:|---:|---|
| CDNA | MOM_V3 | – | 46.00 | open @ 50.88 | +10.61% | 21 | – |
| LINC | MR_V3 | – | 42.40 | open @ 25.64 | -39.52% | 21 | – |
| NVDA | MOM_V3 | – | 221.53 | open @ 230.36 | +3.99% | 21 | – |
| POWL | MR_V3 | – | 207.84 | open @ 181.17 | -12.83% | 21 | – |
| DAC | MOM_V3 | – | 142.07 | open @ 155.26 | +9.28% | 21 | – |
| CHRD | MR_V3 | – | 129.80 | open @ 146.39 | +12.78% | 21 | – |

### 60-day window — SPY buy & hold +2.52%

| Portfolio | live rank | live closed (WR / avg) | live open | deepest rank | MC median | MC p10 … p90 | MC % runs > 0 | MC avg MaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MR_V24_21d | +4.72% | 8 (88% / +5.8%) | 4 | +5.96% | **+5.02%** | +1.6 … +9.1 | 99% | -2.1% |
| MR_V3_SMA5 | -2.54% | 60 (60% / -0.5%) | 5 | +10.05% | **+3.18%** | -3.4 … +14.0 | 73% | -6.6% |
| MR_V3_10d | -4.94% | 24 (46% / -1.7%) | 0 | -2.69% | **+3.08%** | -3.1 … +9.6 | 70% | -6.0% |
| MR_V24_14d | +3.95% | 12 (67% / +2.9%) | 6 | +2.21% | **+2.86%** | -1.6 … +8.4 | 75% | -3.6% |
| MR_CONNORS_SMA5 | -5.48% | 56 (57% / -0.8%) | 5 | +5.99% | **+2.42%** | -2.7 … +9.0 | 69% | -5.2% |
| LIVE_MR+MOM | -1.88% | 0 | 6 | +9.33% | **-1.05%** | -6.8 … +7.4 | 39% | -6.5% |
| MOM_V3_only | -1.35% | 0 | 6 | +12.76% | **-1.56%** | -6.5 … +4.1 | 35% | -5.7% |
| MR_V3_only | -6.71% | 0 | 6 | +1.80% | **-1.66%** | -7.7 … +7.1 | 40% | -7.8% |
| MOM_STRICT_TRAIL | +11.57% | 7 (29% / -0.1%) | 6 | -2.06% | **-2.10%** | -7.1 … +2.6 | 23% | -7.1% |
| BREAKOUT_SMA10 | -5.32% | 29 (28% / -3.0%) | 6 | -5.08% | **-4.12%** | -10.7 … +2.8 | 19% | -8.2% |

Live MR+MOM without regime sizing (always 100% slot size): -2.68% (max DD -17.55%).

Live-ranked MR+MOM trades in the 60d window:

| Ticker | Rule | Signal | Entry | Exit | Ret | Days | Regime |
|---|---|---|---:|---:|---:|---:|---|
| CDNA | MOM_V3 | – | 29.36 | open @ 50.88 | +73.30% | 43 | – |
| RKLB | MR_V3 | – | 90.01 | open @ 64.26 | -28.61% | 43 | – |
| ACMR | MOM_V3 | – | 92.56 | open @ 74.44 | -19.58% | 43 | – |
| FEIM | MR_V3 | – | 63.97 | open @ 60.67 | -5.16% | 43 | – |
| ESTA | MOM_V3 | – | 91.09 | open @ 74.29 | -18.44% | 43 | – |
| FLEX | MR_V3 | – | 132.94 | open @ 109.51 | -17.62% | 43 | – |

### 90-day window — SPY buy & hold +4.46%

| Portfolio | live rank | live closed (WR / avg) | live open | deepest rank | MC median | MC p10 … p90 | MC % runs > 0 | MC avg MaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MR_V24_14d | +12.99% | 24 (71% / +4.3%) | 6 | +14.87% | **+10.20%** | +3.6 … +19.3 | 98% | -5.2% |
| MR_V3_only | +2.04% | 6 (67% / +0.5%) | 6 | +5.84% | **+4.77%** | -3.8 … +16.7 | 73% | -7.8% |
| MR_V3_SMA5 | -6.10% | 82 (57% / -0.8%) | 5 | -7.01% | **+4.40%** | -3.1 … +13.6 | 74% | -8.4% |
| MR_V24_21d | +13.25% | 12 (75% / +7.6%) | 6 | +9.74% | **+3.52%** | -2.3 … +11.8 | 78% | -9.2% |
| MR_CONNORS_SMA5 | -8.22% | 83 (60% / -0.8%) | 5 | -0.23% | **+2.99%** | -4.3 … +11.3 | 69% | -6.5% |
| LIVE_MR+MOM | -0.35% | 3 (67% / +8.6%) | 6 | -12.47% | **+1.23%** | -7.5 … +11.4 | 59% | -7.9% |
| MR_V3_10d | -4.85% | 30 (50% / -1.4%) | 6 | -10.22% | **+0.30%** | -8.7 … +13.7 | 51% | -12.6% |
| MOM_V3_only | -6.22% | 0 | 6 | -10.30% | **-0.42%** | -8.1 … +9.4 | 48% | -8.5% |
| BREAKOUT_SMA10 | +1.21% | 40 (38% / -0.7%) | 6 | -14.27% | **-2.45%** | -9.9 … +6.6 | 38% | -10.5% |
| MOM_STRICT_TRAIL | +21.83% | 13 (38% / -1.3%) | 6 | -14.03% | **-5.15%** | -12.8 … +3.2 | 19% | -10.3% |

Live MR+MOM without regime sizing (always 100% slot size): -0.51% (max DD -25.35%).

Live-ranked MR+MOM trades in the 90d window:

| Ticker | Rule | Signal | Entry | Exit | Ret | Days | Regime |
|---|---|---|---:|---:|---:|---:|---|
| AXTI | MR_V3 | 2026-06-08 | 95.71 | 56.20 | -41.28% | 60 | HEALTHY |
| PVLA | MR_V3 | 2026-06-08 | 106.20 | 155.47 | +46.39% | 60 | HEALTHY |
| KGC | MR_V3 | 2026-06-08 | 26.21 | 31.59 | +20.54% | 60 | HEALTHY |
| ENPH | MOM_V3 | – | 57.12 | open @ 36.37 | -36.33% | 61 | – |
| AMR | MOM_V3 | – | 201.40 | open @ 225.41 | +11.92% | 61 | – |
| ACMR | MOM_V3 | – | 85.00 | open @ 74.44 | -12.42% | 61 | – |
| CDNA | MOM_V3 | – | 49.65 | open @ 50.88 | +2.48% | 0 | – |
| CRDO | MR_V3 | – | 162.10 | open @ 170.57 | +5.23% | 0 | – |
| DAC | MOM_V3 | – | 154.15 | open @ 155.26 | +0.72% | 0 | – |

## 3b. Current open positions (positions.db) marked to market

Returns use adjusted closes (split-safe). 'Since entry' is from the close on the entry date, not the recorded fill. positions.db was last updated 2026-04-02, so this may not be the actual current book.

| Ticker | Strategy | Entry | Days held | Since entry | 90d | 60d | 30d |
|---|---|---|---:|---:|---:|---:|---:|
| WDC | MEAN_REVERSION | 2026-02-23 | 135 | +66.8% | -8.6% | -19.0% | -10.0% |
| DBD | MEAN_REVERSION | 2026-03-11 | 123 | -8.7% | -15.4% | -18.4% | -12.1% |
| AMR | MEAN_REVERSION | 2026-04-02 | 107 | +7.7% | +11.4% | +43.1% | +54.3% |
| BBIO | MEAN_REVERSION | 2026-04-02 | 107 | +2.3% | +10.7% | -3.7% | -8.7% |
| POWL | MEAN_REVERSION | 2026-04-02 | 107 | -0.7% | -36.4% | -26.9% | -13.0% |
| APEI | MEAN_REVERSION | 2026-04-02 | 107 | -21.3% | -13.8% | -21.0% | -15.7% |

## 4. By market regime (api_v2 SPY/VIX regime at signal date)


### 90-day window

| Strategy | HEALTHY (51d) | PULLBACK (8d) | DIP_BUY (4d) |
|---|---|---|---|
| MR_V3 | 1441t, 61% WR, +6.57% **WIN** | 49t, 51% WR, +2.24% mixed | 351t, 45% WR, -0.08% weak |
| MR_V24 | 805t, 62% WR, +2.06% **WIN** | 167t, 52% WR, -0.25% weak | 65t, 45% WR, -1.49% weak |
| MR_CONNORS | 8564t, 57% WR, -0.02% weak | 1714t, 63% WR, +0.13% mixed | 628t, 69% WR, +1.71% **WIN** |
| MOM_V3 | 1022t, 50% WR, -0.40% weak | 93t, 47% WR, -0.11% weak | 114t, 61% WR, +3.98% **WIN** |
| MOM_STRICT | 326t, 32% WR, -2.08% **LOSE** | 79t, 34% WR, -0.96% weak | 29t, 41% WR, +3.08% mixed |
| BREAKOUT | 1124t, 38% WR, -0.52% **LOSE** | 509t, 35% WR, -0.16% weak | 135t, 58% WR, +1.51% **WIN** |

### 60-day window

| Strategy | HEALTHY (38d) | PULLBACK (7d) |
|---|---|---|
| MR_V3 | 254t, 58% WR, +2.08% **WIN** | 46t, 52% WR, +2.62% mixed |
| MR_V24 | 542t, 55% WR, +0.85% mixed | 135t, 57% WR, +0.90% mixed |
| MR_CONNORS | 6353t, 58% WR, +0.15% mixed | 1679t, 63% WR, +0.12% mixed |
| MOM_V3 | 278t, 50% WR, +0.46% mixed | 59t, 51% WR, +0.39% mixed |
| MOM_STRICT | 179t, 32% WR, -2.46% **LOSE** | 36t, 36% WR, -0.24% weak |
| BREAKOUT | 770t, 37% WR, -0.77% **LOSE** | 235t, 35% WR, -0.23% weak |

### By SPY trend regime (atlas_v2 RegimeDetector), 90-day window

| Strategy | BULL | SIDEWAYS |
|---|---|---|
| MR_V3 | 1792t, 58% WR, +5.27% **WIN** | 49t, 51% WR, +2.24% mixed |
| MR_V24 | 870t, 61% WR, +1.79% **WIN** | 167t, 52% WR, -0.25% weak |
| MR_CONNORS | 9192t, 58% WR, +0.10% mixed | 1714t, 63% WR, +0.13% mixed |
| MOM_V3 | 1136t, 51% WR, +0.04% mixed | 93t, 47% WR, -0.11% weak |
| MOM_STRICT | 355t, 33% WR, -1.66% **LOSE** | 79t, 34% WR, -0.96% weak |
| BREAKOUT | 1259t, 40% WR, -0.31% weak | 509t, 35% WR, -0.16% weak |

### By the stock's own regime (RegimeDetector on the stock), 90-day window

| Strategy | BULL | SIDEWAYS | BEAR | HIGH_VOL |
|---|---|---|---|---|
| MR_V3 | 651t, 44% WR, -1.83% **LOSE** | 809t, 64% WR, +8.37% **WIN** | 381t, 68% WR, +10.40% **WIN** | – |
| MR_V24 | 745t, 58% WR, +0.93% mixed | 292t, 62% WR, +2.83% **WIN** | – | – |
| MR_CONNORS | 6867t, 59% WR, +0.15% mixed | 4039t, 58% WR, +0.03% mixed | – | – |
| MOM_V3 | 1229t, 51% WR, +0.03% mixed | – | – | – |
| MOM_STRICT | 434t, 33% WR, -1.53% **LOSE** | – | – | – |
| BREAKOUT | 1096t, 35% WR, -0.69% **LOSE** | 672t, 45% WR, +0.44% mixed | – | – |

## 5. By sector (live exits, marked-to-market)

Finnhub industry mapped to GICS-style sectors. UNKNOWN = closed-end funds and SPACs that Finnhub does not classify.


### 90-day window — all strategies pooled

| Sector | Trades | Win rate | Avg ret | Median | PF | t-stat | Open (MTM) | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| HEALTHCARE | 2484 | 64.3% | +3.97% | +1.55% | 2.73 | +12.1 | 21% | **WIN** |
| ENERGY | 977 | 67.3% | +2.95% | +1.20% | 3.01 | +8.9 | 25% | **WIN** |
| FINANCIALS | 3306 | 64.4% | +1.69% | +0.92% | 2.65 | +13.5 | 17% | **WIN** |
| MATERIALS | 807 | 53.4% | +0.48% | +0.38% | 1.16 | +1.3 | 20% | mixed |
| CONSUMER_STAPLES | 641 | 55.9% | +0.11% | +0.57% | 1.05 | +0.4 | 23% | mixed |
| UNKNOWN | 1349 | 45.1% | -0.25% | -0.08% | 0.70 | -2.1 | 11% | **LOSE** |
| CONSUMER_DISCRETIONARY | 1400 | 50.7% | -0.33% | +0.08% | 0.90 | -1.2 | 21% | weak |
| COMMUNICATION | 724 | 53.3% | -0.34% | +0.21% | 0.89 | -0.9 | 22% | weak |
| REAL_ESTATE | 912 | 46.9% | -0.60% | -0.17% | 0.65 | -4.4 | 18% | **LOSE** |
| TECHNOLOGY | 1499 | 49.4% | -0.79% | -0.14% | 0.85 | -2.0 | 21% | **LOSE** |
| UTILITIES | 387 | 55.8% | -0.92% | +0.28% | 0.52 | -3.7 | 11% | **LOSE** |
| INDUSTRIALS | 2729 | 47.7% | -1.67% | -0.24% | 0.61 | -7.7 | 20% | **LOSE** |

### 90-day window — strategy × sector (avg return, WR, trades)

| Strategy | COMMUNICATION | CONS_DISCRETIONARY | CONS_STAPLES | ENERGY | FINANCIALS | HEALTHCARE | INDUSTRIALS | MATERIALS | REAL_ESTATE | TECHNOLOGY | UTILITIES |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MR_V3 | +0.8% / 50% / 96t  | +0.9% / 48% / 213t  | +1.9% / 50% / 84t  | +14.4% / 83% / 107t ✅ | +10.2% / 75% / 232t ✅ | +16.0% / 74% / 309t ✅ | -2.5% / 42% / 362t ❌ | +5.5% / 59% / 118t ✅ | +0.6% / 47% / 58t  | +3.4% / 52% / 217t  | -4.6% / 33% / 24t ❌ |
| MR_V24 | +1.3% / 50% / 30t  | -0.6% / 46% / 76t  | +2.6% / 69% / 45t ✅ | +3.8% / 82% / 44t ✅ | +2.9% / 74% / 232t ✅ | +2.9% / 60% / 146t ✅ | +0.3% / 51% / 143t  | -1.1% / 49% / 41t  | -0.7% / 46% / 54t  | +2.4% / 51% / 57t  | -0.5% / 42% / 19t  |
| MR_CONNORS | -0.2% / 59% / 455t  | +0.1% / 58% / 838t  | -0.1% / 61% / 389t  | +0.4% / 66% / 629t  | +0.6% / 66% / 2175t  | +1.2% / 68% / 1397t ✅ | -0.7% / 54% / 1665t ❌ | -0.2% / 58% / 483t  | -0.3% / 52% / 640t ❌ | -0.4% / 54% / 920t  | -0.1% / 64% / 296t  |
| MOM_V3 | -4.0% / 41% / 51t  | -4.2% / 30% / 96t ❌ | -2.8% / 42% / 43t  | +10.6% / 82% / 90t ✅ | +5.5% / 76% / 270t ✅ | +11.2% / 67% / 174t ✅ | -8.0% / 32% / 219t ❌ | -2.9% / 40% / 60t  | -2.5% / 27% / 70t ❌ | -13.9% / 25% / 97t ❌ | -7.5% / 14% / 21t ❌ |
| MOM_STRICT | -3.4% / 33% / 18t ❌ | -0.2% / 38% / 34t  | -3.6% / 20% / 10t  | +0.1% / 50% / 36t  | -0.3% / 40% / 40t  | +2.1% / 45% / 117t  | -4.2% / 20% / 89t ❌ | -4.4% / 11% / 18t  | -2.5% / 30% / 10t  | -5.1% / 21% / 57t ❌ | – |
| BREAKOUT | -0.3% / 39% / 74t  | -1.6% / 34% / 143t ❌ | +0.1% / 41% / 70t  | -0.9% / 38% / 71t  | -0.3% / 36% / 357t  | +1.6% / 49% / 341t  | -1.6% / 38% / 251t ❌ | +1.6% / 41% / 87t  | -1.9% / 26% / 80t ❌ | -0.5% / 43% / 151t  | -1.1% / 31% / 26t ❌ |

### 60-day window — all strategies pooled

| Sector | Trades | Win rate | Avg ret | Median | PF | t-stat | Open (MTM) | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| ENERGY | 616 | 70.9% | +1.84% | +1.24% | 2.94 | +8.2 | 20% | **WIN** |
| HEALTHCARE | 1538 | 59.4% | +1.03% | +0.89% | 1.46 | +4.0 | 16% | **WIN** |
| MATERIALS | 461 | 56.2% | +0.60% | +0.67% | 1.33 | +2.0 | 17% | mixed |
| FINANCIALS | 2265 | 63.0% | +0.53% | +0.71% | 1.54 | +6.5 | 10% | mixed |
| CONSUMER_STAPLES | 392 | 56.6% | -0.04% | +0.51% | 0.98 | -0.1 | 19% | weak |
| UNKNOWN | 917 | 44.8% | -0.11% | -0.08% | 0.81 | -1.7 | 13% | weak |
| TECHNOLOGY | 854 | 53.0% | -0.18% | +0.26% | 0.94 | -0.6 | 14% | weak |
| COMMUNICATION | 428 | 53.0% | -0.27% | +0.17% | 0.86 | -0.9 | 16% | weak |
| CONSUMER_DISCRETIONARY | 800 | 51.5% | -0.60% | +0.11% | 0.75 | -2.6 | 12% | **LOSE** |
| UTILITIES | 238 | 55.0% | -0.77% | +0.21% | 0.50 | -3.0 | 5% | **LOSE** |
| INDUSTRIALS | 1488 | 51.4% | -0.83% | +0.10% | 0.68 | -4.7 | 11% | **LOSE** |
| REAL_ESTATE | 569 | 44.6% | -0.84% | -0.20% | 0.46 | -6.2 | 13% | **LOSE** |

### 60-day window — strategy × sector (avg return, WR, trades)

| Strategy | COMMUNICATION | CONS_DISCRETIONARY | CONS_STAPLES | ENERGY | FINANCIALS | HEALTHCARE | INDUSTRIALS | MATERIALS | REAL_ESTATE | TECHNOLOGY | UTILITIES |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MR_V3 | +7.3% / 64% / 14t  | +0.7% / 53% / 15t  | +0.6% / 35% / 20t  | +6.4% / 78% / 9t  | +2.1% / 67% / 84t ✅ | +5.2% / 60% / 58t  | +1.6% / 59% / 39t  | +2.6% / 53% / 17t  | -1.5% / 32% / 19t  | -2.2% / 50% / 14t  | -5.3% / 29% / 7t  |
| MR_V24 | -0.6% / 37% / 19t  | -1.2% / 46% / 52t  | +1.6% / 62% / 24t  | +4.0% / 82% / 38t ✅ | +2.0% / 68% / 148t ✅ | +0.8% / 56% / 98t  | +0.2% / 49% / 90t  | +0.8% / 60% / 20t  | -3.1% / 19% / 32t ❌ | +3.8% / 58% / 38t ✅ | -2.0% / 31% / 13t  |
| MR_CONNORS | -0.1% / 58% / 321t  | -0.1% / 56% / 607t  | -0.0% / 60% / 294t  | +1.1% / 73% / 431t ✅ | +0.5% / 66% / 1813t  | +0.9% / 65% / 1085t  | -0.6% / 55% / 1120t ❌ | +0.6% / 62% / 323t  | -0.4% / 50% / 476t ❌ | -0.4% / 54% / 641t  | -0.4% / 59% / 204t  |
| MOM_V3 | -1.0% / 50% / 16t  | -3.8% / 33% / 30t  | -3.5% / 40% / 20t  | +9.9% / 89% / 46t ✅ | -0.9% / 46% / 48t  | +3.0% / 49% / 49t  | -2.9% / 40% / 52t  | -3.3% / 24% / 17t  | -4.0% / 20% / 15t ❌ | +2.4% / 59% / 22t  | – |
| MOM_STRICT | -6.0% / 18% / 11t  | -5.6% / 25% / 16t ❌ | – | +1.1% / 54% / 33t  | -3.8% / 40% / 15t  | +0.7% / 38% / 58t  | -4.1% / 28% / 40t ❌ | -5.4% / 7% / 14t  | – | -2.3% / 27% / 22t  | – |
| BREAKOUT | -1.7% / 30% / 47t ❌ | -2.0% / 30% / 80t ❌ | +0.6% / 41% / 32t  | -0.9% / 41% / 59t  | -0.8% / 34% / 157t ❌ | +0.2% / 38% / 190t  | -2.2% / 35% / 147t ❌ | +2.2% / 46% / 70t  | -3.2% / 8% / 25t ❌ | +0.0% / 48% / 117t  | -1.7% / 33% / 9t  |

### 30-day window — all strategies pooled

| Sector | Trades | Win rate | Avg ret | Median | PF | t-stat | Open (MTM) | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| ENERGY | 284 | 69.0% | +1.61% | +1.07% | 2.99 | +6.1 | 27% | **WIN** |
| HEALTHCARE | 744 | 59.0% | +1.09% | +0.86% | 1.63 | +3.2 | 21% | **WIN** |
| MATERIALS | 270 | 52.6% | +0.36% | +0.36% | 1.17 | +0.8 | 21% | mixed |
| FINANCIALS | 1099 | 57.0% | +0.09% | +0.36% | 1.09 | +0.9 | 11% | mixed |
| TECHNOLOGY | 517 | 56.9% | -0.03% | +0.50% | 0.99 | -0.1 | 19% | weak |
| UNKNOWN | 451 | 43.7% | -0.24% | -0.09% | 0.61 | -3.2 | 23% | **LOSE** |
| REAL_ESTATE | 267 | 45.7% | -0.55% | -0.13% | 0.57 | -3.0 | 20% | **LOSE** |
| UTILITIES | 83 | 54.2% | -0.76% | +0.20% | 0.45 | -1.7 | 7% | weak |
| COMMUNICATION | 229 | 50.7% | -0.85% | +0.01% | 0.56 | -2.9 | 20% | **LOSE** |
| CONSUMER_STAPLES | 189 | 50.3% | -0.87% | +0.00% | 0.54 | -3.0 | 24% | **LOSE** |
| CONSUMER_DISCRETIONARY | 375 | 44.8% | -1.38% | -0.48% | 0.48 | -4.2 | 16% | **LOSE** |
| INDUSTRIALS | 736 | 46.2% | -1.61% | -0.29% | 0.44 | -7.2 | 11% | **LOSE** |

### 30-day window — strategy × sector (avg return, WR, trades)

| Strategy | COMMUNICATION | CONS_DISCRETIONARY | CONS_STAPLES | ENERGY | FINANCIALS | HEALTHCARE | INDUSTRIALS | MATERIALS | REAL_ESTATE | TECHNOLOGY | UTILITIES |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MR_V3 | – | – | -2.2% / 20% / 5t  | +5.2% / 75% / 8t  | +1.1% / 61% / 18t  | +5.7% / 75% / 8t  | -1.6% / 43% / 7t  | +2.6% / 62% / 8t  | -0.6% / 40% / 10t  | – | – |
| MR_V24 | -3.1% / 17% / 12t  | -3.5% / 33% / 27t ❌ | -0.7% / 42% / 12t  | +4.4% / 83% / 29t ✅ | +1.9% / 68% / 71t ✅ | +1.6% / 55% / 51t  | -1.2% / 44% / 41t  | +0.1% / 60% / 15t  | -2.9% / 12% / 8t  | +1.3% / 53% / 32t  | – |
| MR_CONNORS | -0.4% / 56% / 176t  | -1.0% / 48% / 297t ❌ | -0.7% / 55% / 152t ❌ | +1.1% / 69% / 193t ✅ | +0.0% / 58% / 936t  | +1.4% / 66% / 523t ✅ | -1.2% / 49% / 591t ❌ | +0.2% / 56% / 179t  | -0.3% / 48% / 238t ❌ | +0.5% / 61% / 393t  | -0.7% / 56% / 75t  |
| MOM_V3 | -2.3% / 50% / 6t  | -1.1% / 33% / 9t  | -4.0% / 20% / 5t  | +6.4% / 67% / 6t  | -0.8% / 23% / 13t  | -2.4% / 20% / 15t  | -6.7% / 29% / 14t  | -6.1% / 0% / 7t  | – | -5.7% / 50% / 10t  | – |
| MOM_STRICT | -5.8% / 17% / 6t  | -5.2% / 29% / 7t  | – | +2.2% / 71% / 17t  | -8.6% / 0% / 6t  | -1.1% / 34% / 38t  | -5.1% / 27% / 22t ❌ | -7.8% / 0% / 8t  | – | -4.5% / 24% / 17t ❌ | – |
| BREAKOUT | -2.1% / 36% / 25t  | -2.1% / 30% / 33t  | -1.1% / 33% / 15t  | -0.1% / 55% / 31t  | -0.2% / 38% / 55t  | +0.4% / 41% / 109t  | -2.9% / 36% / 61t ❌ | +2.8% / 51% / 53t  | -4.2% / 14% / 7t  | -2.1% / 40% / 63t ❌ | – |

## 5b. Month by month (signal month, live exits, marked-to-market)

| Strategy | 2026-06 | 2026-07 | 2026-08 | 2026-09 |
|---|---:|---:|---:|---:|
| MR_V3 | +6.09% / 59% / 1496t | +1.26% / 53% / 255t | +1.15% / 54% / 88t | +3.56% / 100% / 2t |
| MR_V24 | +3.00% / 68% / 340t | +0.76% / 56% / 326t | +0.77% / 56% / 335t | -0.24% / 42% / 36t |
| MR_CONNORS | +0.22% / 60% / 2499t | +0.16% / 62% / 4085t | -0.07% / 56% / 3936t | +0.51% / 58% / 386t |
| MOM_V3 | +0.09% / 53% / 841t | +1.07% / 53% / 270t | -2.93% / 33% / 112t | +0.31% / 50% / 6t |
| MOM_STRICT | -0.62% / 35% / 206t | -1.18% / 31% / 88t | -3.57% / 27% / 126t | +1.20% / 71% / 14t |
| BREAKOUT | +0.38% / 42% / 731t | -0.78% / 32% / 449t | -0.70% / 38% / 540t | -0.20% / 42% / 48t |

### Volatility of the stock at signal (ATR(14)% bucket), 90-day window

| Strategy | ATR 3-5% | ATR 5-8% | ATR >8% |
|---|---|---|---|
| MR_V3 | 1202t, 61% WR, +5.59% **WIN** | 456t, 59% WR, +9.75% **WIN** | 183t, 32% WR, -8.85% **LOSE** |
| MR_V24 | 863t, 62% WR, +1.55% **WIN** | 148t, 50% WR, +1.58% mixed | 26t, 38% WR, -2.17% weak |
| MR_CONNORS | 8748t, 60% WR, +0.16% mixed | 1609t, 59% WR, +0.38% mixed | 549t, 49% WR, -1.64% **LOSE** |
| MOM_V3 | 978t, 54% WR, +1.66% mixed | 199t, 43% WR, -2.12% weak | 52t, 17% WR, -22.41% **LOSE** |
| MOM_STRICT | 265t, 36% WR, -1.03% weak | 138t, 31% WR, -1.35% weak | 31t, 19% WR, -6.60% **LOSE** |
| BREAKOUT | 1419t, 38% WR, -0.23% weak | 327t, 43% WR, +0.32% mixed | 22t, 14% WR, -11.48% **LOSE** |

MR_V3 concentration check: on its biggest signal day (2026-06-08) it fired 551 trades (+7.96% avg, 62% WR); all other days: 1290 trades, +4.00% avg, 56% WR, t=+7.0.

MR_V3 by RSI(2) depth (90d): RSI(2) 0-5: 117t, 60% WR, +6.82%; RSI(2) 5-10: 158t, 58% WR, +2.46%; RSI(2)=0: 1566t, 58% WR, +5.34%

## 6. Which exit worked for each entry (90-day window, marked-to-market)

| Entry | Fixed5d | Fixed10d | Fixed14d | Fixed21d | Fixed60d | Fixed90d | SMA5 | RSI65 | SMA10 | TRAIL10 | Best exit |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MR_V3 | +0.89% / 55% | +0.86% / 53% | +1.39% / 53% | +2.59% / 56% | +5.19% / 58%★ | +5.11% / 58% | +0.40% / 62% | +0.36% / 62% | -0.06% / 43% | +0.06% / 44% | Fixed60d (+5.19%, PF 1.85) |
| MR_V24 | +0.98% / 55% | +1.41% / 57% | +1.46% / 59%★ | +1.60% / 57% | +2.05% / 57% | +2.05% / 57% | +0.51% / 63% | +0.47% / 62% | +0.26% / 45% | +1.11% / 44% | Fixed60d (+2.05%, PF 1.60) |
| MR_CONNORS | +0.40% / 53% | +0.16% / 51% | +0.33% / 51% | +0.98% / 54% | +1.74% / 54% | +1.78% / 54% | +0.10% / 59%★ | +0.08% / 58% | -0.31% / 39% | -0.19% / 40% | Fixed90d (+1.78%, PF 1.33) |
| MOM_V3 | -0.40% / 46% | -0.44% / 48% | -0.28% / 48% | -0.28% / 50% | -0.11% / 50% | +0.03% / 51%★ | -0.20% / 52% | -0.16% / 55% | -0.73% / 34% | -0.52% / 35% | Fixed90d (+0.03%, PF 1.00) |
| MOM_STRICT | -0.32% / 49% | -1.57% / 46% | -1.98% / 42% | -2.70% / 40% | -2.80% / 41% | -2.74% / 41% | +0.34% / 54% | +0.18% / 59% | -1.05% / 37% | -1.53% / 33%★ | SMA5 (+0.34%, PF 1.17) |
| BREAKOUT | +0.45% / 50% | +0.17% / 50% | +0.30% / 51% | +0.35% / 50% | +0.65% / 51% | +0.67% / 51% | +0.18% / 48% | +0.39% / 59% | -0.26% / 39%★ | +0.31% / 42% | Fixed90d (+0.67%, PF 1.13) |

★ = the exit the live system / documented model uses. Closed-only version of this grid is in results.json (`grid_entry_exit_closed_only`).

## 7. Verdict — what clearly won and what clearly lost

**Strategies that won in every window they had enough trades in:**

- none

**Strategies that clearly lost in at least one window:**

- **MOM_V3**: 30d **LOSE**, 60d mixed, 90d mixed
- **MOM_STRICT**: 30d **LOSE**, 60d **LOSE**, 90d **LOSE**
- **BREAKOUT**: 30d weak, 60d **LOSE**, 90d weak

**Sectors (all strategies pooled, 90d):** HEALTHCARE +3.97% (2484t) **WIN**, ENERGY +2.95% (977t) **WIN**, FINANCIALS +1.69% (3306t) **WIN**, MATERIALS +0.48% (807t) mixed, CONSUMER_STAPLES +0.11% (641t) mixed, CONSUMER_DISCRETIONARY -0.33% (1400t) weak, COMMUNICATION -0.34% (724t) weak, REAL_ESTATE -0.60% (912t) **LOSE**, TECHNOLOGY -0.79% (1499t) **LOSE**, UTILITIES -0.92% (387t) **LOSE**, INDUSTRIALS -1.67% (2729t) **LOSE**

**Regimes (90d, live combos):** MR_V3 in HEALTHY: +6.57% / 61% WR / 1441t **WIN**; MOM_V3 in DIP_BUY: +3.98% / 61% WR / 114t **WIN**; MOM_STRICT in DIP_BUY: +3.08% / 41% WR / 29t mixed; MR_V3 in PULLBACK: +2.24% / 51% WR / 49t mixed; MR_V24 in HEALTHY: +2.06% / 62% WR / 805t **WIN**; MR_CONNORS in DIP_BUY: +1.71% / 69% WR / 628t **WIN**; BREAKOUT in DIP_BUY: +1.51% / 58% WR / 135t **WIN**; MR_CONNORS in PULLBACK: +0.13% / 63% WR / 1714t mixed; MR_CONNORS in HEALTHY: -0.02% / 57% WR / 8564t weak; MR_V3 in DIP_BUY: -0.08% / 45% WR / 351t weak; MOM_V3 in PULLBACK: -0.11% / 47% WR / 93t weak; BREAKOUT in PULLBACK: -0.16% / 35% WR / 509t weak; MR_V24 in PULLBACK: -0.25% / 52% WR / 167t weak; MOM_V3 in HEALTHY: -0.40% / 50% WR / 1022t weak; BREAKOUT in HEALTHY: -0.52% / 38% WR / 1124t **LOSE**; MOM_STRICT in PULLBACK: -0.96% / 34% WR / 79t weak; MR_V24 in DIP_BUY: -1.49% / 45% WR / 65t weak; MOM_STRICT in HEALTHY: -2.08% / 32% WR / 326t **LOSE**

## 8. QA performed and caveats

- Indicator math (RSI(2) simple-average, SMA, ATR%) matched `backtest_precompute.py` to 1e-9 on sampled tickers; MR_V3 full-history replay reproduced the precompute trade count exactly.
- Six random trades were re-derived by hand from raw DB prices (entry open, exit close, fee): all matched to 4 decimals.
- Zero duplicate and zero overlapping trades per ticker/rule. Series not reaching the end date are excluded (2 universe tickers returned 404 from Tiingo).
- Look-ahead: all entry conditions use bars ≤ signal day; execution is the next bar's open; exits use closes strictly after entry.
- Concentration risk: **551 of the MR_V3 signals in the 90-day window fired on one day (2026-06-08 selloff)**, so MR_V3's 90-day result is largely one dip-buy event, not 60 independent days of evidence.
- Time-exit strategies (Fixed60d/90d) cannot complete inside a 30/60-day window; their rows are marked-to-market and the "Open" column says how much.
- Universe is the repo's Feb-2026 list (survivorship: names delisted since are excluded; names listed since are not included). No earnings or sentiment veto is applied.
- Only HEALTHY / DIP_BUY / PULLBACK (BULL / SIDEWAYS) regimes occurred; conclusions do not transfer to bear or high-VIX regimes.
