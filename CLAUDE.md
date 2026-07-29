# SuperApp Trading Assistant

## Core Rules
- **PRIMARY GOAL**: MAXIMIZE ROI (3% monthly is MINIMUM, not target)
- **RULE**: When saying SELL, ALWAYS say what to BUY
- **MODEL**: Production runs **ATLAS V2.7 (MR entries) + V3.0 (cache-accelerated evaluator) + V3.3 (regime-adaptive entry sizing, 2026-06-12) + V3.4 (Buffered WR scoring, 2026-06-16) + V3.5 (Entries tab sorts by composite_score, not Buffered WR, 2026-06-18) + V3.6 (Fixed42d MR/BOTH exit, 2026-07-22 — replaces V3.4 Fixed60d after a 17-window rolling walk-forward on clean Tiingo data: Fixed42 won 8/17 windows, +30.8% compounded vs Fixed60 -26.1%, smaller worst-window; DEPLOYED + verified live)**. There is no single "version" — the deployed code is a hybrid. See "Active Strategy" section below for the actual rules.
- **VALIDATION**: NEVER recommend without backtest validation (WR > 55%, 10+ trades)
- **LIVE DATA**: NEVER suggest buy without verifying live prices first (MANDATORY)
- **SENTIMENT**: ALWAYS check news sentiment before any buy recommendation (informational; not a hard veto for MR — see VETO chain below)
- **SCAN SIZE**: Scan at least 1,000 stocks before making buy recommendations
- **BACKTEST FIRST**: ALWAYS run backtest on ALL positions BEFORE showing any projections or recommendations (MANDATORY)
- **NO FAKE PROJECTIONS**: NEVER show projected returns without actual backtest data to back it up
- **VERIFY BEFORE SPEAKING**: NEVER tell user any data before checking it deeply first (MANDATORY)
- **RSI ZONE ANALYSIS — RETIRED 2026-07-04**: Per-stock zone expectations are UNCALIBRATED NOISE. Calibration test (5,481 point-in-time samples, `_zonecalib_bt.py`): Spearman IC ≈ 0.00 predicted-vs-realized; stocks "predicting" +20% realized +3.4%, stocks "predicting" negative realized +1.7% — everything converges to the strategy base rate (~+2-4%/60d). Do NOT base hold/sell/size decisions on per-stock zone returns. The behavioral rule that survives (for validated reasons): don't sell overbought winners — hold to the Fixed60d timer.
- **BE CONFIDENT**: Don't ask user for permission when data supports a decision - act on it
- **SCAN FOR BETTER**: Before recommending ANY buy, ALWAYS scan 1,000+ stocks for better alternatives. Don't default to existing holdings - find the BEST opportunity (MANDATORY)
- **PORTFOLIO BALANCE**: When recommending BUY/SELL, ALWAYS consider total portfolio spread. Target ~20% per position, no single stock >30%. Size new buys to rebalance underweight positions. Don't create new overweight positions (MANDATORY)
- **EARNINGS CALENDAR**: ALWAYS check earnings calendar (Finnhub) before ANY buy recommendation. VETO any stock with earnings within 7 days. Also check portfolio holdings for upcoming earnings and WARN user. Use `python3 deep_scanner.py` which has built-in earnings VETO (MANDATORY)
- **WEIGHTED ALLOCATION — RETIRED 2026-07-04**: "Weight capital by zone expected return" allocated on noise (zone IC ≈ 0, see RSI ZONE ANALYSIS above). Use roughly equal sizing across validated entries, ranked by composite_score (the validated sort key). Respect the 20%/30% position caps.
- **TRUST BACKTESTS**: If backtests are valid (WR > 55%, 10+ trades, zone trades >= 5), trust the data regardless of stock price. Only filter penny stocks under $10 (MR scanner cap). Momentum scanner caps at $200.
- **EXIT TRIGGERS (UPDATED 2026-06-17, V3.4)**: Hold positions until backtested per-strategy exit triggers — **Fixed60d** for MR / BOTH (exit on trading day 60; replaced Fixed30d after honest 13-window rolling walk-forward — 24mo IS / 6mo OOS / 6mo step, 17,108 PROD-filtered entries, 487-ticker quarantine). Fixed60d portfolio sim N=4 OOS-2024: +23.2% CAGR / 2.09% monthly / MDD -11.6% / Sharpe 0.78 vs Fixed30d N=4: +6.3% CAGR / 1.04% monthly / MDD -35% / Sharpe 0.59. Cross-period worst-month: Fixed60d +0.94% (never negative) vs Fixed30d -0.18%. Dynamic regime-aware exits (HonestDyn family) were tested honestly and beaten by Fixed60d once portfolio capacity constraints applied. **Fixed90d** for Momentum (unchanged). Valid early exits: (a) Earnings within 7 days — binary event risk, always EXIT. (b) Stock-specific negative sentiment (downgrade, earnings miss, product failure) — EXIT. (c) Model EXIT signal (both ATLAS WR + zone WR fail 65%) — EXIT. NOT valid: market-wide crash headlines, war panic across all stocks, RSI rising (trade working). Distinguish STOCK-SPECIFIC bad news from MARKET-WIDE noise. (MANDATORY)
- **REGIME-ADAPTIVE ENTRIES (UPDATED 2026-06-12, V3.3)**: Per 35K-trade paired backtest + walk-forward validation (train pre-2022, test 2022+), entry rules adjust by regime: **DANGER (SPY -7% to -15% drawdown) → PAUSE all entries** (was -10% to -15%; widened after CORRECTION regime showed 49% WR / +0.22% avg — below threshold). **SHARP_DROP (SPY 5d < -2%) → 70% size** (still +2.27% avg / 57% WR). All other regimes unchanged. "A skip CORRECTION" returned +2.10%/trade out-of-sample vs +1.18% baseline (+78% cumulative). Dual-bucket "defensive RSI<10" approach was tested and REJECTED — Bucket A (high-vol MR) beat Bucket B and C in every regime including CRISIS. (MANDATORY)

