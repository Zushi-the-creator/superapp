#!/usr/bin/env python3
"""
Strategy Comparison Backtest
============================
Compares 4 strategies on stocks we've actually traded.

Strategy A: CURRENT (ATLAS V2.3) - RSI(2)<20, Close>SMA50, Fixed 14d hold, -8% stop
Strategy B: CONNORS CLASSIC       - RSI(2)<10, Close>SMA200, Exit above SMA5, no stop, max 10d
Strategy C: IMPROVED (Proposed)   - RSI(2)<10, Close>SMA200, ADX<25, Exit above SMA5 or 10d max, catastrophic stop below SMA200, next-day-open entry
Strategy D: SCALED ENTRY          - Same as C but buy 50% at signal, 50% more if RSI<5 next 2 days, exit above SMA5

Uses data from: backend/data/stock_cache.db
"""

import sqlite3
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
DB_PATH = "data/stock_cache.db"
FEE_PCT = 0.30  # $3 round-trip on $1,000 = 0.30%

TICKERS = [
    'MRVL', 'VST', 'LLY', 'COIN', 'QQQ', 'MU', 'NVDA', 'SLB', 'SYK', 'SPG',
    'NEM', 'LRCX', 'LIN', 'ALB', 'BE', 'GOOGL', 'COHR', 'JOUT', 'GHM', 'CMC',
    'BWA', 'CGNX', 'MTRN', 'WDC', 'NESR', 'EWTX', 'AGCO', 'PDS', 'LUV'
    # VRT excluded - no data in cache
]

# Our actual trades (entry date, ticker, approximate entry price)
ACTUAL_TRADES = [
    ('2026-01-07', 'MRVL'),
    ('2026-01-07', 'VST'),
    ('2026-01-07', 'LLY'),
    ('2026-01-14', 'COIN'),
    ('2026-01-15', 'QQQ'),
    ('2026-01-20', 'MU'),
    ('2026-01-20', 'NVDA'),
    ('2026-01-30', 'SLB'),
    ('2026-02-04', 'SYK'),
    ('2026-02-04', 'SPG'),
    ('2026-02-05', 'NEM'),
    ('2026-02-05', 'LRCX'),
    ('2026-02-06', 'LIN'),
    ('2026-02-06', 'ALB'),
    ('2026-02-10', 'GOOGL'),
    ('2026-02-10', 'BE'),  # Note: BE was bought earlier too, this is the Feb position
    ('2026-02-11', 'COHR'),
    ('2026-02-13', 'JOUT'),
    ('2026-02-18', 'CMC'),
]


# ============================================================
# Technical Indicators
# ============================================================
def compute_rsi(series, period):
    """Compute RSI for a pandas Series."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_sma(series, period):
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


def compute_adx(high, low, close, period=14):
    """Compute ADX indicator."""
    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0), index=close.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0), index=close.index)

    # Smoothed TR and DMs
    atr = tr.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean() / atr)

    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10))
    adx = dx.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()

    return adx


# ============================================================
# Data Loading
# ============================================================
def load_data(ticker):
    """Load and prepare data for a single ticker."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker=? ORDER BY date",
        conn, params=(ticker,)
    )
    conn.close()

    if len(df) < 210:  # Need at least 200 for SMA200
        return None

    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # Compute indicators
    df['rsi2'] = compute_rsi(df['close'], 2)
    df['sma5'] = compute_sma(df['close'], 5)
    df['sma50'] = compute_sma(df['close'], 50)
    df['sma200'] = compute_sma(df['close'], 200)
    df['adx14'] = compute_adx(df['high'], df['low'], df['close'], 14)

    return df


# ============================================================
# Strategy Implementations
# ============================================================

class TradeResult:
    def __init__(self, ticker, entry_date, exit_date, entry_price, exit_price,
                 hold_days, pct_return, strategy, signal_date=None):
        self.ticker = ticker
        self.entry_date = entry_date
        self.exit_date = exit_date
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.hold_days = hold_days
        self.pct_return = pct_return
        self.strategy = strategy
        self.signal_date = signal_date or entry_date


