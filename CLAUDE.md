# SuperApp Trading Assistant

## Core Rules
- **PRIMARY GOAL**: MAXIMIZE ROI (3% monthly is MINIMUM, not target)
- **RULE**: When saying SELL, ALWAYS say what to BUY
- **MODEL**: Production runs **ATLAS V2.7 (MR entries) + V3.0 (cache-accelerated evaluator) + V3.3 (regime-adaptive entry sizing, 2026-06-12) + V3.4 (Buffered WR scoring, 2026-06-16) + V3.4 (Fixed60d MR exit, 2026-06-17 — replaces V3.2 Fixed30d after honest 13-window walk-forward validation) + V3.5 (Entries tab sorts by composite_score, not Buffered WR, 2026-06-18 — head-to-head walk-forward: composite top-3 fwd +4.43% vs BWR +2.79%)**. There is no single "version" — the deployed code is a hybrid. See "Active Strategy" section below for the actual rules.
- **VALIDATION**: NEVER recommend without backtest validation (WR > 55%, 10+ trades)
- **LIVE DATA**: NEVER suggest buy without verifying live prices first (MANDATORY)
- **SENTIMENT**: ALWAYS check news sentiment before any buy recommendation (informational; not a hard veto for MR — see VETO chain below)
- **SCAN SIZE**: Scan at least 1,000 stocks before making buy recommendations
- **BACKTEST FIRST**: ALWAYS run backtest on ALL positions BEFORE showing any projections or recommendations (MANDATORY)
- **NO FAKE PROJECTIONS**: NEVER show projected returns without actual backtest data to back it up
- **VERIFY BEFORE SPEAKING**: NEVER tell user any data before checking it deeply first (MANDATORY)
- **RSI ZONE ANALYSIS**: Don't assume overbought = sell. Backtest expected returns BY RSI ZONE for each stock (MANDATORY)
- **BE CONFIDENT**: Don't ask user for permission when data supports a decision - act on it
- **SCAN FOR BETTER**: Before recommending ANY buy, ALWAYS scan 1,000+ stocks for better alternatives. Don't default to existing holdings - find the BEST opportunity (MANDATORY)
- **PORTFOLIO BALANCE**: When recommending BUY/SELL, ALWAYS consider total portfolio spread. Target ~20% per position, no single stock >30%. Size new buys to rebalance underweight positions. Don't create new overweight positions (MANDATORY)
- **EARNINGS CALENDAR**: ALWAYS check earnings calendar (Finnhub) before ANY buy recommendation. VETO any stock with earnings within 7 days. Also check portfolio holdings for upcoming earnings and WARN user. Use `python3 deep_scanner.py` which has built-in earnings VETO (MANDATORY)
- **WEIGHTED ALLOCATION**: When deploying new capital, weight by zone expected return - NOT equal weight. Stocks with higher zone returns get more capital (MANDATORY)
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
| Mean Reversion / BOTH | **Fixed60d** — exit on trading day 60 (was Fixed30d, switched 2026-06-17 after 13-window honest walk-forward on clean 2,573-ticker universe: Fixed60d N=4 OOS-2024 +23.2% CAGR / 2.09% monthly / MDD -11.6% / Sharpe 0.78 vs Fixed30d N=4 +6.3% / 1.04% / -35% / 0.59. Cross-period worst-month +0.94% vs -0.18%. Honest regime-dynamic exits also lost to Fixed60d once portfolio capacity constraints applied.) | `api_v2.py:_select_best_exit` |
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

### Open items needing a backtest decision (NOT changed — would alter live exit behavior)
- **Momentum trailing-stop override on MR/Fixed60d** (`api_v2.py:_evaluate_exit_trigger` ~871): an 8%-trailing override currently lets profitable trending MR winners run *past* day 60, contradicting "no stops / let the Fixed60d timer fire." Gating it to MOM-only would force day-60 exits — needs a backtest before changing.
- **`_select_best_exit` hardcodes Fixed60d for all strategies**: the second held-position endpoint (~5543) evaluates MOMENTUM on a 60d timer instead of Fixed90d (premature). Fix needs the position strategy threaded through.
- **Per-stock exit backtest off-by-one**: `_select_best_exit` holds 60 bars; precompute + live timer hold 61. Align the convention.
- **Earnings<7d / sentiment early-exit not wired into the live holdings exit path** — only "model EXIT" is. Decide whether to wire the Finnhub-calendar (not the false-positive news detector) into the exit ladder.

### Lower-priority (cosmetic / non-blocking)
- 27 of 31 endpoints have no FastAPI `response_model=` (no output validation on `/scan/combined`, `/analyze`, etc. — guardrail gap, not a live bug).
- `AllocationChart.tsx` appears unused (dead bundle weight or a missing Portfolio-tab feature).
- `SectorsTab` has no error/retry state (a failed first load shows "No sector data" until remount).
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
