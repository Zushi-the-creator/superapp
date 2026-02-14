    # Product Requirements Document: Trading Models & Signal System

**Version:** 2.1
**Last Updated:** 2026-01-17
**Author:** Trading System

---

## 1. Overview

### 1.1 Purpose
This document defines the exact logic, calculations, and decision-making rules for all trading models used in the portfolio management system. Every signal generation must follow these specifications precisely.

### 1.2 Core Principles

1. **Every position must be monitored daily for BOTH entry AND exit signals.** Missing an exit signal is as costly as missing an entry signal.

2. **When saying SELL, ALWAYS say what to BUY.** Never leave the user without an actionable alternative. This is a MANDATORY rule.

3. **Use fresh data only.** Never make recommendations based on stale data (>1 day old).

4. **Track all signals.** Every signal generated must be recorded for ML learning loop.

### 1.3 Current Models in Use

| Model | Version | Assigned Tickers | Win Rate (Backtest) |
|-------|---------|------------------|---------------------|
| Extreme Oversold | V17.0 | VST | 85.7% |
| Connors RSI(2) | V15.0 | LLY, QQQ | 83.3% |
| RSI(5) + Bollinger Band | V20.0 | COIN | 80.0% |

---

## 2. Technical Indicator Calculations

### 2.1 RSI (Relative Strength Index)

**Formula:**
```
RSI = 100 - (100 / (1 + RS))

Where:
RS = Average Gain / Average Loss (over N periods)
Average Gain = SMA of gains over N periods (losses = 0)
Average Loss = SMA of losses over N periods (gains = 0)
```

**Periods Used:**
- RSI(2): 2-period RSI (very sensitive, mean reversion)
- RSI(5): 5-period RSI (short-term momentum)
- RSI(14): 14-period RSI (standard, trend confirmation)

**Implementation:**
```python
def calc_rsi(prices: pd.Series, period: int) -> pd.Series:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi
```

### 2.2 Moving Averages

**Simple Moving Average (SMA):**
```
SMA(N) = Sum of last N closing prices / N
```

**Exponential Moving Average (EMA):**
```
EMA(N) = Price(today) * k + EMA(yesterday) * (1-k)
Where: k = 2 / (N + 1)
```

**Key SMAs/EMAs:**
- SMA(5): Short-term exit trigger for Connors RSI
- SMA(20): Bollinger Band center
- SMA(50): Medium-term trend
- SMA(200): Long-term trend / uptrend filter
- EMA(9): Fast trend
- EMA(21): Slow trend

### 2.3 Bollinger Bands

**Formula:**
```
Middle Band = SMA(20)
Upper Band = SMA(20) + (2 * StdDev(20))
Lower Band = SMA(20) - (2 * StdDev(20))

BB% = (Price - Lower Band) / (Upper Band - Lower Band) * 100
```

**Interpretation:**
- BB% < 5%: Extremely oversold (near lower band)
- BB% < 20%: Oversold
- BB% 20-80%: Neutral
- BB% > 80%: Overbought
- BB% > 95%: Extremely overbought (near upper band)

---

## 3. Model Specifications

### 3.1 V17.0 Extreme Oversold

**Philosophy:** Buy when multiple RSI timeframes show extreme oversold conditions in an uptrend. Sell when short-term RSI recovers.

**ENTRY CONDITIONS (ALL must be true):**
```
1. RSI(2) < 5       -- Extremely oversold on 2-period
2. RSI(14) < 35     -- Confirmed oversold on 14-period
3. Price > SMA(200) -- Must be in long-term uptrend
```

**EXIT CONDITIONS (ANY triggers sell):**
```
1. RSI(2) > 60      -- Short-term recovery (PRIMARY EXIT)
2. 7 trading days since entry (TIME STOP)
```

**SIGNAL STRENGTH CALCULATION:**
```python
def v17_signal_strength(rsi_2, rsi_14, price, sma_200):
    if rsi_2 < 5 and rsi_14 < 35 and price > sma_200:
        # Entry signal strength (0-100)
        strength = 100 - (rsi_2 * 10)  # Lower RSI = stronger
        return "BUY", min(strength, 100)
    elif rsi_2 > 60:
        strength = min((rsi_2 - 60) * 2.5, 100)  # Higher RSI = stronger sell
        return "SELL", strength
    else:
        return "HOLD", 0
```