def strategy_a_current(df, ticker):
    """
    Strategy A: CURRENT (ATLAS V2.3)
    Entry: RSI(2) < 20, Close > SMA(50)
    Exit: Fixed 14-day hold
    Stop: -8%
    """
    trades = []
    i = 0
    n = len(df)

    while i < n:
        row = df.iloc[i]

        # Check entry conditions
        if (pd.notna(row['rsi2']) and pd.notna(row['sma50']) and
            row['rsi2'] < 20 and row['close'] > row['sma50']):

            entry_price = row['close']
            entry_date = row['date']
            stop_price = entry_price * 0.92  # -8% stop

            # Hold for up to 14 trading days
            exit_idx = None
            exit_price = None

            for j in range(i + 1, min(i + 15, n)):  # 14 trading days
                day = df.iloc[j]

                # Check stop loss (using low price for intraday stops)
                if day['low'] <= stop_price:
                    exit_price = stop_price
                    exit_idx = j
                    break

                # Fixed 14-day hold
                if j == min(i + 14, n - 1):
                    exit_price = day['close']
                    exit_idx = j
                    break

            if exit_idx is None and i + 14 >= n:
                # Not enough data to complete trade
                exit_idx = n - 1
                exit_price = df.iloc[exit_idx]['close']

            if exit_idx is not None:
                exit_date = df.iloc[exit_idx]['date']
                hold_days = (exit_date - entry_date).days
                pct_ret = ((exit_price - entry_price) / entry_price) * 100

                trades.append(TradeResult(
                    ticker, entry_date, exit_date, entry_price, exit_price,
                    hold_days, pct_ret, 'A_Current'
                ))

                i = exit_idx + 1  # Skip past exit
                continue

        i += 1

    return trades


def strategy_b_connors(df, ticker):
    """
    Strategy B: CONNORS CLASSIC
    Entry: RSI(2) < 10, Close > SMA(200)
    Exit: Close above 5-day SMA
    No stop loss
    Max hold: 10 days
    """
    trades = []
    i = 0
    n = len(df)

    while i < n:
        row = df.iloc[i]

        if (pd.notna(row['rsi2']) and pd.notna(row['sma200']) and pd.notna(row['sma5']) and
            row['rsi2'] < 10 and row['close'] > row['sma200']):

            entry_price = row['close']
            entry_date = row['date']

            exit_idx = None
            exit_price = None

            for j in range(i + 1, min(i + 11, n)):  # Max 10 trading days
                day = df.iloc[j]

                # Exit when close > 5-day SMA
                if pd.notna(day['sma5']) and day['close'] > day['sma5']:
                    exit_price = day['close']
                    exit_idx = j
                    break

                # Max hold 10 days
                if j == min(i + 10, n - 1):
                    exit_price = day['close']
                    exit_idx = j
                    break

            if exit_idx is None and i + 10 >= n:
                exit_idx = n - 1
                exit_price = df.iloc[exit_idx]['close']

            if exit_idx is not None:
                exit_date = df.iloc[exit_idx]['date']
                hold_days = (exit_date - entry_date).days
                pct_ret = ((exit_price - entry_price) / entry_price) * 100

                trades.append(TradeResult(
                    ticker, entry_date, exit_date, entry_price, exit_price,
                    hold_days, pct_ret, 'B_Connors'
                ))

                i = exit_idx + 1
                continue

        i += 1

    return trades


def strategy_c_improved(df, ticker):
    """
    Strategy C: IMPROVED (Proposed)
    Entry: RSI(2) < 10, Close > SMA(200), ADX(14) < 25
    Entry price: NEXT DAY OPEN (realistic execution delay)
    Exit: Close above 5-day SMA OR 10-day max hold
    Catastrophic stop: Close below SMA(200)
    """
    trades = []
    i = 0
    n = len(df)

    while i < n:
        row = df.iloc[i]

        if (pd.notna(row['rsi2']) and pd.notna(row['sma200']) and
            pd.notna(row['sma5']) and pd.notna(row['adx14']) and
            row['rsi2'] < 10 and row['close'] > row['sma200'] and
            row['adx14'] < 25):

            # NEXT DAY OPEN entry
            if i + 1 >= n:
                i += 1
                continue

            next_day = df.iloc[i + 1]
            entry_price = next_day['open']
            entry_date = next_day['date']
            signal_date = row['date']

            exit_idx = None
            exit_price = None

            for j in range(i + 2, min(i + 12, n)):  # Max 10 trading days from entry
                day = df.iloc[j]

                # Catastrophic stop: close below SMA200
                if pd.notna(day['sma200']) and day['close'] < day['sma200']:
                    exit_price = day['close']
                    exit_idx = j
                    break

                # Exit when close > 5-day SMA
                if pd.notna(day['sma5']) and day['close'] > day['sma5']:
                    exit_price = day['close']
                    exit_idx = j
                    break

                # Max hold 10 days
                if j == min(i + 11, n - 1):
                    exit_price = day['close']
                    exit_idx = j
                    break

            if exit_idx is None and i + 11 >= n:
                exit_idx = n - 1
                exit_price = df.iloc[exit_idx]['close']

            if exit_idx is not None:
                exit_date = df.iloc[exit_idx]['date']
                hold_days = (exit_date - entry_date).days
                pct_ret = ((exit_price - entry_price) / entry_price) * 100

                trades.append(TradeResult(
                    ticker, entry_date, exit_date, entry_price, exit_price,
                    hold_days, pct_ret, 'C_Improved', signal_date
                ))

                i = exit_idx + 1
                continue

        i += 1

    return trades


