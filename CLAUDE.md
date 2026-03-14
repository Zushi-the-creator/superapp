# SuperApp Trading Assistant

## Core Rules
- **PRIMARY GOAL**: MAXIMIZE ROI (3% monthly is MINIMUM, not target)
- **RULE**: When saying SELL, ALWAYS say what to BUY
- **MODEL**: Use ATLAS V2.4 unified model (replaces V1.0-V27.0, V2.1-V2.3)
- **VALIDATION**: NEVER recommend without backtest validation (WR > 55%, 10+ trades)
- **LIVE DATA**: NEVER suggest buy without verifying live prices first (MANDATORY)
- **SENTIMENT**: ALWAYS check news sentiment before any buy recommendation (MANDATORY)
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
- **TRUST BACKTESTS**: If backtests are valid (WR > 55%, 10+ trades, zone trades >= 5), trust the data regardless of stock price. Only filter penny stocks under $5. Be confident with all stocks the model validates (MANDATORY)
- **EXIT TRIGGERS (UPDATED 2026-03-09)**: Hold positions until backtested exit strategy triggers (Fixed14d/21d, stop loss, target hit). But these are VALID early exit reasons: (a) Earnings within 7 days — binary event risk, always EXIT. (b) Stock-specific negative sentiment (downgrade, earnings miss, product failure) — EXIT. (c) Model EXIT signal (both ATLAS WR + zone WR fail 65%) — EXIT. What is NOT a valid exit: market-wide crash headlines, war panic across all stocks, RSI rising (trade working). Distinguish STOCK-SPECIFIC bad news from MARKET-WIDE noise. (MANDATORY)

---

## Current Positions (Updated 2026-02-23, Live Data)

### USD Portfolio (Broker-verified 2026-02-23)

| Ticker | Shares | Avg Entry | Cost Basis | Weight |
|--------|--------|-----------|------------|--------|
| BE | 15.6302 | $141.84 | $2,216.98 | 27.8% |
| WDC | 6.3874 | $281.80 | $1,799.98 | 19.9% |
| CGNX | 27.5412 | $56.02 | $1,543.00 | 17.2% |
| MTRN | 8.7844 | $150.15 | $1,318.99 | 14.2% |
| BWA | 19.0987 | $61.47 | $1,174.00 | 12.3% |
| GHM | 8.4703 | $84.88 | $719.00 | 7.3% |

**Cash: $121.21 | Total Portfolio: $9,024.86 | Total Fees: $63.01**
**Total Deposited: $8,413.58 | Total Realized P&L: +$531.65 | Account P&L: +$610.88 (+7.3%)**

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

## ATLAS V2.4 - Primary Model (Updated 2026-02-28)

**Location**: `backend/atlas_v2/entry.py`, `backend/atlas_v2/model.py`, `backend/api_v2.py`

### Key V2.4 Changes (Backtested on 167 trades, walk-forward validated)
- **RSI(2) < 10** entry (was < 20) — fewer but higher-quality signals
- **No tight stop losses** — research proves stops HURT mean reversion (widened to -20%/-15%/-12%)
- **Next-day open entry** — eliminates look-ahead bias (was same-bar close)
- **Fee-adjusted backtests** — subtract 0.30% per trade ($3 round-trip on $1K)
- **Per-stock hybrid exit** — each stock gets its optimal exit via walk-forward validation
- **DCA skipped** — only 4.9% marginal gain, doubles fees ($3→$6)
- **Expected**: 78.1% WR, +8.62% avg return, PF 8.68 (vs old 69.3% WR, +5.18%, PF 3.50)

### Entry Signal (V2.4)
```
REQUIRED: Price > SMA(50) AND RSI(2) < 10 AND Volume > 1.5x avg

Scoring:
+40 pts: RSI(2) < 5 (extreme)
+25 pts: RSI(2) < 10
+20 pts: Price > SMA(50) (REQUIRED)
+10 pts: Price > SMA(200)
+10 pts: Volume > 1.5x (REQUIRED)
+10 pts: RSI(14) < 40
+15 pts: SMA50 buffer > 15% (strongest predictor)
-20 pts: Trend strength > 25%
```

### V2.4 VETO Filters (ALL enforced in scanner — `api_v2.py:_dict_to_opportunity`)
| Filter | Condition | Action |
|--------|-----------|--------|
| Analyst Target | Price > target | VETO - overvalued |
| Analyst Consensus | Hold/Sell/Underperform | VETO - not a buy |
| Sentiment | NEGATIVE label | VETO - negative news |
| RSI Entry | RSI(2) > 10 | VETO - not oversold enough |
| Zone WR | Zone WR < 65% (5+ trades) | VETO - below minimum (tiered: 80%→70%→65%) |
| Price | Price < $10 | VETO - too volatile/risky |
| Zone Data | Zone trades < 5 | VETO - insufficient sample |
| Score | zone_return × zone_WR / 100 < 3.0 | VETO - low expected value |
| Avg Return | avg_return < 3% | VETO - won't cover fees |
| Crash Filter | >8% drop in 1 day | VETO - wait for stabilization |
| Flip Cooldown | SELL signal < 5 days ago | VETO - avoid whipsaw |
| Earnings | < 7 days to earnings | VETO - binary event |
| Post-Earnings Drop | >5% drop on earnings day | ANALYZE zone return before acting |

### Scoring (Updated 2026-02-28)
- **Score = zone_return × zone_WR / 100** (what matters at CURRENT RSI, not overall avg)
- Fallback to avg_return × WR if zone_trades < 5
- Winners pattern: RSI(2) near 0 + above SMA50 + BULL + positive sentiment + zone > 5%
- Upgrades only suggest switching positions whose exit strategy has triggered

### Validation Thresholds — Tiered WR System (Validated on 122 stocks, 1,760 trades)
| WR Tier | Range | Avg Return | % Profitable | Action |
|---------|-------|------------|-------------|--------|
| **TIER1** | >= 80% | +7.23% | 100% | **BEST — priority picks** |
| **TIER2** | 70-79% | +5.81% | 98% | **GREAT — strong candidates** |
| **TIER3** | 65-69% | +5.36% | 96% | **GOOD — acceptable** |
| REJECT | < 65% | +2.6% | 75% | **VETO — not worth the risk** |
| Zone trades < 5 | — | — | — | **VETO — insufficient sample** |
| Trades < 10 | — | — | — | **WARNING — lower confidence** |

### Exit Strategy (V2.4 — per-stock hybrid, backtested optimal)
- **Per-stock exit selection**: Walk-forward validated (5-fold TimeSeriesSplit)
- **Exit types**: Fixed3d/7d/14d/21d, SMA5/10, RSI50/65/80, Trail5/8
- **No profit targets**: Let positions run to their optimal exit
- **Exit selection**: By absolute avg_ret (not annualized)
- **Stop loss**: -20% (BULL), -15% (SIDEWAYS), -12% (BEAR) — effectively removed
- **SMA50 buffer weighting**: Higher buffer = stronger signal
- **Backtest entry**: Next-day open price (honest execution)
- **Fee deduction**: 0.30% per trade subtracted from backtest returns

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
