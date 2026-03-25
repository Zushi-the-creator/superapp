"""
ATLAS Strategy QA V2 — Comprehensive Consistency & Regression Tests
====================================================================
Validates that ALL components of the trading system are aligned with V2.6 rules.

Tests:
  1. RSI threshold consistency (< 10 everywhere)
  2. Hold period consistency (30d everywhere)
  3. Next-day open entry (no look-ahead bias)
  4. Fee deduction (0.30% everywhere)
  5. Overlap prevention in backtests
  6. VETO filter alignment (scanner vs api_v2)
  7. Market regime gate (SPY 5d < -1% = pause)
  8. Exit strategy (Fixed30d, no stops/targets)
  9. Backtest accuracy (cross-validate scanner vs model.py)
  10. Zone WR threshold (65% not 55%)

Usage:
    python3 strategy_qa_v2.py              # Run all tests
    python3 strategy_qa_v2.py --verbose    # Show details
    python3 strategy_qa_v2.py --test 3     # Run specific test
"""

import sys
import os
import re
import ast
import json
import math
import random
import inspect
import argparse
from datetime import datetime
from typing import List, Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ─── Test Infrastructure ─────────────────────────────────────────────────────

class QAResult:
    def __init__(self, name: str, passed: bool, detail: str = "", severity: str = "ERROR"):
        self.name = name
        self.passed = passed
        self.detail = detail
        self.severity = severity  # ERROR, WARNING, INFO

    def __str__(self):
        icon = "PASS" if self.passed else f"FAIL [{self.severity}]"
        s = f"  [{icon}] {self.name}"
        if self.detail and not self.passed:
            s += f"\n         {self.detail}"
        return s


class QASuite:
    def __init__(self, verbose: bool = False):
        self.results: List[QAResult] = []
        self.verbose = verbose

    def check(self, name: str, condition: bool, detail: str = "", severity: str = "ERROR"):
        r = QAResult(name, condition, detail, severity)
        self.results.append(r)
        if self.verbose or not condition:
            print(r)
        return condition

    def summary(self):
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        errors = sum(1 for r in self.results if not r.passed and r.severity == "ERROR")
        warnings = sum(1 for r in self.results if not r.passed and r.severity == "WARNING")
        total = len(self.results)
        print(f"\n{'='*70}")
        print(f"  QA SUMMARY: {passed}/{total} passed | {errors} errors | {warnings} warnings")
        print(f"{'='*70}")
        if failed:
            print("\n  FAILURES:")
            for r in self.results:
                if not r.passed:
                    print(f"    {r}")
        return errors == 0  # True if no errors (warnings OK)


# ─── Source Code Scanning Utilities ───────────────────────────────────────────

def _read_file(path: str) -> str:
    """Read file contents, return empty string if missing."""
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _find_pattern(source: str, pattern: str) -> List[Tuple[int, str]]:
    """Find regex pattern in source, return list of (line_num, matched_line)."""
    matches = []
    for i, line in enumerate(source.split("\n"), 1):
        if re.search(pattern, line):
            matches.append((i, line.strip()))
    return matches


_BASE = os.path.dirname(os.path.abspath(__file__))


# ─── Test 1: RSI Threshold Consistency ────────────────────────────────────────

def test_rsi_threshold(qa: QASuite):
    """Verify RSI(2) < 10 is used consistently across all entry paths."""
    print("\n[TEST 1] RSI Threshold Consistency (must be < 10 everywhere)")
    print("-" * 60)

    files_to_check = {
        "entry.py": os.path.join(_BASE, "atlas_v2", "entry.py"),
        "model.py": os.path.join(_BASE, "atlas_v2", "model.py"),
        "validator.py": os.path.join(_BASE, "atlas_v2", "validator.py"),
        "deep_scanner.py": os.path.join(_BASE, "deep_scanner.py"),
        "strategy_qa.py": os.path.join(_BASE, "strategy_qa.py"),
        "portfolio_check.py": os.path.join(_BASE, "portfolio_check.py"),
        "api_v2.py": os.path.join(_BASE, "api_v2.py"),
    }

    for name, path in files_to_check.items():
        src = _read_file(path)
        if not src:
            qa.check(f"RSI threshold: {name} exists", False, "File not found")
            continue

        # Check for RSI < 50 (the old bug) in backtest contexts
        bad = _find_pattern(src, r"rsi.*<\s*50.*sma")
        qa.check(
            f"RSI threshold: {name} has no RSI<50 in backtest",
            len(bad) == 0,
            f"Found RSI<50: {bad[:3]}" if bad else ""
        )

        # Check for regime-dependent RSI thresholds in backtest (rsi_threshold from params)
        if name in ("model.py", "validator.py"):
            bad2 = _find_pattern(src, r"rsi_threshold|regime_params\[.rsi")
            qa.check(
                f"RSI threshold: {name} uses fixed < 10 (no regime params)",
                len(bad2) == 0,
                f"Uses regime-dependent RSI: {bad2[:3]}" if bad2 else "",
                "WARNING"
            )