---

## Current Positions (Updated 2026-06-17, reconciled to PRODUCTION API — source of truth)

> The local positions.db and this file had both drifted ~6 weeks stale (showed an April PRAX/GHM/AMSC/CAMT/APEI/IREN set). Reconciled to the live production portfolio (`superapp-ke5bhg.fly.dev/api/v2/portfolio`, the frontend source) on 2026-06-17. The April set was CLOSED; deposits grew to $20,907.

### USD Portfolio (live 2026-06-17)

| Ticker | Shares | Avg Entry | Cost Basis | Current | Value | P&L | Weight | Days | RSI2 |
|--------|--------|-----------|------------|---------|-------|-----|--------|------|------|
| NVDA | 15.2646 | $197.45 | $3,014.00 | $207.23 | $3,163.6 | +$149 (+5.0%) | 18.5% | 30 | 59 |
| SFM | 37.8924 | $79.17 | $2,999.94 | $80.72 | $3,058.7 | +$59 (+2.0%) | 17.9% | 29 | 0 |
| BE | 10.1786 | $294.73 | $2,999.94 | $290.90 | $2,961.0 | -$39 (-1.3%) | 17.4% | 15 | 100 |
| CLS | 5.5429 | $377.23 | $2,090.95 | $387.49 | $2,147.6 | +$57 (+2.7%) | 12.6% | 28 | 32 |
| CELC | 22.5773 | $132.88 | $3,000.07 | $87.62 | $1,978.4 | -$1,022 (-34.1%) | 11.6% | 28 | 0 |
| DAC | 14.8286 | $128.00 | $1,898.06 | $127.49 | $1,890.5 | -$8 (-0.4%) | 11.1% | 15 | 1 |
| APP | 3.7902 | $568.83 | $2,155.98 | $491.98 | $1,864.7 | -$291 (-13.5%) | 10.9% | 10 | 81 |

**Cash: $4,302.75 | Positions Value: ~$17,064 | Total Portfolio: ~$21,367**
**Total Deposited: $20,907.44 | Realized P&L: +$1,967.68 | Total Fees: $110 | Total Tax: $317**
**Open P&L: -$1,094.80 (-6.03%) — drag is CELC (-$1,022, sell-the-news + convertible dilution; thesis intact)**

### Exit status (Fixed60d, all entered May–June → none at day 60 yet)
- No holding has earnings within 7 days (verified vs Finnhub calendar 2026-06-17 — portfolio_check/scanner news-based earnings detector is throwing false positives on ALL tickers; do not trust it).
- No stock-specific negative-sentiment exit: all 7 hold POSITIVE sentiment.
- NVDA prod UI shows "EXIT NOW" = stale Fixed30d logic (prod not yet redeployed to V3.4 Fixed60d). Under Fixed60d it HOLDS to day 60.

### ILS Portfolio
- **SOLD** TA-35 3x ETF on 2026-02-10 for ~+2,871 ILS profit (+14.5%)
- LUMI.TA: ~10,000 ILS position (entered 2026-02-17)
- Waiting for TA-35 pullback to ~4,000 to re-enter (RSI < 35 entry signal)

---

## Transaction History (Broker-Verified from Blink PDF)

### Deposits
| Date | Amount |
|------|--------|
| 2026-01-04 | $1,500.00 |
| 2026-01-07 | $1,500.00 |
| 2026-01-08 | $200.00 |
| 2026-01-15 | $500.00 |
| 2026-01-30 | $1,500.21 |
| 2026-02-13 | $3,213.37 |
| **Total** | **$8,413.58** |

### Closed Trades (Chronological)
| Ticker | Entry | Exit | Cost | Proceeds | P&L | P&L% |
|--------|-------|------|------|----------|-----|------|
| MRVL | 01-07 | 01-14 | $778.50 | $715.41 | -$63.09 | -8.1% |
| VST | 01-07 | 01-20 | $1,340.34 | $1,276.66 | -$63.68 | -4.8% |
| LLY | 01-07 | 01-20 | $1,080.50 | $1,030.80 | -$49.70 | -4.6% |
| COIN | 01-14 | 01-20 | $715.99 | $644.54 | -$71.45 | -10.0% |
| QQQ | 01-15 | 02-10 | $1,466.98 | $1,464.53 | -$2.45 | -0.2% |
| MU | 01-20 | 02-04 | $1,258.99 | $1,185.63 | -$73.36 | -5.8% |
| NVDA | 01-20 | 02-04 | $1,019.99 | $978.10 | -$41.89 | -4.1% |
| SLB | 01-30 | 02-05 | $1,293.99 | $1,328.14 | +$34.15 | +2.6% |
| SYK | 02-04 | 02-06 | $1,091.98 | $1,073.56 | -$18.42 | -1.7% |
| SPG | 02-04 | 02-06 | $975.99 | $992.55 | +$16.56 | +1.7% |
| NEM | 02-05 | 02-06 | $665.00 | $662.48 | -$2.52 | -0.4% |
| LRCX | 02-05 | 02-13 | $1,002.98 | $1,079.34 | +$76.36 | +7.6% |
| LIN | 02-06 | 02-10 | $999.97 | $1,022.31 | +$22.34 | +2.2% |
| ALB | 02-06 | 02-18 | $1,933.99 | $2,033.05 | +$99.06 | +5.1% |
| GOOGL | 02-10 | 02-12 | $1,020.99 | $994.72 | -$26.27 | -2.6% |
| VRT | 02-10 | 02-11 | $1,461.99 | $1,775.54 | +$313.55 | +21.4% |
| COHR | 02-11 | 02-23 | $3,053.96 | $3,447.88 | +$393.92 | +12.9% |
| JOUT | 02-13 | 02-18 | $498.00 | $499.61 | +$1.61 | +0.3% |
| CMC | 02-18 | 02-19 | $1,329.99 | $1,316.96 | -$13.03 | -1.0% |
| **TOTAL** | | | | | **+$531.65** | |

