"""
ATLAS V2.0 - Research-Backed Trading Model
==========================================

Based on 2024-2025 academic research:
- Jha et al. (2025): RL with triple-indicator achieved 85.4% accuracy
- QuantifiedStrategies: RSI(2) mean reversion 91% win rate
- arXiv 2024: Thompson Sampling with ε-greedy for parameter optimization
- QuantInsti: Walk-forward validation (WFE > 50% required)
- ScienceDirect 2024: Multi-factor confirmation improves reliability

Key Principles:
1. ENTRY: Multi-factor confirmation (RSI + Trend + Volume)
2. EXIT: Time-based exits outperform trailing stops
3. LEARNING: Thompson Sampling with exponential decay
4. VALIDATION: Walk-forward with overfitting detection
"""

from .model import ATLASV2Model
from .entry import EntryEngine, EntrySignal
from .exit import ExitEngine, ExitSignal
from .regime import RegimeDetector, MarketRegime
from .learner import ThompsonSamplingLearner
from .validator import WalkForwardValidator

__all__ = [
    'ATLASV2Model',
    'EntryEngine',
    'ExitEngine',
    'RegimeDetector',
    'ThompsonSamplingLearner',
    'WalkForwardValidator',
]

__version__ = "2.0.0"