def strategy_d_scaled(df, ticker):
    """
    Strategy D: SCALED ENTRY
    Same as Strategy C but:
    - Buy 50% at signal (next-day open), 50% more if RSI drops below 5 in next 2 days
    - Exit: Close above 5-day SMA or 10-day max hold
    - Catastrophic stop: Close below SMA(200)
    """
    trades = []
    i = 0
    n = len(df)

    while i < n:
        row = df.iloc[i]

        if (pd.notna(row['rsi2']) and pd.notna(row['sma200']) and
            pd.notna(row['sma5']) and pd.notna(row['adx14']) and
            row['rsi2'] < 10 and row['close'] > row['sma200'] and
            row['adx14'] < 25):

            # NEXT DAY OPEN for first tranche (50%)
            if i + 1 >= n:
                i += 1
                continue

            next_day = df.iloc[i + 1]
            entry_price_1 = next_day['open']
            entry_date = next_day['date']
            signal_date = row['date']
            weight_1 = 0.5

            # Check if RSI drops below 5 in the next 2 days for second tranche
            entry_price_2 = None
            weight_2 = 0.0

            for k in range(i + 1, min(i + 3, n)):
                day_k = df.iloc[k]
                if pd.notna(day_k['rsi2']) and day_k['rsi2'] < 5:
                    # Buy second tranche at next day's open
                    if k + 1 < n:
                        entry_price_2 = df.iloc[k + 1]['open']
                        weight_2 = 0.5
                    break

            # Weighted average entry price
            if entry_price_2 is not None:
                avg_entry = (entry_price_1 * weight_1 + entry_price_2 * weight_2) / (weight_1 + weight_2)
            else:
                avg_entry = entry_price_1
                # Only deployed 50% of capital, so returns are halved on the position
                # But we track per-share return here

            exit_idx = None
            exit_price = None

            # Start checking for exit from 2 days after signal (to allow scaling in)
            start_check = i + 3 if entry_price_2 else i + 2

            for j in range(start_check, min(i + 12, n)):
                day = df.iloc[j]

                # Catastrophic stop
                if pd.notna(day['sma200']) and day['close'] < day['sma200']:
                    exit_price = day['close']
                    exit_idx = j
                    break

                # Exit when close > 5-day SMA
                if pd.notna(day['sma5']) and day['close'] > day['sma5']:
                    exit_price = day['close']
                    exit_idx = j
                    break

                # Max hold
                if j == min(i + 11, n - 1):
                    exit_price = day['close']
                    exit_idx = j
                    break

            if exit_idx is None and i + 11 >= n:
                exit_idx = n - 1
                exit_price = df.iloc[exit_idx]['close']

            if exit_idx is not None:
                exit_date = df.iloc[exit_idx]['date']
                hold_days = (exit_date - entry_date).days
                pct_ret = ((exit_price - avg_entry) / avg_entry) * 100

                # Note: if only 50% was deployed, effective portfolio return is halved
                effective_pct = pct_ret if entry_price_2 else pct_ret * 0.5

                trades.append(TradeResult(
                    ticker, entry_date, exit_date, avg_entry, exit_price,
                    hold_days, pct_ret, 'D_Scaled', signal_date
                ))

                i = exit_idx + 1
                continue

        i += 1

    return trades


# ============================================================
# Metrics Computation
# ============================================================
def compute_metrics(trades, label):
    """Compute comprehensive metrics for a list of trades."""
    if not trades:
        return {
            'strategy': label,
            'total_trades': 0,
            'win_rate': 0,
            'avg_return': 0,
            'avg_hold': 0,
            'profit_factor': 0,
            'max_consec_loss': 0,
            'sharpe_like': 0,
            'avg_return_fee_adj': 0,
            'win_rate_fee_adj': 0,
            'total_return': 0,
            'median_return': 0,
            'best_trade': 0,
            'worst_trade': 0,
        }

    returns = [t.pct_return for t in trades]
    fee_adj_returns = [r - FEE_PCT for r in returns]
    holds = [t.hold_days for t in trades]

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    fee_wins = [r for r in fee_adj_returns if r > 0]
    fee_losses = [r for r in fee_adj_returns if r <= 0]

    # Profit factor
    sum_wins = sum(wins) if wins else 0
    sum_losses = abs(sum(losses)) if losses else 0.001
    profit_factor = sum_wins / sum_losses if sum_losses > 0 else float('inf')

    # Fee-adjusted profit factor
    fee_sum_wins = sum(fee_wins) if fee_wins else 0
    fee_sum_losses = abs(sum(fee_losses)) if fee_losses else 0.001
    fee_profit_factor = fee_sum_wins / fee_sum_losses if fee_sum_losses > 0 else float('inf')

    # Max consecutive losses
    max_consec = 0
    current_consec = 0
    for r in returns:
        if r <= 0:
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0

    # Sharpe-like ratio
    std_ret = np.std(returns) if len(returns) > 1 else 1
    sharpe = np.mean(returns) / std_ret if std_ret > 0 else 0

    fee_std = np.std(fee_adj_returns) if len(fee_adj_returns) > 1 else 1
    fee_sharpe = np.mean(fee_adj_returns) / fee_std if fee_std > 0 else 0

    return {
        'strategy': label,
        'total_trades': len(trades),
        'win_rate': (len(wins) / len(returns)) * 100,
        'avg_return': np.mean(returns),
        'median_return': np.median(returns),
        'avg_hold': np.mean(holds),
        'profit_factor': profit_factor,
        'max_consec_loss': max_consec,
        'sharpe_like': sharpe,
        'total_return': sum(returns),
        'best_trade': max(returns),
        'worst_trade': min(returns),
        # Fee-adjusted
        'avg_return_fee_adj': np.mean(fee_adj_returns),
        'win_rate_fee_adj': (len(fee_wins) / len(fee_adj_returns)) * 100,
        'profit_factor_fee_adj': fee_profit_factor,
        'sharpe_fee_adj': fee_sharpe,
        'total_return_fee_adj': sum(fee_adj_returns),
    }