**Wins: 8 | Losses: 12 | Win Rate: 40% | Total Fees: $63.01 | Dividend: $0.40**

---

## Active Strategy — V2.7 / V3.0 / V3.3 / V3.4 hybrid (verified 2026-06-17)

**Locations**:
- Entry/scoring: `backend/strategy_evaluator.py`, `backend/deep_scanner.py`, `backend/momentum_scanner.py`
- Exits: `backend/api_v2.py:_select_best_exit` (Fixed60d for MR / BOTH — V3.4, Fixed90d for MOM)
- Regime gate: `backend/api_v2.py:_check_market_regime`
- Signal tracker: `backend/signal_tracker_update.py` + `signal_tracker_loop` (daily snapshot of top-20 + forward-return backfill)
- Live API: `backend/api_v2.py` (28 routes)

There is no longer a single "atlas v2 model" file driving production. `backend/atlas_v2/entry.py` exists and exposes `EntryEngine`, but the live scan path is `strategy_evaluator.evaluate_all` → `_dict_to_opportunity`. Treat `atlas_v2/__init__.py:__version__ = "2.0.0"` as stale.

### Mean Reversion entry rule (live)
```
REQUIRED:  Price > SMA(50)
           RSI(2) < 10
           ATR(14)% >= 3%       (volatility floor — #1 predictor of big winners)
           Price >= $10         (penny filter)
           SMA50 buffer >= 5%   (#2 predictor)
           Volume >= 1.0×       (no longer 1.5×)
           RSI(14) < 60
```

### Momentum entry rule (live, `momentum_scanner.py`)
- Minervini 6/6 trend template
- 20-day return > 5%
- Parabolic-spike VETO (>=10% gap)
- 5-day return > 15% VETO
- Price >= $10 and **price <= $200** (research-backed cap; >$200 has -5% edge)

### VETO chain (the filters that actually block buys, `api_v2.py:_dict_to_opportunity`)
| Filter | Condition | Why it stayed |
|--------|-----------|---------------|
| Penny | Price < $10 | Volatility / liquidity |
| Volatility (NEW 2026-06-19) | ATR(14)% >= 15% | 29% WR / -12.6% avg on 32K-trade validation — worst cohort, no tail benefit. Was a soft -5pt composite penalty; now a hard veto. |
| Earnings | <= 7 days to next earnings | Binary event risk |
| Analyst | Consensus = Hold/Sell/Underperform/Strong Sell | +1.19% edge in backtest |
| Correlation | Holdings correlation > 0.7 | Concentration risk |

**Removed 2026-04-24** because backtests showed they REJECTED higher-return signals on average:
- Analyst target (price > target): -0.40% edge → REMOVED
- Sentiment score < -0.3 in MR scanner: -0.43% edge → REMOVED (still active in `momentum_scanner.py:232` and `atlas_v2/entry.py:423` — inconsistent enforcement, see Known drift below)
- Zone WR < 65% / zone trades < 5 / score < 3.0 / avg_return < 3%: documented but currently NOT enforced as hard vetoes — they are ranking factors only. Tier labels (TIER1/TIER2/TIER3) are display-only.

### Entries-tab sort key (V3.5 composite_score, 2026-06-18) — **PRIMARY SORT KEY**
- **The Entries tab sorts by `composite_score`** (`_compute_composite_score` in `api_v2.py`), tiebroken by Buffered WR. Changed from Buffered-WR sort on 2026-06-18 after a head-to-head walk-forward — see `backend/_rank_backtest.py`.
- **Why** (point-in-time walk-forward, 299 anchors, 7,172 PROD-gated signals, 2017-2026, Fixed60d forward return, no lookahead — BWR recomputed per-anchor from only trades closed before the anchor):
  - Top-1 fwd 60d: **composite +4.02% vs BWR +1.03%** (OOS +5.76% vs +2.06%)
  - Top-3 fwd 60d: **composite +4.43% vs BWR +2.79%** (OOS +5.77% vs +3.56%)
  - Top-5 fwd 60d: **composite +4.07% vs BWR +2.51%** (paired t=+2.15)
  - Spearman IC: composite +0.014 vs BWR +0.006 (OOS +0.022 vs +0.005)
- **Honest caveat**: median anchor is a wash (win-counts 137 vs 135); composite's edge is tail-driven — it surfaces the high-ATR / BOTH-bonus winners, which is exactly what a top-1-to-3 concentrated book captures. Live composite also gets real analyst consensus (+1.19% edge) the backtest replica lacked, so the live edge is likely larger.
- **No contradiction with the old BWR validation**: BWR's "+11.50% vs +5.50%" win was vs **EV-classic** (already dropped from composite), never vs composite.
- **Frontend**: `OpportunitiesTab.tsx` sorts `unified` by `composite_score`; headline number shows composite ("Score 65 · BWR 54") so number + tier badge + sort order all agree.

### Buffered WR — now a secondary/tiebreak stat (V3.4, 2026-06-16)
- **Formula**: `score = bayesian_wr - (std / sqrt(n))` per strategy; computed in `backtest_precompute.py`, stored in `backtest_cache.mr_score` / `mom_score`, surfaced as `combined.score`.
- Still displayed per row and used as the sort tiebreaker. Beat EV-classic in its own validation (527 signals × 9yr: full +11.50% vs +5.50% CAGR; OOS +4.80% vs -6.50%) — but was beaten by composite as the sort key (above).

### Legacy: `api_v2.py:_ev_score` (still used for holdings rotation comparison)
- Bayesian-shrunk: `zone_ret_shrunk × zone_wr_shrunk / 100` for MR, momentum-zone equivalent for MOM
- Shrinkage priors: `PRIOR_RET = 2.85`, `PRIOR_WEIGHT = 20`
- Fallback to avg_return × WR if zone_trades < 5