**DAILY CHECK FOR EXISTING POSITION:**
```
IF position exists in VST:
    IF RSI(2) > 60:
        SIGNAL = "SELL"
        ALERT = "V17.0 EXIT: RSI(2) = {value} > 60 threshold"
    ELIF days_held >= 7:
        SIGNAL = "SELL"
        ALERT = "V17.0 TIME STOP: 7 days reached"
    ELSE:
        SIGNAL = "HOLD"
```

---

### 3.2 V15.0 Connors RSI(2)

**Philosophy:** Larry Connors mean reversion strategy. Buy extreme oversold in uptrend, sell when price recovers above short-term average.

**ENTRY CONDITIONS (ALL must be true):**
```
1. RSI(2) < 5       -- Extremely oversold
2. Price > SMA(200) -- Long-term uptrend filter
```

**EXIT CONDITIONS (ANY triggers sell):**
```
1. Price > SMA(5)   -- Price recovered above 5-day average (PRIMARY)
2. 7 trading days since entry (TIME STOP)
```

**SIGNAL STRENGTH CALCULATION:**
```python
def v15_signal_strength(rsi_2, price, sma_5, sma_200):
    if rsi_2 < 5 and price > sma_200:
        strength = 100 - (rsi_2 * 15)
        return "BUY", min(strength, 100)
    elif price > sma_5:
        # Sell strength based on how far above SMA(5)
        pct_above = ((price - sma_5) / sma_5) * 100
        strength = min(50 + (pct_above * 20), 100)
        return "SELL", strength
    else:
        return "HOLD", 0
```

**DAILY CHECK FOR EXISTING POSITION:**
```
IF position exists in LLY or QQQ:
    IF Price > SMA(5):
        SIGNAL = "SELL"
        ALERT = "V15.0 EXIT: Price ${price} > SMA(5) ${sma5}"
    ELIF days_held >= 7:
        SIGNAL = "SELL"
        ALERT = "V15.0 TIME STOP: 7 days reached"
    ELSE:
        distance_to_exit = ((sma_5 - price) / price) * 100
        SIGNAL = "HOLD"
        NOTE = "Price {distance_to_exit}% below SMA(5) exit trigger"
```

---

### 3.3 V20.0 RSI(5) + Bollinger Band

**Philosophy:** Combine momentum (RSI) with volatility (BB) for high-beta stocks. More forgiving entry than RSI(2) strategies.

**ENTRY CONDITIONS (ALL must be true):**
```
1. RSI(5) < 25           -- Oversold on 5-period
2. Price within 2% of Lower Bollinger Band
   (BB% < 10% OR Price < Lower_BB * 1.02)
```

**EXIT CONDITIONS (ANY triggers sell):**
```
1. RSI(5) > 80           -- Overbought (PRIMARY)
2. 7 trading days since entry (TIME STOP)
```

**SIGNAL STRENGTH CALCULATION:**
```python
def v20_signal_strength(rsi_5, price, bb_lower, bb_upper):
    bb_pct = (price - bb_lower) / (bb_upper - bb_lower) * 100

    if rsi_5 < 25 and bb_pct < 10:
        strength = (25 - rsi_5) * 3 + (10 - bb_pct) * 2
        return "BUY", min(strength, 100)
    elif rsi_5 > 80:
        strength = min((rsi_5 - 80) * 5, 100)
        return "SELL", strength
    else:
        return "HOLD", 0
```

**DAILY CHECK FOR EXISTING POSITION:**
```
IF position exists in COIN:
    IF RSI(5) > 80:
        SIGNAL = "SELL"
        ALERT = "V20.0 EXIT: RSI(5) = {value} > 80 threshold"
    ELIF days_held >= 7:
        SIGNAL = "SELL"
        ALERT = "V20.0 TIME STOP: 7 days reached"
    ELSE:
        SIGNAL = "HOLD"
        distance_to_exit = 80 - rsi_5
        NOTE = "RSI(5) is {distance_to_exit} points from sell trigger"
```