# ─── Test 2: Hold Period Consistency ──────────────────────────────────────────

def test_hold_period(qa: QASuite):
    """Verify Fixed30d hold is used consistently."""
    print("\n[TEST 2] Hold Period Consistency (must be 30d everywhere)")
    print("-" * 60)

    # model.py backtest
    src = _read_file(os.path.join(_BASE, "atlas_v2", "model.py"))
    qa.check(
        "Hold period: model.py uses 30d",
        "_HOLD_DAYS = 30" in src or "forward_days = 30" in src,
        "Expected _HOLD_DAYS = 30 in backtest()"
    )
    qa.check(
        "Hold period: model.py no 7d forward",
        "forward_days = 7" not in src,
        "Old 7-day forward still present"
    )

    # validator.py
    src = _read_file(os.path.join(_BASE, "atlas_v2", "validator.py"))
    qa.check(
        "Hold period: validator.py uses 30d",
        "FORWARD_RETURN_DAYS = 30" in src,
        "Expected FORWARD_RETURN_DAYS = 30"
    )

    # strategy_qa.py
    src = _read_file(os.path.join(_BASE, "strategy_qa.py"))
    qa.check(
        "Hold period: strategy_qa.py uses 30d",
        "HOLD_DAYS = 30" in src,
        "Expected HOLD_DAYS = 30"
    )

    # deep_scanner.py
    src = _read_file(os.path.join(_BASE, "deep_scanner.py"))
    qa.check(
        "Hold period: deep_scanner.py uses 30d",
        "fwd = 30" in src or "hold_days = 30" in src or "_hold_days" in src,
        "Expected 30-day hold in backtest"
    )

    # exit.py
    src = _read_file(os.path.join(_BASE, "atlas_v2", "exit.py"))
    qa.check(
        "Hold period: exit.py uses Fixed30d",
        "HOLD_DAYS = 30" in src,
        "Expected HOLD_DAYS = 30 in ExitEngine"
    )


# ─── Test 3: Next-Day Open Entry ─────────────────────────────────────────────

def test_next_day_open(qa: QASuite):
    """Verify backtests use next-day open (not same-bar close = look-ahead bias)."""
    print("\n[TEST 3] Next-Day Open Entry (no look-ahead bias)")
    print("-" * 60)

    for name, path in [
        ("model.py", os.path.join(_BASE, "atlas_v2", "model.py")),
        ("validator.py", os.path.join(_BASE, "atlas_v2", "validator.py")),
    ]:
        src = _read_file(path)
        # Check for next-day open pattern
        has_next_day = bool(re.search(r"history\[i\s*\+\s*1\].*open|opens\[i\s*\+\s*1\]|opens_list\[i\s*\+\s*1\]", src))
        # Check for same-bar close entry (the bug)
        has_same_bar = bool(re.search(r"entry_price\s*=\s*history\[i\]\[.close.\]", src))
        qa.check(
            f"Next-day open: {name} uses i+1 open",
            has_next_day,
            "No next-day open entry found in backtest"
        )
        qa.check(
            f"Next-day open: {name} no same-bar close entry",
            not has_same_bar,
            "Same-bar close entry found (look-ahead bias)"
        )


# ─── Test 4: Fee Deduction ───────────────────────────────────────────────────

def test_fee_deduction(qa: QASuite):
    """Verify 0.30% fee is deducted in all backtests."""
    print("\n[TEST 4] Fee Deduction (0.30% in all backtests)")
    print("-" * 60)

    for name, path in [
        ("model.py", os.path.join(_BASE, "atlas_v2", "model.py")),
        ("validator.py", os.path.join(_BASE, "atlas_v2", "validator.py")),
        ("strategy_qa.py", os.path.join(_BASE, "strategy_qa.py")),
        ("deep_scanner.py", os.path.join(_BASE, "deep_scanner.py")),
        ("portfolio_check.py", os.path.join(_BASE, "portfolio_check.py")),
    ]:
        src = _read_file(path)
        has_fee = bool(re.search(r"FEE_PCT\s*=\s*0\.30|_FEE_PCT\s*=\s*0\.30|fee.*0\.30", src, re.IGNORECASE))
        qa.check(
            f"Fee deduction: {name} has 0.30% fee",
            has_fee,
            "No 0.30% fee deduction found"
        )