### Exit Strategy (live V3.4, per-strategy)
| Strategy | Exit | File:line |
|----------|------|-----------|
| Mean Reversion / BOTH | **Fixed42d** (V3.6, DEPLOYED + verified live 2026-07-22) — exit on trading day 42. Replaced Fixed60d after a 17-window rolling walk-forward on clean Tiingo data: Fixed42 won 8/17 windows, +30.8% compounded vs Fixed60 -26.1%, smaller worst-window (-31% vs -44%). 60d holds trap portfolio slots for the slow drift tail. Wired in `_select_best_exit` (label+42d), `_EXIT_STRATEGIES["Fixed42d"]`, the portfolio-endpoint `exit_strat_name`/live `expected_exit_strat`, `/analyze` `_HOLD=42`, `backtest_precompute.MR_HOLD_DAYS=42`, and frontend PositionsTable countdowns. | `api_v2.py:_select_best_exit` |
| Momentum | **Fixed90d** | `api_v2.py:_EXIT_STRATEGIES` |
| Stop loss | None — research confirms stops HURT mean reversion | — |
| Profit target | None — let fixed timer fire | — |

The file `backend/data/exit_strategy_validated.json` exists but is empty `{}`. Per-stock optimal exit is computed on-the-fly in `_select_best_exit`, not loaded from JSON. Don't trust documentation that references that JSON.

### Composite score (V3.2, post 2026-06-02 patches)
Multi-factor 0-100 ranking computed in `_compute_composite_score`. After audits stripped EV/WR ramps (anti-predictive OOS), the active weights are:

| Factor | Weight | Why |
|---|---|---|
| ATR% | up to 40 pts; ATR>=15 now HARD-VETOED (2026-06-19) | Per-trade WR/return sweet spot is 4-8% (8-10% is a WR trough), BUT a top-10 ranking A/B (`_composite_ab_test.py`) showed demoting 8-15% LOWERS realized ROI — the edge is tail/skew-driven and the tail lives in high ATR, so high-ATR weights are kept. Only the catastrophic >=15% band (29% WR / -12.6%) is removed. |
| Analyst consensus | 15 pts | +1.19% edge on 95K signals |
| BOTH-strategy bonus (NEW 2026-06-02) | 0-12 pts | ret_20d>5% + atr>=4 → BOTH cohort (+4.14%/trd in 10yr study) |
| Sentiment score | 10 pts | informational |
| Volume ratio (U-shape) | 0-10 pts | reward <0.5 OR 1.0-1.5; penalize "uncommitted" 0.5-1.0 |
| Price tier | 10 pts | $10-25 sweet spot |
| RSI(2) depth, SMA50 buffer | 5 pts | minor |

### Backtest invariants
- Next-day open entry (no same-bar lookahead) — verified in `deep_scanner.py:378`, `backtest_precompute.py:131,192`
- 0.30% fee deduction per trade
- RSI(2) < 10 filter at entry (NOT < 50, which was a past bug)
- 60 trading days hold for MR/BOTH (`Fixed60d` — V3.4 since 2026-06-17), 90 for MOM (`Fixed90d`); both weekday-counted in positions.py + api_v2.py
- backtest_cache uses MR_HOLD_DAYS=60 + MOM_HOLD_DAYS=90 — now matches the live exit (cache and exit both answer the same question after the V3.4 switch)

### Market regime gate (`api_v2.py:_check_market_regime`)
Drawdown- and SMA-based. Pauses entries when stocks won't reliably mean-revert.
| Regime | Trigger | Action |
|--------|---------|--------|
| DANGER | -15% <= SPY drawdown <= -7% (V3.3 widened from -10%) | PAUSE all entries |
| CRISIS | VIX > 40 | PAUSE all entries |
| WEAK | SPY 0% to -2% below SMA200 | PAUSE MR only (momentum still works); 50% size |
| CORRECTION | -20% <= SPY drawdown < -15% | 50% size |
| BEAR_BOUNCE | SPY drawdown < -20% | FULL size (best regime for MR) |
| BELOW_SMA200 | SPY > 2% below SMA200 | FULL size |
| PULLBACK | SPY below SMA50 (above SMA200) | FULL size |
| DIP_BUY | -7% < SPY drawdown <= -3% (V3.3 narrowed from -10%) | FULL size |
| SHARP_DROP | SPY 5d return < -2% (V3.3 new tier) | 70% size, entries OK |
| FEAR | VIX > 30 | 50% size |
| HEALTHY | otherwise | 70% size |

The `pause_mr` flag is wired in `/api/v2/scan/combined` to filter MR signals when WEAK fires.

### Fixed in 2026-06-19 full-system QA
- **Universe staleness (CRITICAL)**: `data_cache.get_stale_tickers`/`is_fresh` now key on `data_end` (latest bar), not `last_updated` (refresh-touch timestamp) — the bug that hid genuinely-oversold names by leaving their bars stale while flagged fresh. AND `_newest_bar_date` now excludes VIX (Yahoo intraday bar = today) + crypto (`*USD`, 7-day week) so they don't poison the equity baseline and flag the whole universe stale → refresh storms.
- **Phantom-oversold (HIGH)**: `quote_refresh_loop` no longer falls back to `prevClose` as a "live" price (mirrors `_fetch_tiingo_iex_batch`); `_fresh_live_px()` + live-overlay `ts` guard.
- **WR-gate bypass (HIGH)**: `_dict_to_opportunity` now vetoes `<10 trades` (was a free pass); `_meets_strict_criteria` trades floor 6→10.
- **Zone-stat bias (HIGH)**: `deep_scanner` zone-return loop now applies the same ATR≥3 + price≥10 filters as the tradable cohort.
- **KPICards (HIGH)**: `spy_5d_return` null-guarded; regime label/color now driven by `pause_entries`/`position_size_pct` + the actual emitted regime name (DANGER/CRISIS now correctly show "ENTRIES PAUSED"; the never-emitted BEAR/DECLINING/CAUTION branches removed).
- **Robustness**: atomic `save_cache` (tmp+os.replace, no half-written JSON); `busy_timeout=5000` on all `positions.py` connections; bounded (900s) subsequent-run cache refresh.
- **Stale-DOC items confirmed ALREADY FIXED in code** (do not "re-fix"): sentiment veto is removed in momentum_scanner + atlas_v2 (informational only); `atlas_v2/__init__.py` is `2.7.0` not `2.0.0`; `backtest_cache` is refreshed when >24h old (not weekly).