---

## 4. Position Monitoring System

### 4.1 Daily Check Requirements

**CRITICAL: Run every market day BEFORE market open and AFTER market close**

```python
def daily_position_check(positions: List[Position]) -> List[Signal]:
    signals = []

    for position in positions:
        ticker = position.ticker
        model = position.model
        entry_date = position.entry_date
        days_held = (today - entry_date).days

        # Fetch fresh data
        data = fetch_latest_data(ticker)
        indicators = calculate_indicators(data)

        # Check model-specific exit conditions
        if model == "V17.0":
            if indicators.rsi_2 > 60:
                signals.append(Signal(
                    ticker=ticker,
                    action="SELL",
                    reason=f"V17.0 EXIT: RSI(2) = {indicators.rsi_2:.1f} > 60",
                    urgency="HIGH",
                    model=model
                ))
            elif days_held >= 7:
                signals.append(Signal(
                    ticker=ticker,
                    action="SELL",
                    reason=f"V17.0 TIME STOP: {days_held} days held",
                    urgency="MEDIUM",
                    model=model
                ))

        elif model == "V15.0":
            if indicators.price > indicators.sma_5:
                signals.append(Signal(
                    ticker=ticker,
                    action="SELL",
                    reason=f"V15.0 EXIT: Price ${indicators.price:.2f} > SMA(5) ${indicators.sma_5:.2f}",
                    urgency="HIGH",
                    model=model
                ))
            elif days_held >= 7:
                signals.append(Signal(
                    ticker=ticker,
                    action="SELL",
                    reason=f"V15.0 TIME STOP: {days_held} days held",
                    urgency="MEDIUM",
                    model=model
                ))

        elif model == "V20.0":
            if indicators.rsi_5 > 80:
                signals.append(Signal(
                    ticker=ticker,
                    action="SELL",
                    reason=f"V20.0 EXIT: RSI(5) = {indicators.rsi_5:.1f} > 80",
                    urgency="HIGH",
                    model=model
                ))
            elif days_held >= 7:
                signals.append(Signal(
                    ticker=ticker,
                    action="SELL",
                    reason=f"V20.0 TIME STOP: {days_held} days held",
                    urgency="MEDIUM",
                    model=model
                ))

    return signals
```

### 4.2 Signal History Tracking

**Every signal must be recorded with:**
```python
@dataclass
class SignalRecord:
    id: str                    # Unique ID
    timestamp: datetime        # When signal generated
    ticker: str
    model: str
    signal_type: str           # BUY, SELL, HOLD
    reason: str                # Human-readable reason
    indicators: dict           # RSI values, prices, etc.
    price_at_signal: float     # Price when signal generated
    was_followed: bool = None  # Did user act on it?
    outcome_price: float = None # Price after 7 days
    outcome_pct: float = None  # Return if followed
```

### 4.3 Missed Signal Detection

**Run daily to detect signals that occurred but weren't acted upon:**

```python
def detect_missed_signals(ticker: str, model: str, lookback_days: int = 5) -> List[MissedSignal]:
    missed = []
    data = fetch_historical_data(ticker, days=lookback_days + 20)

    for i in range(lookback_days, 0, -1):
        date = today - timedelta(days=i)
        indicators = calculate_indicators_at_date(data, date)

        if model == "V17.0" and indicators.rsi_2 > 60:
            missed.append(MissedSignal(
                date=date,
                ticker=ticker,
                signal="SELL",
                indicator=f"RSI(2) = {indicators.rsi_2:.1f}",
                threshold="RSI(2) > 60",
                price_at_signal=indicators.price,
                price_now=current_price,
                impact_pct=((current_price - indicators.price) / indicators.price) * 100
            ))

    return missed
```

---

## 5. Decision Flow Charts

### 5.1 V17.0 Extreme Oversold Flow