# ─── Test 5: Overlap Prevention ──────────────────────────────────────────────

def test_overlap_prevention(qa: QASuite):
    """Verify non-overlapping trades in all backtests."""
    print("\n[TEST 5] Overlap Prevention (non-overlapping trades)")
    print("-" * 60)

    for name, path in [
        ("model.py", os.path.join(_BASE, "atlas_v2", "model.py")),
        ("validator.py", os.path.join(_BASE, "atlas_v2", "validator.py")),
        ("strategy_qa.py", os.path.join(_BASE, "strategy_qa.py")),
        ("deep_scanner.py", os.path.join(_BASE, "deep_scanner.py")),
        ("portfolio_check.py", os.path.join(_BASE, "portfolio_check.py")),
    ]:
        src = _read_file(path)
        has_overlap = bool(re.search(
            r"last_exit|non_overlapping|overlap|last_exit_day|last_exit_idx|zone_last_exit",
            src
        ))
        qa.check(
            f"Overlap prevention: {name}",
            has_overlap,
            "No overlap prevention found in backtest loop"
        )


# ─── Test 6: VETO Filter Alignment ───────────────────────────────────────────

def test_veto_alignment(qa: QASuite):
    """Verify VETO filters are consistent between scanner and api_v2."""
    print("\n[TEST 6] VETO Filter Alignment (scanner vs api_v2)")
    print("-" * 60)

    api_src = _read_file(os.path.join(_BASE, "api_v2.py"))
    scanner_src = _read_file(os.path.join(_BASE, "deep_scanner.py"))

    # 1. Sentiment threshold -0.3
    qa.check(
        "VETO: api_v2 sentiment threshold -0.3",
        bool(re.search(r"sentiment.*<\s*-0\.3", api_src)),
        "Sentiment threshold != -0.3"
    )
    qa.check(
        "VETO: scanner sentiment threshold -0.3",
        bool(re.search(r"sentiment.*<\s*-0\.3", scanner_src)),
        "Sentiment threshold != -0.3"
    )

    # 2. Analyst Hold/Sell VETO
    qa.check(
        "VETO: api_v2 analyst Hold/Sell",
        bool(re.search(r"Hold.*Sell.*Underperform", api_src)),
        "Missing analyst VETO for Hold/Sell"
    )
    qa.check(
        "VETO: scanner analyst Hold/Sell",
        bool(re.search(r"Hold.*Sell.*Underperform", scanner_src)),
        "Missing analyst VETO for Hold/Sell"
    )

    # 3. Zone WR threshold 65%
    qa.check(
        "VETO: api_v2 zone WR threshold >= 65%",
        bool(re.search(r"bayes.*<\s*65|zone.*wr.*<\s*65", api_src, re.IGNORECASE)),
        "Zone WR threshold should be 65% (CLAUDE.md)"
    )

    # 4. Score < 3.0
    qa.check(
        "VETO: api_v2 score < 3.0",
        bool(re.search(r"score\s*<\s*3\.0", api_src)),
        "Missing score < 3.0 VETO"
    )

    # 5. Price < $10
    for name, src in [("api_v2", api_src), ("scanner", scanner_src)]:
        qa.check(
            f"VETO: {name} price < $10",
            bool(re.search(r"price\s*<\s*10", src)),
            "Missing price < $10 filter"
        )

    # 6. Earnings within 7 days
    for name, src in [("api_v2", api_src), ("scanner", scanner_src)]:
        qa.check(
            f"VETO: {name} earnings check",
            bool(re.search(r"earnings|EARNINGS", src)),
            "Missing earnings within 7d VETO"
        )


# ─── Test 7: Market Regime Gate ───────────────────────────────────────────────