### Exit-logic items RESOLVED in 2026-06-19 QA (backtested where behavior changed)
- **MR trailing-stop override REMOVED** (`_evaluate_exit_trigger`): the 8%-trailing override is now gated to `strategy=="Fixed90d"` (momentum only). A 32,607-trade backtest (`_exit_policy_bt.py`) proved it HURTS MR — cuts the median affected trade -3.0% (5,649 worse vs 3,147 better), OOS median +0.20%→-0.22%, OOS WR 51%→49%; only a tail-driven mean bump. Confirms "stops hurt mean reversion." MR/BOTH now let the Fixed60d timer fire.
- **`_select_best_exit` is now strategy-aware**: Fixed90d/90-day hold for MOMENTUM, Fixed60d/60 for MR/BOTH; cache key includes strategy (was returning the MR result for MOM positions). The 2nd held-position endpoint now passes the position strategy + uses the right target_hold_days (90 for MOM).
- **Off-by-one fixed**: `_select_best_exit` now holds `ed+hold` bars (was `ed+hold-1`), matching the live timer + precompute cache.
- **Earnings<7d exit WIRED** into the live holdings exit ladder (Priority 2) using the forward Finnhub/Tiingo calendar (`next_earnings_map`), NOT the false-positive news detector. The documented "always EXIT on earnings <7d" rule now actually fires.
- **2nd-endpoint `days_held`** now weekday-counted (was calendar — ran the days-remaining counter ~40% fast).
- Note: `_is_true_bear` bear-exit branches remain inert (regime never emits "BEAR") — left inert intentionally; activating panic-sells would contradict the "don't sell into market-wide crashes" strategy.

### Hold-vs-exit mega-validation (2026-06-20 → 07-04, all point-in-time, IS+OOS)
Every early-exit / rotation idea was backtested against HOLD-to-Fixed60d-timer on PROD-gated entries. **HOLD won every time:**
| Policy tested | Result vs HOLD |
|---|---|
| Composite rotation (gap>15, live ROTATE logic) | −13 to −24 CAGR pts ($114k vs $16.5k on $10k, 2017-2026) |
| Rotate losers-only variants | all lose (best still −60% of final equity) |
| Model-EXIT (WR<65 both zones) | −2.5pp/trade on the flagged cohort (OOS −1.9pp) |
| Exit on SMA50 break ("broken technicals") | −2.7pp/trade; 90% of MR entries break SMA50 mid-hold — that's the dip, not a broken thesis |
| Stop-loss −8% | hurts (22-39% WR exit cohorts) |
| Pace-rotation (cut behind-pace at day D, redeploy) | no robust winner; the one good combo (d21/−3%) is an isolated overfit spike — neighbors and N=7 all lose |
| Exit when current-zone expectation negative | HOLD wins by ~2.7pp at day 5/14/21 checkpoints (the "ARCB case") |
**Zone-expectation calibration (`_zonecalib_bt.py`, 5,481 samples): per-stock zone returns have IC ≈ 0.00 — pure noise.** Realized ≈ base rate (~+2-4%/60d) regardless of predicted. Raw zone numbers (e.g. "+37.5% expected") must not drive decisions or sizing; shrunk is only marginally better calibrated. **Valid exits remain ONLY: Fixed60d/90d timer, earnings <7d.**

### Exit-family study 2026-07-19 (`_exit_family_bt.py` + `_entry_variant_bt.py`, 7,322 PROD-gated MR signals 2017-2026, next-day-open, 0.6% RT fee, IS<2023/OOS 2023+)
- **WR vs hold-length is a structural trade, not a tuning problem.** Fixed60d WR is ~52-55% in EVERY entry variant tested (RSI2<5, RSI2<2, 2-3 consecutive down closes, cumRSI<20, 5d drop<-8%, buf≥10, ATR 5-12) — deeper oversold does NOT raise 60d WR. Short Connors-style exits (RSI2>75, cap 21d) give 64-70% WR / median +2% / ~6d holds, best in DIP regimes OOS (70.2% WR, +1.30%/trade, 0.23%/day — the best per-day cell in the whole grid), but per-trade profit is ~1/4 of Fixed60d's (+3.9% OOS).
- **Short exits do NOT compound at portfolio level**: in every N=5 sim (always-on idle=cash AND QQQ-core dip-only), rsi65/rsi75/sma5-cross/first-up-close underperform fixed timers badly (cut winners at +2%, losers still ride to cap; fee churn). Matches tracked `exit_strategy_study.py` (RSIexit_70/SMAcross_5 fell off leaderboard) and the deleted exit_study_v2 Connors tests. Literature agrees the bounce is 1-10d but its "recycle capital" case fails our capacity/fee reality.
- **Fixed42 beat Fixed60 in ALL FOUR portfolio-sim configurations** (always-on 2017: 4.0 vs 0.5% CAGR; always-on 2023+: ~9-20 vs 3.5-5.3%; QQQ-core dip-only 2017: 21.4 vs 8.2%; 2023+: ~18-20 vs 12-14%) despite lower per-trade avg — 60d holds trap slots. Offset spread is wide (path luck); needs the 13-window walk-forward harness before replacing Fixed60d. **Candidate V3.6: Fixed42d MR exit — VALIDATE FIRST.**
- **Regime dominates exit choice**: DIP-regime entries beat HEALTHY entries in every policy (OOS fixed60: +2.89 vs +4.48 avg is era-mixed, but WR/short-exit cells: DIP 70% vs HEALTHY 64%); the QQQ-core dip-only frame (DipRunner, 2026-07-11 audit) remains the architecture.
- Loser-only cuts (day-10/21 if <-5%) and partial scale-outs: no robust improvement (cut10w60 won one sim config, lost the OOS-era config — era-unstable, rejected). Confirms Alvarez: N-day loser stops are psychology, not edge.

