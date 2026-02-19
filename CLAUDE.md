# SuperApp Trading Assistant

## Core Rules
- **PRIMARY GOAL**: MAXIMIZE ROI (3% monthly is MINIMUM, not target)
- **RULE**: When saying SELL, ALWAYS say what to BUY
- **MODEL**: Use ATLAS V2.1 unified model (replaces V1.0-V27.0)
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

---

## Current Positions (Updated 2026-02-18, Live Data)

### USD Portfolio

| Ticker | Shares | Avg Entry | Regime | WR | Avg Ret (14d) | SMA50 Buffer | Weight |
|--------|--------|-----------|--------|-----|---------------|--------------|--------|
| COHR | 13.8764 | $220.08 | BULL | 94.3% | +11.97% | +14.8% | 36% |
| BE | 15.6302 | $141.84 | BULL | 82.8% | +24.98% | +26.4% | 28% |
| CMC | 16.9659 | $78.39 | BULL | 87.5% | +5.43% | +6.3% | 15% |
| BWA | 19.0987 | $61.47 | BULL | 84.0% | +6.95% | +27.2% | 14% |
| GHM | 8.4703 | $84.88 | BULL | 88.5% | +10.09% | +15.1% | 8% |

### ILS Portfolio
- **SOLD** TA-35 3x ETF on 2026-02-10 for ~+2,871 ILS profit (+14.5%)
- LUMI.TA: ~10,000 ILS position (entered 2026-02-17)
- Waiting for TA-35 pullback to ~4,000 to re-enter (RSI < 35 entry signal)

---

## Transaction History
| Date | Action | Ticker | Shares | Amount | Fee |
|------|--------|--------|--------|--------|-----|
| 2026-02-06 | SELL | SPG | - | $995 | -$1.50 |
| 2026-02-06 | SELL | NEM | - | $664 | -$1.50 |
| 2026-02-06 | SELL | SYK | - | $1,074 | -$1.50 |
| 2026-02-06 | BUY | LIN | 2.205 | $999 | -$1.50 |
| 2026-02-06 | BUY | BE | 4.64 | $650 | -$1.50 |
| 2026-02-06 | BUY | ALB | 6.5922 | $1,070 | -$1.50 |
| 2026-02-10 | SELL | LIN | 2.205 | ~$1,021 | -$1.50 |
| 2026-02-10 | BUY | GOOGL | 3.2039 | $1,021 | -$1.50 |
| 2026-02-10 | SELL | QQQ | 2.381 | ~$1,462 | -$1.50 |
| 2026-02-10 | BUY | VRT | 7.2447 | $1,462 | -$1.50 |
| 2026-02-10 | SELL | TA-35 3x (ILS) | - | ~22,675 ILS | - |
| 2026-02-11 | SELL | VRT | 7.2447 | $1,775 | -$1.50 |
| 2026-02-11 | BUY | COHR | 4.7599 | $1,062 | -$1.50 |
| 2026-02-11 | BUY | BE (add) | 2.581 | $376 | -$1.50 |
| 2026-02-11 | BUY | LRCX (add) | 1.4423 | $336 | -$1.50 |
| 2026-02-12 | SELL | GOOGL | 3.2039 | $994 | -$1.50 |
| 2026-02-12 | BUY | COHR (add) | 4.5514 | $992 | -$1.50 |
| 2026-02-13 | SELL | LRCX | 4.5502 | $1,079 | -$1.50 |
| 2026-02-13 | BUY | COHR (add) | 4.5651 | $1,004 | -$1.50 |
| 2026-02-13 | BUY | BE (add) | 8.4635 | $1,200 | -$1.50 |
| 2026-02-13 | BUY | ALB (add) | 5.1978 | $862 | -$1.50 |
| 2026-02-13 | BUY | GHM | 8.4703 | $719 | -$1.50 |
| 2026-02-13 | BUY | JOUT | 10.2115 | $498 | -$1.50 |
| 2026-02-18 | SELL | JOUT | 10.2115 | $500 | -$1.50 |
| 2026-02-18 | SELL | ALB | 11.78 | $2,032 | -$1.50 |
| 2026-02-18 | BUY | CMC | 16.9659 | $1,330 | -$1.50 |
| 2026-02-18 | BUY | BWA | 19.0987 | $1,174 | -$1.50 |
| **Total Fees** | | | | | **-$33.00** |

---

## ATLAS V2.3 - Primary Model (Updated 2026-02-18)

**Location**: `backend/atlas_v2/entry.py`, `backend/atlas_v2/model.py`, `backend/api_v2.py`

### Key V2.3 Changes (Backtested on 467 trades from our portfolio stocks)
- **14-day hold** replaces 7-day (87.7% WR, +11.29% avg vs 84%, +6.03%)
- **No profit targets** — they HALVE returns (+5.25% vs +11.29%)
- **SMA50 buffer** is #1 predictor (20%+ = +9.29% avg vs 0-5% = +2.76%)
- **Exit selection by avg_ret** not annualized (favors longer holds like Fixed14d)

### Entry Signal (V2.3)
```
REQUIRED: Price > SMA(50) AND RSI(2) < threshold AND Volume > 1.5x avg

Scoring:
+40 pts: RSI(2) < 5 (extreme)
+25 pts: RSI(2) < 10
+15 pts: RSI(2) < 20
+20 pts: Price > SMA(50) (REQUIRED)
+10 pts: Price > SMA(200)
+10 pts: Volume > 1.5x (REQUIRED in V2.3)
+10 pts: RSI(14) < 40
+15 pts: SMA50 buffer > 15% (NEW — strongest predictor)
-20 pts: Trend strength > 25%
```

### V2.3 VETO Filters
| Filter | Condition | Action |
|--------|-----------|--------|
| Analyst Target | Price > target | VETO - overvalued |
| Crash Filter | >8% drop in 1 day | VETO - wait for stabilization |
| Flip Cooldown | SELL signal < 5 days ago | VETO - avoid whipsaw |
| Weekly RSI | Weekly RSI > 70 | VETO - overbought multi-TF |
| Earnings | < 7 days to earnings | VETO - binary event (check Finnhub calendar) |
| Sentiment | Score < -0.3 | VETO - negative news |
| Post-Earnings Drop | >5% drop on earnings day | ANALYZE zone return before acting |

### Validation Thresholds
| Condition | Level | Action |
|-----------|-------|--------|
| WR < 55% | CRITICAL | INVALID - Do not recommend |
| WR 55-60% | WARNING | Small position only |
| Trades < 10 | CRITICAL | Insufficient sample |

### Exit Strategy (V2.3 — backtested optimal)
- **Hold period**: Fixed 14 days (replaces variable 7-day)
- **No profit targets**: Let positions run full 14 days
- **Exit selection**: By absolute avg_ret (not annualized)
- **Stop loss**: -8% (BULL), -5% (SIDEWAYS), -4% (BEAR)
- **SMA50 buffer weighting**: Higher buffer = stronger signal

---

## REQUIRED: Full Analysis Before Any Recommendation

**ALWAYS check these 4 factors before recommending ANY stock:**

### 1. Technical (85% weight)
```
- RSI(2) < 20 for BUY (< 10 = strong)
- Price > SMA(50) (uptrend required)
- Backtest WR > 55% (10+ trades)
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
**Rule**: RSI(2) must be < 20 AND Price > SMA(50) for BUY signals.

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
| ATLAS V2.1 | `backend/atlas_v2/` |
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
*Last updated: 2026-02-10*