def test_market_regime_gate(qa: QASuite):
    """Verify market regime gate pauses entries when SPY 5d < -1%."""
    print("\n[TEST 7] Market Regime Gate (SPY 5d < -1% = pause)")
    print("-" * 60)

    src = _read_file(os.path.join(_BASE, "api_v2.py"))

    qa.check(
        "Regime gate: _check_market_regime exists",
        "_check_market_regime" in src,
        "Function missing"
    )

    qa.check(
        "Regime gate: pause_entries = True when declining",
        bool(re.search(r'pause_entries.*=\s*True', src)),
        "pause_entries never set to True"
    )

    qa.check(
        "Regime gate: SPY 5d < -1% triggers pause",
        bool(re.search(r'spy_ret\s*<\s*-1', src)),
        "Missing SPY 5d < -1% check"
    )


# ─── Test 8: Exit Strategy ───────────────────────────────────────────────────

def test_exit_strategy(qa: QASuite):
    """Verify exit.py uses Fixed30d and no stops/targets."""
    print("\n[TEST 8] Exit Strategy (Fixed30d, no stops/targets)")
    print("-" * 60)

    src = _read_file(os.path.join(_BASE, "atlas_v2", "exit.py"))

    qa.check(
        "Exit: HOLD_DAYS = 30",
        "HOLD_DAYS = 30" in src,
        "Expected HOLD_DAYS = 30"
    )

    # Should NOT have regime-dependent stop/target params
    has_regime_params = bool(re.search(
        r"exit_params\s*=\s*\{.*MarketRegime\.BULL.*stop_loss_pct",
        src, re.DOTALL
    ))
    qa.check(
        "Exit: no regime-dependent stop/target params",
        not has_regime_params,
        "Old regime-based stop/target params still present"
    )

    # Should have earnings/sentiment early exit
    qa.check(
        "Exit: earnings early exit trigger",
        "earnings_within_7d" in src,
        "Missing earnings early exit parameter"
    )
    qa.check(
        "Exit: sentiment early exit trigger",
        "negative_sentiment" in src,
        "Missing sentiment early exit parameter"
    )


# ─── Test 9: Backtest Cross-Validation ───────────────────────────────────────

def test_backtest_cross_validation(qa: QASuite):
    """Cross-validate backtests between model.py, strategy_qa.py, and deep_scanner."""
    print("\n[TEST 9] Backtest Cross-Validation")
    print("-" * 60)

    try:
        from data_cache import DataCache
        from atlas_v2.entry import EntryEngine
        from atlas_v2.model import ATLASV2Model
    except ImportError as e:
        qa.check("Backtest cross-validation: imports", False, str(e))
        return

    cache = DataCache()
    entry = EntryEngine()

    # Pick a well-known stock for cross-validation
    test_tickers = ["AAPL", "MSFT", "NVDA"]
    for ticker in test_tickers:
        df = cache.get(ticker, 1260)
        if df is None or len(df) < 100:
            continue

        closes = df["Close"].dropna().tolist()
        opens = df["Open"].tolist() if "Open" in df.columns else closes

        if len(closes) < 82:
            continue

        # Method A: Direct backtest (same as strategy_qa.py / deep_scanner)
        trades_direct = []
        last_exit = -1
        for i in range(50, len(closes) - 31):
            if i <= last_exit:
                continue
            rsi = entry.calc_rsi(closes[:i+1], 2)
            sma = entry.calc_sma(closes[:i+1], 50)
            if rsi < 10 and closes[i] > sma:
                ep = opens[i+1] if i+1 < len(opens) and opens[i+1] > 0 else closes[i]
                xp = closes[i+1+30]
                ret = ((xp - ep) / ep) * 100 - 0.30
                trades_direct.append(ret)
                last_exit = i + 1 + 30

        # Method B: model.py backtest
        history = []
        for idx in range(len(closes)):
            history.append({
                'date': f'day_{idx}',
                'close': closes[idx],
                'open': opens[idx] if idx < len(opens) else closes[idx],
                'high': df['High'].tolist()[idx] if 'High' in df.columns and idx < len(df) else closes[idx],
                'low': df['Low'].tolist()[idx] if 'Low' in df.columns and idx < len(df) else closes[idx],
                'volume': df['Volume'].tolist()[idx] if 'Volume' in df.columns and idx < len(df) else 0,
            })

        model = ATLASV2Model()
        model_result = model.backtest(history, ticker)
        trades_model = model_result.get('trades', 0)

        # They should produce same trade count (± 1 for edge cases)
        diff = abs(len(trades_direct) - trades_model)
        qa.check(
            f"Cross-validate {ticker}: trade count match ({len(trades_direct)} vs {trades_model})",
            diff <= 1,
            f"Direct={len(trades_direct)}, Model={trades_model}, diff={diff}"
        )

        if trades_direct and trades_model > 0:
            wr_direct = sum(1 for r in trades_direct if r > 0) / len(trades_direct) * 100
            wr_model = model_result.get('win_rate', 0)
            wr_diff = abs(wr_direct - wr_model)
            qa.check(
                f"Cross-validate {ticker}: WR match ({wr_direct:.1f}% vs {wr_model:.1f}%)",
                wr_diff < 5,
                f"WR gap: {wr_diff:.1f}%"
            )

        break  # One stock is enough for regression test

    cache.close()


