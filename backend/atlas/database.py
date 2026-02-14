"""
ATLAS Database Module
======================

Single SQLite database for all ATLAS data:
- trades: Every trade with full context and outcome
- parameters: Learned parameters per regime
- regime_performance: Rolling performance metrics
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict


@dataclass
class TradeRecord:
    """Record of a completed trade"""
    ticker: str
    signal: str  # BUY
    entry_date: str
    entry_price: float
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    return_pct: Optional[float] = None
    was_correct: Optional[bool] = None
    regime: str = "SIDEWAYS"
    rsi2_at_entry: Optional[float] = None
    rsi14_at_entry: Optional[float] = None
    volume_ratio: Optional[float] = None
    exit_reason: Optional[str] = None
    holding_days: Optional[int] = None
    position_size: Optional[float] = None
    transaction_cost: float = 3.0  # Round-trip


class ATLASDatabase:
    """
    Single source of truth for all ATLAS data.

    Tables:
    - trades: Complete trade history with outcomes
    - parameters: Regime-specific learned parameters
    - regime_performance: Rolling performance by regime
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), "atlas.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database schema"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Trades table - every trade with full context
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    entry_date TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_date TEXT,
                    exit_price REAL,
                    return_pct REAL,
                    was_correct INTEGER,
                    regime TEXT NOT NULL,
                    rsi2_at_entry REAL,
                    rsi14_at_entry REAL,
                    volume_ratio REAL,
                    exit_reason TEXT,
                    holding_days INTEGER,
                    position_size REAL,
                    transaction_cost REAL DEFAULT 3.0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Parameters table - learned values per regime
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS parameters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    regime TEXT NOT NULL,
                    param_name TEXT NOT NULL,
                    param_value REAL NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    samples INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    UNIQUE(regime, param_name)
                )
            """)

            # Regime performance - rolling metrics
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS regime_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    regime TEXT NOT NULL,
                    window_end TEXT NOT NULL,
                    total_trades INTEGER,
                    wins INTEGER,
                    win_rate REAL,
                    avg_return REAL,
                    avg_holding_days REAL,
                    best_rsi2_threshold REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Indices for fast lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_regime ON trades(regime)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(entry_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_params_regime ON parameters(regime)")

            conn.commit()

            # Initialize default parameters if not exist
            self._init_default_parameters(cursor)
            conn.commit()

    def _init_default_parameters(self, cursor):
        """Initialize default parameters for each regime"""
        defaults = {
            "BULL": {
                "rsi2_buy": 25.0,
                "rsi2_sell": 95.0,
                "stop_loss_pct": 8.0,
                "profit_target_pct": 10.0,
                "trailing_stop_pct": 10.0,
            },
            "BEAR": {
                "rsi2_buy": 10.0,
                "rsi2_sell": 85.0,
                "stop_loss_pct": 4.0,
                "profit_target_pct": 3.0,
                "trailing_stop_pct": 5.0,
            },
            "SIDEWAYS": {
                "rsi2_buy": 20.0,
                "rsi2_sell": 90.0,
                "stop_loss_pct": 5.0,
                "profit_target_pct": 5.0,
                "trailing_stop_pct": 8.0,
            },
            "HIGH_VOL": {
                "rsi2_buy": 15.0,
                "rsi2_sell": 90.0,
                "stop_loss_pct": 4.0,
                "profit_target_pct": 4.0,
                "trailing_stop_pct": 6.0,
            },
        }

        now = datetime.now().isoformat()
        for regime, params in defaults.items():
            for param_name, param_value in params.items():
                cursor.execute("""
                    INSERT OR IGNORE INTO parameters (regime, param_name, param_value, confidence, samples, updated_at)
                    VALUES (?, ?, ?, 0.5, 0, ?)
                """, (regime, param_name, param_value, now))

    # ==================== TRADES ====================

    def insert_trade(self, trade: TradeRecord) -> int:
        """Insert a new trade record, return trade ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO trades (
                    ticker, signal, entry_date, entry_price, exit_date, exit_price,
                    return_pct, was_correct, regime, rsi2_at_entry, rsi14_at_entry,
                    volume_ratio, exit_reason, holding_days, position_size, transaction_cost
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.ticker, trade.signal, trade.entry_date, trade.entry_price,
                trade.exit_date, trade.exit_price, trade.return_pct,
                1 if trade.was_correct else 0 if trade.was_correct is not None else None,
                trade.regime, trade.rsi2_at_entry, trade.rsi14_at_entry,
                trade.volume_ratio, trade.exit_reason, trade.holding_days,
                trade.position_size, trade.transaction_cost
            ))
            conn.commit()
            return cursor.lastrowid

    def update_trade_exit(
        self,
        trade_id: int,
        exit_date: str,
        exit_price: float,
        exit_reason: str = None
    ):
        """Update a trade with exit information"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Get entry info to calculate return
            cursor.execute("SELECT entry_price, entry_date FROM trades WHERE id = ?", (trade_id,))
            row = cursor.fetchone()
            if not row:
                return

            entry_price, entry_date = row
            return_pct = ((exit_price - entry_price) / entry_price) * 100
            was_correct = 1 if return_pct > 0 else 0

            # Calculate holding days
            try:
                entry_dt = datetime.fromisoformat(entry_date.split("T")[0])
                exit_dt = datetime.fromisoformat(exit_date.split("T")[0])
                holding_days = (exit_dt - entry_dt).days
            except:
                holding_days = 0

            cursor.execute("""
                UPDATE trades SET
                    exit_date = ?,
                    exit_price = ?,
                    return_pct = ?,
                    was_correct = ?,
                    exit_reason = ?,
                    holding_days = ?
                WHERE id = ?
            """, (exit_date, exit_price, return_pct, was_correct, exit_reason, holding_days, trade_id))
            conn.commit()

    def get_recent_trades(self, limit: int = 50, regime: str = None) -> List[Dict]:
        """Get recent trades, optionally filtered by regime"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if regime:
                cursor.execute("""
                    SELECT * FROM trades
                    WHERE regime = ? AND was_correct IS NOT NULL
                    ORDER BY entry_date DESC
                    LIMIT ?
                """, (regime, limit))
            else:
                cursor.execute("""
                    SELECT * FROM trades
                    WHERE was_correct IS NOT NULL
                    ORDER BY entry_date DESC
                    LIMIT ?
                """, (limit,))

            return [dict(row) for row in cursor.fetchall()]

    def get_open_trades(self) -> List[Dict]:
        """Get trades without exit (still open)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM trades
                WHERE exit_date IS NULL
                ORDER BY entry_date DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_regime_stats(self, regime: str, lookback_trades: int = 30) -> Dict:
        """Get performance stats for a specific regime"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END) as wins,
                    AVG(return_pct) as avg_return,
                    AVG(holding_days) as avg_hold
                FROM (
                    SELECT * FROM trades
                    WHERE regime = ? AND was_correct IS NOT NULL
                    ORDER BY entry_date DESC
                    LIMIT ?
                )
            """, (regime, lookback_trades))

            row = cursor.fetchone()
            if row and row[0] > 0:
                return {
                    "regime": regime,
                    "total_trades": row[0],
                    "wins": row[1] or 0,
                    "win_rate": (row[1] / row[0] * 100) if row[0] > 0 else 0,
                    "avg_return": row[2] or 0,
                    "avg_holding_days": row[3] or 0,
                }
            return {
                "regime": regime,
                "total_trades": 0,
                "wins": 0,
                "win_rate": 65.0,  # Default assumption
                "avg_return": 0,
                "avg_holding_days": 7,
            }

    # ==================== PARAMETERS ====================

    def get_parameters(self, regime: str) -> Dict[str, float]:
        """Get all parameters for a regime"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT param_name, param_value FROM parameters
                WHERE regime = ?
            """, (regime,))
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_parameter(self, regime: str, param_name: str) -> Optional[float]:
        """Get a specific parameter value"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT param_value FROM parameters
                WHERE regime = ? AND param_name = ?
            """, (regime, param_name))
            row = cursor.fetchone()
            return row[0] if row else None

    def update_parameter(
        self,
        regime: str,
        param_name: str,
        param_value: float,
        confidence: float = None,
        samples: int = None
    ):
        """Update a parameter value"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()

            # Get current values for optional fields
            cursor.execute("""
                SELECT confidence, samples FROM parameters
                WHERE regime = ? AND param_name = ?
            """, (regime, param_name))
            row = cursor.fetchone()

            if row:
                current_conf, current_samples = row
                confidence = confidence if confidence is not None else current_conf
                samples = samples if samples is not None else current_samples
            else:
                confidence = confidence if confidence is not None else 0.5
                samples = samples if samples is not None else 0

            cursor.execute("""
                INSERT INTO parameters (regime, param_name, param_value, confidence, samples, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(regime, param_name) DO UPDATE SET
                    param_value = excluded.param_value,
                    confidence = excluded.confidence,
                    samples = excluded.samples,
                    updated_at = excluded.updated_at
            """, (regime, param_name, param_value, confidence, samples, now))
            conn.commit()

    # ==================== REGIME PERFORMANCE ====================

    def record_regime_performance(
        self,
        regime: str,
        total_trades: int,
        wins: int,
        avg_return: float,
        avg_holding_days: float = None,
        best_rsi2_threshold: float = None
    ):
        """Record a performance snapshot for a regime"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

            cursor.execute("""
                INSERT INTO regime_performance (
                    regime, window_end, total_trades, wins, win_rate,
                    avg_return, avg_holding_days, best_rsi2_threshold
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                regime, now, total_trades, wins, win_rate,
                avg_return, avg_holding_days, best_rsi2_threshold
            ))
            conn.commit()

    def get_regime_performance_history(self, regime: str, limit: int = 10) -> List[Dict]:
        """Get historical performance snapshots for a regime"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM regime_performance
                WHERE regime = ?
                ORDER BY window_end DESC
                LIMIT ?
            """, (regime, limit))
            return [dict(row) for row in cursor.fetchall()]

    # ==================== UTILITIES ====================

    def get_all_stats(self) -> Dict:
        """Get comprehensive stats across all data"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Overall stats
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END) as wins,
                    AVG(return_pct) as avg_return,
                    SUM(return_pct) as total_return
                FROM trades
                WHERE was_correct IS NOT NULL
            """)
            overall = cursor.fetchone()

            # Per-regime stats
            cursor.execute("""
                SELECT
                    regime,
                    COUNT(*) as total,
                    SUM(CASE WHEN was_correct = 1 THEN 1 ELSE 0 END) as wins,
                    AVG(return_pct) as avg_return
                FROM trades
                WHERE was_correct IS NOT NULL
                GROUP BY regime
            """)
            regimes = cursor.fetchall()

            return {
                "overall": {
                    "total_trades": overall[0] or 0,
                    "wins": overall[1] or 0,
                    "win_rate": (overall[1] / overall[0] * 100) if overall[0] else 0,
                    "avg_return": overall[2] or 0,
                    "total_return": overall[3] or 0,
                },
                "by_regime": {
                    row[0]: {
                        "total_trades": row[1],
                        "wins": row[2],
                        "win_rate": (row[2] / row[1] * 100) if row[1] else 0,
                        "avg_return": row[3] or 0,
                    }
                    for row in regimes
                }
            }

    def export_to_json(self, output_path: str = None) -> Dict:
        """Export all data to JSON for analysis"""
        if output_path is None:
            output_path = os.path.join(os.path.dirname(__file__), "atlas_export.json")

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Get all trades
            cursor.execute("SELECT * FROM trades ORDER BY entry_date DESC")
            trades = [dict(row) for row in cursor.fetchall()]

            # Get all parameters
            cursor.execute("SELECT * FROM parameters")
            params = [dict(row) for row in cursor.fetchall()]

            # Get performance history
            cursor.execute("SELECT * FROM regime_performance ORDER BY window_end DESC")
            performance = [dict(row) for row in cursor.fetchall()]

            data = {
                "exported_at": datetime.now().isoformat(),
                "stats": self.get_all_stats(),
                "trades": trades,
                "parameters": params,
                "performance_history": performance,
            }

            with open(output_path, 'w') as f:
                json.dump(data, f, indent=2, default=str)

            return data