# ============================================================
# Actual Trades Replay
# ============================================================
def replay_actual_trades(all_data):
    """For each of our actual entry dates, simulate what each strategy would have done."""
    results = {'A_Current': [], 'B_Connors': [], 'C_Improved': [], 'D_Scaled': []}

    for entry_date_str, ticker in ACTUAL_TRADES:
        if ticker not in all_data or all_data[ticker] is None:
            continue

        df = all_data[ticker]
        entry_date = pd.Timestamp(entry_date_str)

        # Find the index for entry date (or closest)
        mask = df['date'] >= entry_date
        if not mask.any():
            continue

        idx = df[mask].index[0]
        row = df.iloc[idx]

        # ---- Strategy A: Enter at close, hold 14 days, -8% stop ----
        entry_price_a = row['close']
        stop_a = entry_price_a * 0.92
        exit_price_a = None
        exit_idx_a = None

        for j in range(idx + 1, min(idx + 15, len(df))):
            day = df.iloc[j]
            if day['low'] <= stop_a:
                exit_price_a = stop_a
                exit_idx_a = j
                break
            if j == min(idx + 14, len(df) - 1):
                exit_price_a = day['close']
                exit_idx_a = j
                break

        if exit_idx_a is not None:
            ret_a = ((exit_price_a - entry_price_a) / entry_price_a) * 100
            hold_a = (df.iloc[exit_idx_a]['date'] - row['date']).days
            results['A_Current'].append(TradeResult(
                ticker, row['date'], df.iloc[exit_idx_a]['date'],
                entry_price_a, exit_price_a, hold_a, ret_a, 'A_Current'
            ))

        # ---- Strategy B: Enter at close, exit above SMA5, max 10 days ----
        entry_price_b = row['close']
        exit_price_b = None
        exit_idx_b = None

        for j in range(idx + 1, min(idx + 11, len(df))):
            day = df.iloc[j]
            if pd.notna(day['sma5']) and day['close'] > day['sma5']:
                exit_price_b = day['close']
                exit_idx_b = j
                break
            if j == min(idx + 10, len(df) - 1):
                exit_price_b = day['close']
                exit_idx_b = j
                break

        if exit_idx_b is not None:
            ret_b = ((exit_price_b - entry_price_b) / entry_price_b) * 100
            hold_b = (df.iloc[exit_idx_b]['date'] - row['date']).days
            results['B_Connors'].append(TradeResult(
                ticker, row['date'], df.iloc[exit_idx_b]['date'],
                entry_price_b, exit_price_b, hold_b, ret_b, 'B_Connors'
            ))

        # ---- Strategy C: Enter at NEXT DAY OPEN, exit above SMA5 or 10d, catastrophic stop ----
        if idx + 1 < len(df):
            entry_price_c = df.iloc[idx + 1]['open']
            exit_price_c = None
            exit_idx_c = None

            for j in range(idx + 2, min(idx + 12, len(df))):
                day = df.iloc[j]
                if pd.notna(day['sma200']) and day['close'] < day['sma200']:
                    exit_price_c = day['close']
                    exit_idx_c = j
                    break
                if pd.notna(day['sma5']) and day['close'] > day['sma5']:
                    exit_price_c = day['close']
                    exit_idx_c = j
                    break
                if j == min(idx + 11, len(df) - 1):
                    exit_price_c = day['close']
                    exit_idx_c = j
                    break

            if exit_idx_c is not None:
                ret_c = ((exit_price_c - entry_price_c) / entry_price_c) * 100
                hold_c = (df.iloc[exit_idx_c]['date'] - df.iloc[idx + 1]['date']).days
                results['C_Improved'].append(TradeResult(
                    ticker, df.iloc[idx + 1]['date'], df.iloc[exit_idx_c]['date'],
                    entry_price_c, exit_price_c, hold_c, ret_c, 'C_Improved'
                ))

        # ---- Strategy D: Scaled entry (50% next day, 50% if RSI<5 in 2 days) ----
        if idx + 1 < len(df):
            entry_price_d1 = df.iloc[idx + 1]['open']
            entry_price_d2 = None

            for k in range(idx + 1, min(idx + 3, len(df))):
                day_k = df.iloc[k]
                if pd.notna(day_k['rsi2']) and day_k['rsi2'] < 5 and k + 1 < len(df):
                    entry_price_d2 = df.iloc[k + 1]['open']
                    break

            if entry_price_d2:
                avg_entry_d = (entry_price_d1 * 0.5 + entry_price_d2 * 0.5)
            else:
                avg_entry_d = entry_price_d1

            exit_price_d = None
            exit_idx_d = None
            start_d = idx + 3 if entry_price_d2 else idx + 2

            for j in range(start_d, min(idx + 12, len(df))):
                day = df.iloc[j]
                if pd.notna(day['sma200']) and day['close'] < day['sma200']:
                    exit_price_d = day['close']
                    exit_idx_d = j
                    break
                if pd.notna(day['sma5']) and day['close'] > day['sma5']:
                    exit_price_d = day['close']
                    exit_idx_d = j
                    break
                if j == min(idx + 11, len(df) - 1):
                    exit_price_d = day['close']
                    exit_idx_d = j
                    break

            if exit_idx_d is not None:
                ret_d = ((exit_price_d - avg_entry_d) / avg_entry_d) * 100
                hold_d = (df.iloc[exit_idx_d]['date'] - df.iloc[idx + 1]['date']).days
                results['D_Scaled'].append(TradeResult(
                    ticker, df.iloc[idx + 1]['date'], df.iloc[exit_idx_d]['date'],
                    avg_entry_d, exit_price_d, hold_d, ret_d, 'D_Scaled'
                ))

    return results