# ─── Test 10: Entry Engine Functional Test ────────────────────────────────────

def test_entry_engine_functional(qa: QASuite):
    """Verify entry engine correctly rejects RSI >= 10 and accepts RSI < 10."""
    print("\n[TEST 10] Entry Engine Functional Test")
    print("-" * 60)

    from atlas_v2.entry import EntryEngine, SignalType

    engine = EntryEngine()

    # Generate synthetic price data: strong uptrend, small 2-day dip that stays above SMA50
    # SMA50 of [100..130] ≈ 115. Price at end needs to stay > 115 after dip.
    base = 100.0
    closes = [base + i * 0.5 for i in range(200)]  # Long uptrend → SMA50 is well below
    # Small 2-day dip at end (drives RSI(2) to 0, but stays above SMA50)
    closes[-2] = closes[-3] * 0.97  # -3%
    closes[-1] = closes[-2] * 0.97  # -3% more

    rsi2 = engine.calc_rsi(closes, 2)
    sma50 = engine.calc_sma(closes, 50)
    price = closes[-1]

    qa.check(
        "Entry engine: synthetic data valid (RSI<10, above SMA50)",
        rsi2 < 10 and price > sma50,
        f"RSI={rsi2:.1f}, price={price:.1f}, SMA50={sma50:.1f}",
        "WARNING"
    )

    if rsi2 < 10 and price > sma50:
        signal = engine.generate_signal(closes)
        qa.check(
            "Entry engine: RSI<10 + above SMA50 = BUY",
            signal.signal == SignalType.BUY,
            f"Expected BUY, got {signal.signal.value} (RSI={rsi2:.1f}, score={signal.score})"
        )


    # Test that RSI=50 is rejected
    flat_closes = [100.0] * 60
    signal2 = engine.generate_signal(flat_closes)
    qa.check(
        "Entry engine: RSI~50 rejected (not oversold)",
        signal2.signal != SignalType.BUY,
        f"Expected HOLD, got {signal2.signal.value}"
    )

    # Test that below SMA50 is rejected
    down_closes = [100 - i * 0.5 for i in range(60)]
    down_closes[-2] = down_closes[-3] - 5
    down_closes[-1] = down_closes[-2] - 3
    signal3 = engine.generate_signal(down_closes)
    qa.check(
        "Entry engine: below SMA50 rejected",
        signal3.signal != SignalType.BUY,
        f"Expected HOLD, got {signal3.signal.value}"
    )


# ─── Test 11: Exit Engine Functional Test ─────────────────────────────────────

def test_exit_engine_functional(qa: QASuite):
    """Verify exit engine uses Fixed30d and respects early exit triggers."""
    print("\n[TEST 11] Exit Engine Functional Test")
    print("-" * 60)

    from atlas_v2.exit import ExitEngine, ExitAction

    engine = ExitEngine()

    closes = [100.0] * 60

    # Day 15: should HOLD (not yet 30 days)
    sig = engine.get_exit_signal(100, 105, 15, closes)
    qa.check(
        "Exit engine: day 15 = HOLD",
        sig.action == ExitAction.HOLD,
        f"Expected HOLD, got {sig.action.value}"
    )

    # Day 30: should exit (Fixed30d)
    sig2 = engine.get_exit_signal(100, 95, 30, closes)
    qa.check(
        "Exit engine: day 30 = SELL_TIME",
        sig2.action == ExitAction.SELL_TIME,
        f"Expected SELL_TIME, got {sig2.action.value}"
    )

    # Day 10 + earnings = early exit
    sig3 = engine.get_exit_signal(100, 102, 10, closes, earnings_within_7d=True)
    qa.check(
        "Exit engine: earnings = early exit",
        sig3.action != ExitAction.HOLD,
        f"Expected exit, got {sig3.action.value}"
    )

    # Day 10 + negative sentiment = early exit
    sig4 = engine.get_exit_signal(100, 98, 10, closes, negative_sentiment=True)
    qa.check(
        "Exit engine: negative sentiment = early exit",
        sig4.action != ExitAction.HOLD,
        f"Expected exit, got {sig4.action.value}"
    )

    # Day 5, profitable, no triggers = HOLD (V2.6: no profit targets!)
    sig5 = engine.get_exit_signal(100, 115, 5, closes)
    qa.check(
        "Exit engine: +15% at day 5 = HOLD (no profit target)",
        sig5.action == ExitAction.HOLD,
        f"Expected HOLD (no profit target in V2.6), got {sig5.action.value}"
    )

    # Day 5, -20% loss, no triggers = HOLD (V2.6: no stop losses!)
    sig6 = engine.get_exit_signal(100, 80, 5, closes)
    qa.check(
        "Exit engine: -20% at day 5 = HOLD (no stop loss)",
        sig6.action == ExitAction.HOLD,
        f"Expected HOLD (no stop loss in V2.6), got {sig6.action.value}"
    )


