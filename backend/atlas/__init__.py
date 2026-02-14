"""
ATLAS: Adaptive Trading Learning and Signal System
===================================================

Unified trading model consolidating 30+ models into one adaptive system.
Target: 3% monthly returns with controlled risk.

Components:
- indicators: Technical analysis calculations (RSI, SMA, EMA, BB, ATR)
- regime: Market regime detection (BULL, BEAR, SIDEWAYS, HIGH_VOL)
- entry: Unified entry signal generation
- exits: Adaptive exit strategies (mechanical vs quick-sell)
- sizing: Kelly Criterion position sizing
- learning: Thompson Sampling continuous improvement
- database: Single SQLite for all data
- backtest: Walk-forward validation

Usage:
    from atlas import ATLASModel

    model = ATLASModel()
    signal = model.analyze(ticker, closes, volumes)

    if signal.action == "BUY":
        size = model.get_position_size(account_value, signal)

Author: Claude Trading Assistant
Version: 1.0.0
Created: 2026-01-30
"""

from .core import ATLASModel
from .database import ATLASDatabase
from .indicators import Indicators
from .regime import RegimeDetector, MarketRegime
from .entry import EntrySignal
from .exits import ExitSystem, ExitSignal
from .sizing import PositionSizer
from .learning import LearningEngine

__version__ = "1.0.0"
__all__ = [
    "ATLASModel",
    "ATLASDatabase",
    "Indicators",
    "RegimeDetector",
    "MarketRegime",
    "EntrySignal",
    "ExitSystem",
    "ExitSignal",
    "PositionSizer",
    "LearningEngine",
]