# ============================================================
# Display Functions
# ============================================================
def print_separator(char='=', width=120):
    print(char * width)


def print_metrics_table(metrics_list):
    """Print a comparison table of metrics."""
    headers = [
        ('Strategy', 'strategy', '{}'),
        ('Trades', 'total_trades', '{}'),
        ('Win Rate', 'win_rate', '{:.1f}%'),
        ('Avg Ret', 'avg_return', '{:+.2f}%'),
        ('Med Ret', 'median_return', '{:+.2f}%'),
        ('Avg Hold', 'avg_hold', '{:.1f}d'),
        ('P.Factor', 'profit_factor', '{:.2f}'),
        ('MaxCLoss', 'max_consec_loss', '{}'),
        ('Sharpe', 'sharpe_like', '{:.3f}'),
        ('Total Ret', 'total_return', '{:+.1f}%'),
        ('Best', 'best_trade', '{:+.1f}%'),
        ('Worst', 'worst_trade', '{:+.1f}%'),
    ]

    # Header
    header_str = ""
    for name, _, _ in headers:
        header_str += f"{name:>12}"
    print(header_str)
    print('-' * len(header_str))

    for m in metrics_list:
        row_str = ""
        for name, key, fmt in headers:
            val = m.get(key, 'N/A')
            if val == 'N/A' or (isinstance(val, (int, float)) and val == 0 and key in ['total_trades']):
                row_str += f"{'N/A':>12}"
            else:
                try:
                    row_str += f"{fmt.format(val):>12}"
                except:
                    row_str += f"{str(val):>12}"
        print(row_str)


def print_fee_adjusted_table(metrics_list):
    """Print fee-adjusted metrics."""
    headers = [
        ('Strategy', 'strategy', '{}'),
        ('Trades', 'total_trades', '{}'),
        ('WR (fee)', 'win_rate_fee_adj', '{:.1f}%'),
        ('Avg Ret', 'avg_return_fee_adj', '{:+.2f}%'),
        ('P.Factor', 'profit_factor_fee_adj', '{:.2f}'),
        ('Sharpe', 'sharpe_fee_adj', '{:.3f}'),
        ('Total Ret', 'total_return_fee_adj', '{:+.1f}%'),
    ]

    header_str = ""
    for name, _, _ in headers:
        header_str += f"{name:>14}"
    print(header_str)
    print('-' * len(header_str))

    for m in metrics_list:
        row_str = ""
        for name, key, fmt in headers:
            val = m.get(key, 'N/A')
            try:
                row_str += f"{fmt.format(val):>14}"
            except:
                row_str += f"{str(val):>14}"
        print(row_str)