# ─── Test 12: RSI Calculation Consistency ─────────────────────────────────────

def test_rsi_calculation(qa: QASuite):
    """Verify RSI(2) gives same values in entry.py vs deep_scanner."""
    print("\n[TEST 12] RSI Calculation Consistency")
    print("-" * 60)

    from atlas_v2.entry import EntryEngine

    engine = EntryEngine()

    # Test with known data
    # After a 2-day drop from 100 to 90 to 85:
    closes = [100] * 50 + [100, 90, 85]
    rsi_entry = engine.calc_rsi(closes, 2)

    # Verify it's oversold (< 10)
    qa.check(
        "RSI calc: 2-day drop produces RSI < 10",
        rsi_entry < 10,
        f"RSI={rsi_entry:.1f} after 10% + 5.6% drop (expected < 10)"
    )

    # After flat: RSI is 100 (0 losses → avg_loss=0 → RS=inf → RSI=100)
    # This is mathematically correct. Wilder's formula: no losses = maximum strength.
    flat = [100] * 60
    rsi_flat = engine.calc_rsi(flat, 2)
    qa.check(
        "RSI calc: flat prices = RSI 100 (no losses)",
        rsi_flat == 100,
        f"RSI={rsi_flat:.1f} for flat prices (expected 100, no losses)"
    )

    # After 2-day rally: RSI should be > 90
    up = [100] * 50 + [100, 110, 120]
    rsi_up = engine.calc_rsi(up, 2)
    qa.check(
        "RSI calc: 2-day rally = RSI > 90",
        rsi_up > 90,
        f"RSI={rsi_up:.1f} after rally (expected > 90)"
    )


# ─── Main Runner ─────────────────────────────────────────────────────────────

ALL_TESTS = [
    (1, "RSI Threshold", test_rsi_threshold),
    (2, "Hold Period", test_hold_period),
    (3, "Next-Day Open", test_next_day_open),
    (4, "Fee Deduction", test_fee_deduction),
    (5, "Overlap Prevention", test_overlap_prevention),
    (6, "VETO Alignment", test_veto_alignment),
    (7, "Market Regime Gate", test_market_regime_gate),
    (8, "Exit Strategy", test_exit_strategy),
    (9, "Backtest Cross-Validation", test_backtest_cross_validation),
    (10, "Entry Engine Functional", test_entry_engine_functional),
    (11, "Exit Engine Functional", test_exit_engine_functional),
    (12, "RSI Calculation", test_rsi_calculation),
]


def main():
    parser = argparse.ArgumentParser(description="ATLAS Strategy QA V2")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--test", "-t", type=int, help="Run specific test number")
    args = parser.parse_args()

    print("=" * 70)
    print("  ATLAS STRATEGY QA V2 — Comprehensive Consistency Tests")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    qa = QASuite(verbose=args.verbose)

    tests_to_run = ALL_TESTS
    if args.test:
        tests_to_run = [(n, name, fn) for n, name, fn in ALL_TESTS if n == args.test]
        if not tests_to_run:
            print(f"Test {args.test} not found. Available: 1-{len(ALL_TESTS)}")
            return

    for num, name, fn in tests_to_run:
        try:
            fn(qa)
        except Exception as e:
            qa.check(f"Test {num} ({name}): no crash", False, str(e))

    all_pass = qa.summary()
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