### Alternative-strategy survey 2026-07-19 (`_alt_strategy_bt.py`, `_mom_rotation_bt.py` + web research)
Tested on our own cache (honest conventions) + literature review. **Do NOT build:** PEAD (dead academically — Martineau 2021; our data: +0.9%/42d, 51% WR OOS), sector rotation (15-16% CAGR < QQQ; alpha decayed ~2010), GEM/dual momentum (~6% CAGR OOS 2014+), VIX-switching (refuted OOS; sells bottoms), turn-of-month as overlay (5.5% CAGR; only valid use = timing NEW-cash deployment, zero tax cost), IPO breakouts (negative base rates, WR 20-35%). **QQQ Faber SMA200 monthly**: 19.1% vs 21.8% B&H, MDD -28.6 vs -35.1, 10 switches/decade — insurance, not alpha; SMA gates on stock momentum HURT in our tests (whipsaw, exits after crash + misses recovery — consistent with DANGER-flip finding).
**Candidates that survived:**
1. **Large-cap 12-1 momentum rotation** (top-200 dollar-vol, px≥20, 12-1 mom capped ≤200%, top-10 equal-weight, monthly, NO SMA gate): our data 2017+ **32.5% CAGR / MDD -40.9% / monthly WR 63.5%**; 2023+ 58.7%/65.1%. SURVIVORSHIP-INFLATED upper bound (live SPMO analog = 18.6%/yr; QMOM small-cap analog = 12.7% — large-cap is the sleeve that works). Param-sensitive (dv100/cap100 variant → only 15.4%). Needs walk-forward + quarantine-aware validation before any live sizing. This is the honest replacement direction for the broken tab momentum sleeve (which ranks by ret20×vr spike-chasing).
2. **52wk-high Minervini breakout @ Fixed90d** (within 5% of 252d high, de-dup): 56.4% WR / +4.62% OOS per trade, 59.5% WR 2025+ — the momentum gate itself is fine at the right horizon; the tab's ranking within it is what rotted.
3. **Leveraged-index trend satellite (QLD/TQQQ > 200SMA, Gayed)** — only published family beating QQQ's CAGR (26%+ backtested), at realized -57 to -72% MDD (2022, filtered). User-decision-only, ≤10-20% satellite, never the book.

### Lower-priority (cosmetic / non-blocking)
- 27 of 31 endpoints have no FastAPI `response_model=` (no output validation on `/scan/combined`, `/analyze`, etc. — guardrail gap, not a live bug).
- `AllocationChart.tsx` appears unused (dead bundle weight or a missing Portfolio-tab feature).
- ~~`SectorsTab` has no error/retry state~~ — FIXED 2026-07-11 in the Sectors-tab upgrade (error card + retry, stale-data banner). The tab now shows RRG rotation quadrants vs SPY (INFORMATIONAL ONLY — sector strength does NOT feed entry scoring; a sector-tilt factor needs its own backtest first), 11×11 sector correlations, per-sector news sentiment (`sector_intel_loop`, 45-min refresh, Google News RSS), and portfolio tilt vs leadership (quadrant weights, HHI, flags). Logic in `backend/sector_intel.py`; ticker→sector via `ticker_sectors` SQLite table (static seed + Finnhub profile2 backfill). Skill: `/sectors`.
- `OpportunitiesTab` force-refresh can stack 5s pollers if clicked repeatedly (use a ref).

---

## REQUIRED: Full Analysis Before Any Recommendation

**ALWAYS check these 4 factors before recommending ANY stock:**

### 1. Technical (85% weight)
```
- RSI(2) < 10 for BUY (< 5 = extreme)
- Price > SMA(50) (uptrend required)
- Backtest WR > 55% (10+ trades)
- Backtest uses next-day open entry + 0.30% fee deduction
```

### 2. Sentiment (10% weight) - VETO Function
```python
from atlas_v2.sentiment_analyst import SentimentAnalyzer
sentiment = SentimentAnalyzer().analyze(ticker, fetch_if_none=True)
# VETO if: sentiment.veto == True (negative news or earnings < 7 days)
```

### 3. Analyst Targets (5% weight) - Exit Only
```python
from atlas_v2.sentiment_analyst import AnalystIntegration
analyst = AnalystIntegration().get_analyst_data(ticker, current_price)
# Use analyst.target_avg for EXIT price, NOT entry
# WARN if: current_price > analyst.target_avg (overvalued)
```

### 4. RSI Zone Expected Returns - EXIT Decisions (NEW)
```
For EXITS: Don't assume overbought = sell
ALWAYS backtest expected returns BY RSI ZONE for each stock:
- BE overbought (RSI>80): +5.62% expected → HOLD/ADD
- LRCX overbought: +2.54% expected → Consider rotation
- QQQ overbought: +0.14% expected → Borderline
- LIN RSI 20-40: -1.12% expected → CAUTION
```

### Decision Matrix
| Technical | Sentiment | RSI Zone Return | Result |
|-----------|-----------|-----------------|--------|
| BUY + WR>55% | No Veto | N/A | **BUY** |
| BUY + WR>55% | VETO | N/A | **WAIT** |
| BUY + WR<55% | Any | N/A | **REJECT** |
| OVERBOUGHT | Any | > +3% | **HOLD** |
| OVERBOUGHT | Any | < +2% | **Consider rotation** |

---

## Transaction Costs

