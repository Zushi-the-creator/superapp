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

from .model import ATLASV2Model, AnalysisResult
from .entry import EntryEngine, EntrySignal, SignalType, SignalStrength, SignalWarning
from .exit import ExitEngine, ExitSignal
from .regime import RegimeDetector, MarketRegime
from .learner import ThompsonSamplingLearner
from .validator import WalkForwardValidator
from .sector_strategies import SectorStrategyEngine, Sector, StrategyType
from .sentiment_analyst import CombinedScorer, SentimentAnalyzer, AnalystIntegration
from .expert_analyst import ExpertAnalyst, StockAnalysis, PortfolioAction, create_expert_analyst

__all__ = [
    'ATLASV2Model',
    'AnalysisResult',
    'EntryEngine',
    'EntrySignal',
    'SignalType',
    'SignalStrength',
    'SignalWarning',
    'ExitEngine',
    'ExitSignal',
    'RegimeDetector',
    'MarketRegime',
    'ThompsonSamplingLearner',
    'WalkForwardValidator',
    'SectorStrategyEngine',
    'Sector',
    'StrategyType',
    'CombinedScorer',
    'SentimentAnalyzer',
    'AnalystIntegration',
    'ExpertAnalyst',
    'StockAnalysis',
    'PortfolioAction',
    'create_expert_analyst',
]

__version__ = "2.0.0"