def print_per_ticker_breakdown(all_trades_by_strategy):
    """Print per-ticker comparison."""
    # Gather all tickers that had trades
    all_tickers = set()
    for strat_trades in all_trades_by_strategy.values():
        for t in strat_trades:
            all_tickers.add(t.ticker)

    all_tickers = sorted(all_tickers)

    print(f"\n{'Ticker':>8}", end='')
    for strat in ['A_Current', 'B_Connors', 'C_Improved', 'D_Scaled']:
        print(f"  | {strat:>12} Trd  WR%  AvgR%", end='')
    print()
    print('-' * 140)

    for ticker in all_tickers:
        print(f"{ticker:>8}", end='')
        for strat in ['A_Current', 'B_Connors', 'C_Improved', 'D_Scaled']:
            ticker_trades = [t for t in all_trades_by_strategy.get(strat, []) if t.ticker == ticker]
            if ticker_trades:
                wr = len([t for t in ticker_trades if t.pct_return > 0]) / len(ticker_trades) * 100
                avg_r = np.mean([t.pct_return for t in ticker_trades])
                print(f"  | {strat:>12}  {len(ticker_trades):>2}  {wr:>4.0f}  {avg_r:>+5.1f}", end='')
            else:
                print(f"  | {strat:>12}   0    --    --", end='')
        print()


def print_trade_details(trades, label, max_trades=None):
    """Print individual trade details."""
    if not trades:
        print(f"  No trades for {label}")
        return

    sorted_trades = sorted(trades, key=lambda t: t.entry_date)
    if max_trades:
        sorted_trades = sorted_trades[:max_trades]

    print(f"  {'Ticker':>8} {'Entry Date':>12} {'Exit Date':>12} {'Entry$':>8} {'Exit$':>8} {'Hold':>5} {'Return':>8}")
    print(f"  {'-'*8} {'-'*12} {'-'*12} {'-'*8} {'-'*8} {'-'*5} {'-'*8}")

    for t in sorted_trades:
        entry_str = t.entry_date.strftime('%Y-%m-%d') if hasattr(t.entry_date, 'strftime') else str(t.entry_date)[:10]
        exit_str = t.exit_date.strftime('%Y-%m-%d') if hasattr(t.exit_date, 'strftime') else str(t.exit_date)[:10]
        win_marker = '+' if t.pct_return > 0 else '-' if t.pct_return < 0 else '='
        print(f"  {t.ticker:>8} {entry_str:>12} {exit_str:>12} {t.entry_price:>8.2f} {t.exit_price:>8.2f} {t.hold_days:>4}d {t.pct_return:>+7.2f}% {win_marker}")