**Fee: $1.50/trade | Round-trip: $3.00**

| Rule | Threshold |
|------|-----------|
| Min profit to trade | $6.00 (2x cost) |
| $1,000 position min move | 0.30% |
| Swap only if | Net benefit > $6, WR improvement > 10% |

---

## Critical Lessons (Mistakes to Avoid)

### 1. ALWAYS Validate Before Recommending
**Mistake**: Recommended SYK (50% WR) and SPG (40% WR) without backtest validation.
**Rule**: Use `model.analyze_with_validation()`. If WR < 55%, DO NOT RECOMMEND.

### 2. Check RSI Before ANY Recommendation
**Mistake**: Recommended AMD when RSI(2) = 100 (overbought).
**Rule**: RSI(2) must be < 10 AND Price > SMA(50) for BUY signals (V2.4).

### 3. RSI(2) > 80 Exit is WRONG for Momentum Stocks (CRITICAL)
**Mistake**: Assumed overbought = sell for LRCX without checking RSI zone returns.
**Rule**: ALWAYS backtest expected returns BY RSI ZONE. BE at overbought has +5.62% expected!

### 4. Always Provide Alternatives
**Mistake**: Said "don't buy" without giving alternatives.
**Rule**: If you say NO to something, say YES to something else.

### 5. Use Fresh Data Only
**Mistake**: Made recommendations using stale data.
**Rule**: Fetch fresh quotes before any recommendation. State the data date.

### 6. No Rate-Limited APIs
**Rule**: Use Stooq (historical, unlimited), Finnhub (quotes, 60/min), Finviz (analysts, unlimited), Google News RSS (sentiment, unlimited). BANNED: Alpha Vantage (25/day), Yahoo Finance (429 errors).

### 7. Never Estimate ILS Positions
**Mistake**: Estimated TA-35 3x ETF was up +26% when actually only +2.3%.
**Rule**: ALWAYS ask user for current position value, never estimate from index.

### 8. Be Confident
**Mistake**: Asked user "should I scan?" instead of just doing it.
**Rule**: When data supports a decision, act on it confidently. Don't ask for permission.

### 9. ALWAYS Check Earnings Calendar Before Recommending (2026-02-12)
**Mistake**: Held ALB and BE through earnings without warning user. ALB dropped -8.6% (earnings miss), BE dropped -9.9% (sell-the-news despite beat).
**Rule**: Check Finnhub earnings calendar for ALL portfolio holdings weekly. VETO any new buy within 7 days of earnings. For existing positions, WARN user and suggest trimming before earnings if position is >20% of portfolio. Deep scanner now has built-in earnings VETO.
**Post-earnings**: If stock drops >5% on earnings, check zone return at new RSI before acting. BE beat earnings and has +12.80% zone return at RSI 30-40 = HOLD. ALB missed but still +9.05% zone return = HOLD with caution.

### 10. Weight Capital by Zone Return, Not Equal
**Mistake**: Suggested deploying $3,200 equally across 5 stocks when zone returns ranged from +2% to +6.7%.
**Rule**: Allocate proportionally to zone expected return. COHR (+6.68%) and BE (+5.65%) should get 63% of capital, not 40%.

### 11. NEVER Sell Before Exit Strategy Triggers (2026-02-27)
**Mistake**: Recommended selling LUV (day 3, Stop8T10 not triggered) and AGCO (day 3/21, Fixed21d not triggered) because their /analyze scores looked weak. Used NEW entry analysis to override EXISTING position exit strategies.
**Rule**: The /analyze endpoint is for evaluating NEW entries. A stock's current score or RSI moving up does NOT mean sell — that's the TRADE WORKING. Only sell when the backtested exit strategy triggers (Fixed14d/21d timer, stop loss, or target hit). NO manual overrides. This is emotional trading disguised as analysis.

---

## Decision Weights (Validated on 755 trades)

| Factor | Weight | Use |
|--------|--------|-----|
| Technical (RSI, trend) | 85% | Entry signals |
| Sentiment | 10% | VETO only (block if negative) |
| Analyst targets | 5% | Exit price only |

### Sentiment VETO Conditions
- Earnings within 7 days → WAIT
- More negative than positive news → WAIT
- Major policy/macro event → Reduce size

---

## Top Candidates from 1,012 Stock Scan (2026-02-09)

| Ticker | Price | RSI | WR | Trades | Avg Ret | Sentiment |
|--------|-------|-----|-----|--------|---------|-----------|
| LIN | $454 | 0.0 | 78.1% | 32 | +1.24% | POSITIVE |
| DXCM | $70 | 0.0 | 75.6% | 41 | +1.65% | POSITIVE |
| BE | $137 | 0.0 | 75.0% | 44 | +13.63% | NEUTRAL |
| AMG | $302 | 7.4 | 74.5% | 47 | +2.74% | POSITIVE |
| CALM | $85 | 17.0 | 72.7% | 33 | +2.40% | NEUTRAL |
| ALB | $160 | 23.6 | 71.4% | 42 | +6.42% | POSITIVE |
| RDW | $9.29 | 28.3 | 64.3% | 42 | +10.69% | POSITIVE |

---

## Watchlist

| Ticker | Action | Entry Zone | Stop |
|--------|--------|------------|------|
| CEG | Watch for entry | $290 | - |
| DXCM | BUY candidate | RSI < 10 | - |
| AMG | BUY candidate | RSI < 10 | - |

---

## Israeli Market & Leveraged ETFs

**Module**: `backend/israeli_market.py`

### Supported Tickers
- TA35.TA: TA-35 Index
- TEVA.TA, NICE.TA, etc.

### 3x Leveraged ETF Adjustments
| Parameter | 1x | 2x | 3x |
|-----------|-----|-----|-----|
| RSI Oversold | <20 | <30 | <35 |
| RSI Overbought | >80 | >70 | >65 |
| Max Hold (BULL) | 7d | 5d | 5d |
| Stop Loss | 8% | 10% | 12% |
| Target | 10% | 8% | 8% |