```
START: Daily Check for VST
         |
         v
    [Fetch Data]
         |
         v
    [Calculate RSI(2), RSI(14), SMA(200)]
         |
         v
    Is Position Open?
    /           \
   YES          NO
    |            |
    v            v
[CHECK EXIT]   [CHECK ENTRY]
    |            |
    v            v
RSI(2) > 60?   RSI(2) < 5?
    |            |
   YES          YES
    |            |
    v            v
 SELL!       RSI(14) < 35?
    |            |
   NO           YES
    |            |
    v            v
Days >= 7?    Price > SMA(200)?
    |            |
   YES          YES
    |            |
    v            v
 SELL!         BUY!
    |            |
   NO           NO
    |            |
    v            v
  HOLD         HOLD
```

### 5.2 V15.0 Connors RSI(2) Flow

```
START: Daily Check for LLY/QQQ
         |
         v
    [Fetch Data]
         |
         v
    [Calculate RSI(2), SMA(5), SMA(200)]
         |
         v
    Is Position Open?
    /           \
   YES          NO
    |            |
    v            v
[CHECK EXIT]   [CHECK ENTRY]
    |            |
    v            v
Price > SMA(5)?  RSI(2) < 5?
    |            |
   YES          YES
    |            |
    v            v
 SELL!       Price > SMA(200)?
    |            |
   NO           YES
    |            |
    v            v
Days >= 7?      BUY!
    |            |
   YES          NO
    |            |
    v            v
 SELL!        HOLD
    |
   NO
    |
    v
  HOLD
```

### 5.3 V20.0 RSI(5) + BB Flow

```
START: Daily Check for COIN
         |
         v
    [Fetch Data]
         |
         v
    [Calculate RSI(5), BB Lower/Upper]
         |
         v
    Is Position Open?
    /           \
   YES          NO
    |            |
    v            v
[CHECK EXIT]   [CHECK ENTRY]
    |            |
    v            v
RSI(5) > 80?   RSI(5) < 25?
    |            |
   YES          YES
    |            |
    v            v
 SELL!       BB% < 10%?
    |            |
   NO           YES
    |            |
    v            v
Days >= 7?      BUY!
    |            |
   YES          NO
    |            |
    v            v
 SELL!        HOLD
    |
   NO
    |
    v
  HOLD
```

---

## 6. Signal Recording Requirements

### 6.1 What Must Be Recorded

**On Every Signal Generation:**
```json
{
    "signal_id": "uuid",
    "timestamp": "2026-01-17T09:30:00Z",
    "ticker": "VST",
    "model": "V17.0",
    "signal": "SELL",
    "reason": "RSI(2) = 84.3 > 60 threshold",
    "urgency": "HIGH",
    "indicators": {
        "rsi_2": 84.3,
        "rsi_5": 65.2,
        "rsi_14": 58.1,
        "price": 175.50,
        "sma_5": 172.30,
        "sma_200": 165.00,
        "bb_pct": 75.2
    },
    "position": {
        "shares": 7.9038,
        "entry_price": 169.58,
        "entry_date": "2026-01-05",
        "days_held": 8,
        "unrealized_pnl": 46.78,
        "unrealized_pnl_pct": 3.49
    }
}
```

### 6.2 What Must Be Tracked After Signal

**7-Day Follow-up Record:**
```json
{
    "signal_id": "uuid",
    "was_followed": false,
    "follow_up_date": "2026-01-24T16:00:00Z",
    "price_at_signal": 175.50,
    "price_7d_later": 166.60,
    "would_have_returned_pct": -5.07,
    "actual_action_taken": "HELD",
    "actual_return_pct": -1.76,
    "signal_was_correct": true,
    "notes": "Missed sell signal cost ~3.3% opportunity"
}
```

---

## 7. Learning Loop Integration

### 7.1 Model Performance Update

After each signal outcome is recorded:

```python
def update_model_performance(signal_record: SignalRecord):
    model = signal_record.model
    was_correct = signal_record.signal_was_correct

    # Update rolling accuracy
    model_stats = get_model_stats(model)
    model_stats.total_signals += 1
    if was_correct:
        model_stats.correct_signals += 1

    model_stats.live_win_rate = (
        model_stats.correct_signals / model_stats.total_signals
    ) * 100

    # Compare to backtest win rate
    model_stats.live_vs_backtest_gap = (
        model_stats.live_win_rate - model_stats.backtest_win_rate
    )

    # Alert if degradation
    if model_stats.live_vs_backtest_gap < -10:
        alert(f"WARNING: {model} live accuracy {model_stats.live_win_rate:.1f}% "
              f"is {abs(model_stats.live_vs_backtest_gap):.1f}% below backtest")

    save_model_stats(model_stats)
```

### 7.2 Dashboard Display Requirements

The dashboard MUST show:

1. **Current Signals** - What the model says RIGHT NOW
2. **Signal History** - Last 30 days of signals generated
3. **Missed Signals** - Signals that triggered but weren't followed
4. **Model Accuracy** - Live accuracy vs backtest accuracy
5. **Position Exit Distance** - How close each position is to exit trigger

---

## 8. Example: What Should Have Happened with VST

### Timeline Reconstruction

| Date | RSI(2) | Model Says | What Happened |
|------|--------|------------|---------------|
| Jan 13 | 100.0 | **SELL** (>60) | Not tracked, missed |
| Jan 14 | 84.3 | **SELL** (>60) | Not tracked, missed |
| Jan 15 | 0.0 | HOLD | - |
| Jan 16 | 82.1 | **SELL** (>60) | Not tracked, missed |
| Jan 17 | 45.2 | HOLD | Price dropped 7.5% |

### What System Should Have Done

```
Jan 13, 2026 - Market Close Check:
  VST: RSI(2) = 100.0
  Model V17.0 EXIT RULE: RSI(2) > 60 = TRUE

  ALERT GENERATED:
  ================================================
  🚨 SELL SIGNAL - VST
  Model: V17.0 Extreme Oversold
  Trigger: RSI(2) = 100.0 > 60 threshold
  Current Price: $180.12
  Your P&L: +$83.45 (+6.23%)

  ACTION REQUIRED: Consider selling position
  ================================================

  SIGNAL RECORDED TO DATABASE:
  - signal_id: abc123
  - timestamp: 2026-01-13T16:00:00
  - signal: SELL
  - price: 180.12
```

---

## 9. Implementation Checklist

- [ ] Daily position scan runs at market open and close
- [ ] All models check BOTH entry AND exit conditions
- [ ] Every signal is recorded to database
- [ ] Missed signals are detected and reported
- [ ] Dashboard shows signal history
- [ ] 7-day follow-up tracks signal accuracy
- [ ] Model live accuracy is calculated and displayed
- [ ] Alerts generated for high-urgency signals

---

## Appendix A: Indicator Reference

| Indicator | Formula | Buy Zone | Sell Zone | Neutral |
|-----------|---------|----------|-----------|---------|
| RSI(2) | Standard RSI, 2 periods | < 5 | > 60-90 | 5-60 |
| RSI(5) | Standard RSI, 5 periods | < 25 | > 80 | 25-80 |
| RSI(14) | Standard RSI, 14 periods | < 30 | > 70 | 30-70 |
| BB% | Position in Bollinger Band | < 10% | > 90% | 10-90% |
| Price vs SMA(5) | Price / SMA(5) | Below | Above | - |
| Price vs SMA(200) | Price / SMA(200) | - | - | Must be above for entry |

---

## Appendix B: Model Quick Reference

### V17.0 Extreme Oversold (VST)
- **BUY**: RSI(2) < 5 AND RSI(14) < 35 AND Price > SMA(200)
- **SELL**: RSI(2) > 60 OR 7 days held

### V15.0 Connors RSI(2) (LLY, QQQ)
- **BUY**: RSI(2) < 5 AND Price > SMA(200)
- **SELL**: Price > SMA(5) OR 7 days held

### V20.0 RSI(5) + BB (COIN)
- **BUY**: RSI(5) < 25 AND BB% < 10
- **SELL**: RSI(5) > 80 OR 7 days held

---

*End of Document*