# ============================================================
# Main
# ============================================================
def main():
    print_separator()
    print("  STRATEGY COMPARISON BACKTEST")
    print(f"  Run date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Fee assumption: {FEE_PCT:.2f}% per round-trip ($3 on $1,000)")
    print(f"  Tickers: {len(TICKERS)} stocks")
    print_separator()

    # ---- Load all data ----
    print("\n[1] Loading price data...")
    all_data = {}
    for ticker in TICKERS:
        df = load_data(ticker)
        if df is not None:
            all_data[ticker] = df
            print(f"    {ticker}: {len(df)} bars ({df['date'].iloc[0].strftime('%Y-%m-%d')} to {df['date'].iloc[-1].strftime('%Y-%m-%d')})")
        else:
            print(f"    {ticker}: SKIPPED (insufficient data)")

    print(f"\n  Loaded {len(all_data)} / {len(TICKERS)} tickers successfully")

    # ---- Run all strategies on all tickers ----
    print("\n[2] Running backtests on ALL signals across all tickers...")

    all_trades = {
        'A_Current': [],
        'B_Connors': [],
        'C_Improved': [],
        'D_Scaled': [],
    }

    strategy_funcs = {
        'A_Current': strategy_a_current,
        'B_Connors': strategy_b_connors,
        'C_Improved': strategy_c_improved,
        'D_Scaled': strategy_d_scaled,
    }

    for ticker, df in all_data.items():
        for strat_name, func in strategy_funcs.items():
            trades = func(df, ticker)
            all_trades[strat_name].extend(trades)

    # ---- Compute metrics ----
    print("\n" + "=" * 120)
    print("  PART 1: ALL SIGNALS BACKTEST (every RSI dip signal across all tickers)")
    print("=" * 120)

    all_metrics = []
    for strat_name in ['A_Current', 'B_Connors', 'C_Improved', 'D_Scaled']:
        m = compute_metrics(all_trades[strat_name], strat_name)
        all_metrics.append(m)

    print("\n  --- RAW METRICS (before fees) ---")
    print_metrics_table(all_metrics)

    print("\n  --- FEE-ADJUSTED METRICS ($3 round-trip / $1,000 position = 0.30%) ---")
    print_fee_adjusted_table(all_metrics)

    # ---- Per-ticker breakdown ----
    print("\n" + "=" * 120)
    print("  PER-TICKER BREAKDOWN")
    print("=" * 120)

    for strat_name in ['A_Current', 'B_Connors', 'C_Improved', 'D_Scaled']:
        trades = all_trades[strat_name]
        print(f"\n  --- {strat_name} ---")
        ticker_stats = defaultdict(list)
        for t in trades:
            ticker_stats[t.ticker].append(t.pct_return)

        print(f"  {'Ticker':>8} {'Trades':>7} {'WinRate':>8} {'AvgRet':>8} {'MedRet':>8} {'Best':>8} {'Worst':>8} {'TotalRet':>10}")
        print(f"  {'-'*8} {'-'*7} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")

        for ticker in sorted(ticker_stats.keys()):
            rets = ticker_stats[ticker]
            n = len(rets)
            wr = len([r for r in rets if r > 0]) / n * 100
            avg = np.mean(rets)
            med = np.median(rets)
            best = max(rets)
            worst = min(rets)
            total = sum(rets)
            print(f"  {ticker:>8} {n:>7} {wr:>7.1f}% {avg:>+7.2f}% {med:>+7.2f}% {best:>+7.1f}% {worst:>+7.1f}% {total:>+9.1f}%")

    # ---- Replay actual trades ----
    print("\n" + "=" * 120)
    print("  PART 2: REPLAY OF OUR ACTUAL 19 TRADE ENTRY DATES")
    print("  (What would each strategy have done if entered on the same dates?)")
    print("=" * 120)

    replay_results = replay_actual_trades(all_data)

    replay_metrics = []
    for strat_name in ['A_Current', 'B_Connors', 'C_Improved', 'D_Scaled']:
        m = compute_metrics(replay_results[strat_name], strat_name)
        replay_metrics.append(m)

    print("\n  --- RAW METRICS (on our actual entry dates) ---")
    print_metrics_table(replay_metrics)

    print("\n  --- FEE-ADJUSTED METRICS ---")
    print_fee_adjusted_table(replay_metrics)

    # ---- Trade-by-trade for replay ----
    for strat_name in ['A_Current', 'B_Connors', 'C_Improved', 'D_Scaled']:
        print(f"\n  --- {strat_name}: Trade-by-Trade on Our Entry Dates ---")
        print_trade_details(replay_results[strat_name], strat_name)

    # ---- Head-to-head comparison ----
    print("\n" + "=" * 120)
    print("  PART 3: HEAD-TO-HEAD COMPARISON SUMMARY")
    print("=" * 120)

    print("""
    Strategy Descriptions:
    =====================
    A) CURRENT (ATLAS V2.3): RSI(2)<20, Close>SMA50, Fixed 14-day hold, -8% stop
    B) CONNORS CLASSIC:      RSI(2)<10, Close>SMA200, Exit above SMA5, no stop, max 10d
    C) IMPROVED (Proposed):  RSI(2)<10, Close>SMA200, ADX<25, next-day-open entry,
                             exit above SMA5 or 10d max, catastrophic stop < SMA200
    D) SCALED ENTRY:         Same as C + scale in 50%+50% if RSI<5 within 2 days
    """)

    print("  ALL-SIGNALS COMPARISON (comprehensive backtest):")
    print(f"  {'Metric':<25}", end='')
    for m in all_metrics:
        print(f"  {m['strategy']:>14}", end='')
    print()
    print(f"  {'-'*25}", end='')
    for _ in all_metrics:
        print(f"  {'-'*14}", end='')
    print()

    comparison_rows = [
        ('Total Trades', 'total_trades', '{}'),
        ('Win Rate', 'win_rate', '{:.1f}%'),
        ('Avg Return/Trade', 'avg_return', '{:+.2f}%'),
        ('Median Return', 'median_return', '{:+.2f}%'),
        ('Avg Hold Period', 'avg_hold', '{:.1f} days'),
        ('Profit Factor', 'profit_factor', '{:.2f}'),
        ('Max Consec Losses', 'max_consec_loss', '{}'),
        ('Sharpe-like Ratio', 'sharpe_like', '{:.3f}'),
        ('Cumulative Return', 'total_return', '{:+.1f}%'),
        ('Best Single Trade', 'best_trade', '{:+.1f}%'),
        ('Worst Single Trade', 'worst_trade', '{:+.1f}%'),
        ('Fee-Adj Win Rate', 'win_rate_fee_adj', '{:.1f}%'),
        ('Fee-Adj Avg Return', 'avg_return_fee_adj', '{:+.2f}%'),
        ('Fee-Adj P.Factor', 'profit_factor_fee_adj', '{:.2f}'),
        ('Fee-Adj Total Ret', 'total_return_fee_adj', '{:+.1f}%'),
    ]

    for label, key, fmt in comparison_rows:
        print(f"  {label:<25}", end='')
        for m in all_metrics:
            val = m.get(key, 0)
            try:
                print(f"  {fmt.format(val):>14}", end='')
            except:
                print(f"  {str(val):>14}", end='')
        print()

    print("\n  OUR-TRADES REPLAY COMPARISON:")
    print(f"  {'Metric':<25}", end='')
    for m in replay_metrics:
        print(f"  {m['strategy']:>14}", end='')
    print()
    print(f"  {'-'*25}", end='')
    for _ in replay_metrics:
        print(f"  {'-'*14}", end='')
    print()

    for label, key, fmt in comparison_rows:
        print(f"  {label:<25}", end='')
        for m in replay_metrics:
            val = m.get(key, 0)
            try:
                print(f"  {fmt.format(val):>14}", end='')
            except:
                print(f"  {str(val):>14}", end='')
        print()

    # ---- Winner determination ----
    print("\n" + "=" * 120)
    print("  VERDICT & RECOMMENDATIONS")
    print("=" * 120)

    # Rank by fee-adjusted sharpe
    ranked_all = sorted(all_metrics, key=lambda m: m.get('sharpe_fee_adj', 0), reverse=True)
    ranked_replay = sorted(replay_metrics, key=lambda m: m.get('avg_return_fee_adj', 0), reverse=True)

    print("\n  Ranking by Fee-Adjusted Sharpe (ALL signals):")
    for i, m in enumerate(ranked_all, 1):
        print(f"    #{i}: {m['strategy']:>12} | Sharpe={m.get('sharpe_fee_adj',0):.3f} | WR={m['win_rate_fee_adj']:.1f}% | Avg={m['avg_return_fee_adj']:+.2f}% | Trades={m['total_trades']}")

    print("\n  Ranking by Fee-Adjusted Avg Return (OUR entry dates):")
    for i, m in enumerate(ranked_replay, 1):
        print(f"    #{i}: {m['strategy']:>12} | Avg={m.get('avg_return_fee_adj',0):+.2f}% | WR={m['win_rate_fee_adj']:.1f}% | Total={m.get('total_return_fee_adj',0):+.1f}% | Trades={m['total_trades']}")

    # Key insights
    print("\n  KEY INSIGHTS:")

    best_all = ranked_all[0]
    best_replay = ranked_replay[0]

    print(f"    - Best strategy (all signals): {best_all['strategy']} with Sharpe {best_all.get('sharpe_fee_adj',0):.3f}")
    print(f"    - Best strategy (our trades):  {best_replay['strategy']} with {best_replay.get('avg_return_fee_adj',0):+.2f}% avg return")

    # Compare current vs best
    current_all = next(m for m in all_metrics if m['strategy'] == 'A_Current')
    if best_all['strategy'] != 'A_Current':
        wr_diff = best_all['win_rate_fee_adj'] - current_all['win_rate_fee_adj']
        ret_diff = best_all['avg_return_fee_adj'] - current_all['avg_return_fee_adj']
        print(f"    - vs Current: {wr_diff:+.1f}% WR improvement, {ret_diff:+.2f}% avg return improvement")
    else:
        print(f"    - Current strategy is already the best by Sharpe ratio!")

    # SMA50 vs SMA200 insight
    a_wr = current_all['win_rate']
    b_wr = next(m for m in all_metrics if m['strategy'] == 'B_Connors')['win_rate']
    print(f"    - SMA50 filter (A) WR: {a_wr:.1f}% vs SMA200 filter (B) WR: {b_wr:.1f}%")

    # RSI threshold insight
    a_trades = current_all['total_trades']
    b_trades = next(m for m in all_metrics if m['strategy'] == 'B_Connors')['total_trades']
    print(f"    - RSI<20 generates {a_trades} signals vs RSI<10 generates {b_trades} signals ({a_trades-b_trades} more trades with looser filter)")

    # Hold period insight
    a_hold = current_all['avg_hold']
    b_hold = next(m for m in all_metrics if m['strategy'] == 'B_Connors')['avg_hold']
    c_hold = next(m for m in all_metrics if m['strategy'] == 'C_Improved')['avg_hold']
    print(f"    - Avg hold: A={a_hold:.1f}d, B={b_hold:.1f}d, C={c_hold:.1f}d (shorter = faster capital rotation)")

    # Profit factor comparison
    for m in all_metrics:
        pf = m.get('profit_factor_fee_adj', 0)
        quality = "EXCELLENT" if pf > 2.0 else "GOOD" if pf > 1.5 else "ACCEPTABLE" if pf > 1.0 else "POOR"
        print(f"    - {m['strategy']} Profit Factor (fee-adj): {pf:.2f} ({quality})")

    print("\n" + "=" * 120)
    print("  END OF BACKTEST REPORT")
    print("=" * 120)


if __name__ == '__main__':
    main()