### Backtest Results (TA-35 3x, 1 year)
- 5-day hold: **64.9% WR**, +2.71% avg return, 57 trades

---

## SIMULATOR — autonomous $100k paper book (NEW 2026-07-29)

A second, fully isolated portfolio the model manages end-to-end. **Never touches positions.db.**

| Piece | Path |
|---|---|
| Policy + ledger + journal | `backend/sim_engine.py` (no api_v2 import — no circular dep) |
| Routes + live-input plumbing + loop | `backend/api_v2.py` (`/api/v2/sim/*`, `sim_engine_loop`) |
| State DB | `backend/data/sim.db` (gitignored; prod has its own on the Fly volume) |
| Frontend | `frontend/components/dashboard/SimTab.tsx` → sidebar "Sim $100k" |

**Strategy registry** (`sim_engine.STRATEGIES`) — each sleeve carries an evidence tier that the UI renders, so an unvalidated sleeve can never look like a validated one. **Tier A** = walk-forward validated here, **B** = study-supported but not walk-forward validated here, **C** = documented weak/unvalidated.

| id | Tier | Source | Exit | Default |
|---|---|---|---|---|
| `CORE_QQQ` | A | passive | band rebalance to `core_target_pct` (40%) | ON |
| `MR_FIXED42` | A | MR/BOTH signals | Fixed42d timer | ON, 5 slots |
| `SWING_RSI75` | C | MR signals w/ live RSI2<10 | RSI(2)>75 **or** 21d cap | ON, 2 slots |
| `BREAKOUT_52W` | B | MOM signals within 5% of 252d high | Fixed90d timer | ON, 2 slots |
| `MOM_ROT_12_1` | B | monthly top-N by 12-1 momentum (top-200 $vol, px>=20, capped 200%) | drops out of the monthly rank | ON, 3 slots |
| `MOM_FIXED90` | C | raw momentum-scanner ranking | Fixed90d timer | OFF — strictly dominated by BREAKOUT_52W on the same pool |

Slot sizing: alpha capital = equity × (100 − core_target_pct), split across every enabled slot, regime-scaled, capped at `max_position_pct` (15%). Sleeves take from the shared ranked candidate list in registry order, so the validated sleeve gets first pick of a contested name.

**Signal source = `get_combined_opportunities()` called in-process**, so the sim inherits the whole prod pipeline (regime gate, live overlay, composite enrichment) with zero duplication. On top of that it re-applies the Entries-tab "validated" filter (`analyst_consensus` OR `sentiment_label` non-empty) plus the VETO chain (penny, ATR>=15, analyst Hold/Sell, <10 trades, composite < 45) and a max-3-per-sector cap. api_v2 additionally computes `high52_dist` (BREAKOUT gate), live RSI(2) with the intraday price appended (SWING exit) and the 12-1 ranking (24h cache).

**Exits**: each sleeve's own rule, plus two universal ones — earnings <=7d and stock-specific negative sentiment. No stops, no targets.

**Rotation / manual trading.** `rotation_enabled` (auto-switch on a composite gap) defaults **OFF**: our point-in-time test of exactly that logic returned 13-24 CAGR points below holding to the timer. Manual `POST /sim/trade|close|switch` are always available; every manual fill is tagged `origin='MANUAL'` in positions, transactions and the journal, and `get_stats()` reports `by_origin` so discretionary decisions are measured against the model's rather than blended into them.

**Cadence**: `sim_engine_loop` runs every `cycle_minutes` (default 60, floor 5) during REGULAR, plus one post-close cycle that journals exits and writes the daily equity + QQQ-buy-and-hold benchmark row. Outside RTH nothing fills (`session != REGULAR` → exits log as SKIP "execute at next open").

**Costs modelled**: $1.50/fill + 5bps adverse slippage each way.

**Every decision is journalled** to `sim_decisions` with its reason — entries carry RSI2/ATR/buffer/52w-dist/WR/trades/analyst/sentiment/exit-plan, skips carry the exact veto, manual sells record `cut_short_by` (days clipped off the exit rule). The tab's Journal sub-tab is the audit trail.

Endpoints: `GET /sim/state|strategies|candidates|decisions|history|equity`, `POST /sim/run?force=&dry_run=`, `POST /sim/config` (per-strategy dicts are MERGED, not replaced), `POST /sim/trade|close|switch`, `POST /sim/reset?confirm=RESET`.

**Frontend sub-tabs**: Book (strategy + tier badge + exit rule per row, Sell/Switch buttons), Strategies (registry cards w/ thesis + evidence + toggle + slot steppers), Buy/Switch (live candidate feed w/ per-sleeve buy buttons and the block reason for everything it won't take), Journal, Closed (attribution by strategy AND by model-vs-manual), Policy.

---

## File Locations

| Component | Path |
|-----------|------|
| ATLAS V2.4 | `backend/atlas_v2/` |
| Positions DB | `backend/positions.db` |
| Signal History | `backend/signal_history.db` |
| Exit Strategies | `backend/data/exit_strategy_validated.json` |

---

## Data Sources

| Purpose | Source | Limit | Notes |
|---------|--------|-------|-------|
| Historical OHLCV | **Stooq** | UNLIMITED | Primary, 365 days, no key |
| Live Quotes | **Finnhub** | 60/min | Free key |
| Analyst Targets | **Finviz** (scraping) | UNLIMITED | No key, price targets + rec score |
| Sentiment | **Google News RSS** | UNLIMITED | No key, VADER analysis |
| Analyst Ratings | **Finnhub** /recommendation | 60/min | Fallback for Finviz |
| Israeli Market | Yahoo Finance (.TA) | Limited | Only for .TA tickers |

**BANNED**: Alpha Vantage (25/day), Yahoo Finance for US stocks (429 errors), Demo/fake data

---
*Last updated: 2026-02-28*
