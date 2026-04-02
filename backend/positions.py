"""
Position Tracking Module
Track user's stock positions, P&L, and whether our signals were correct
"""

import sqlite3
import asyncio
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path


class PositionManager:
    """
    Manages user's stock positions and tracks performance
    """

    def __init__(self, db_path: str = "data/positions.db"):
        self.db_path = db_path

        # Ensure data directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_database()

    def _init_database(self):
        """Create database tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            cursor = conn.cursor()

            # Positions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    entry_date TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    shares INTEGER NOT NULL,
                    position_type TEXT DEFAULT 'LONG',
                    status TEXT DEFAULT 'OPEN',
                    exit_date TEXT,
                    exit_price REAL,
                    notes TEXT,
                    created_at INTEGER NOT NULL,
                    UNIQUE(ticker, entry_date, entry_price)
                )
            """)

            # Allow fractional shares
            try:
                cursor.execute("SELECT typeof(shares) FROM positions LIMIT 1")
            except Exception:
                pass

            # Add currency column if missing (backward compat: default USD)
            try:
                cursor.execute("ALTER TABLE positions ADD COLUMN currency TEXT DEFAULT 'USD'")
            except sqlite3.OperationalError:
                pass

            # Add strategy column (V3.0: MR=45d hold, MOMENTUM=60d hold)
            try:
                cursor.execute("ALTER TABLE positions ADD COLUMN strategy TEXT DEFAULT 'MEAN_REVERSION'")
            except sqlite3.OperationalError:
                pass

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pos_ticker ON positions(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pos_status ON positions(status)")

            # Transactions table - tracks all buys/sells with fees
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id INTEGER,
                    ticker TEXT NOT NULL,
                    action TEXT NOT NULL,
                    date TEXT NOT NULL,
                    price REAL NOT NULL,
                    shares REAL NOT NULL,
                    total REAL NOT NULL,
                    fee REAL DEFAULT 1.50,
                    realized_pnl REAL,
                    notes TEXT,
                    created_at TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_ticker ON transactions(ticker)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date)")

            # Position history - daily snapshots of position value
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS position_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    current_price REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    unrealized_pnl_pct REAL NOT NULL,
                    signal TEXT,
                    signal_strength INTEGER,
                    rsi REAL,
                    timestamp INTEGER NOT NULL,
                    FOREIGN KEY(position_id) REFERENCES positions(id),
                    UNIQUE(position_id, date)
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pos_hist_date ON position_history(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pos_hist_pos_date ON position_history(position_id, date)")

            conn.commit()
        finally:
            conn.close()

        print(f"Position database initialized at {self.db_path}")

    async def add_position(self, ticker: str, entry_date: str, entry_price: float,
                          shares: float, notes: str = "", currency: str = "USD") -> Dict:
        """Add a new position"""
        try:
            return await asyncio.to_thread(
                self._add_position_sync, ticker, entry_date, entry_price, shares, notes, currency
            )
        except Exception as e:
            print(f"Error adding position: {e}")
            return {"error": str(e)}

    def _add_position_sync(self, ticker: str, entry_date: str, entry_price: float,
                           shares: float, notes: str, currency: str = "USD") -> Dict:
        """Synchronous version of add_position"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO positions
                (ticker, entry_date, entry_price, shares, notes, created_at, status, currency)
                VALUES (?, ?, ?, ?, ?, ?, 'OPEN', ?)
            """, (
                ticker.upper(),
                entry_date,
                entry_price,
                shares,
                notes,
                int(datetime.now().timestamp()),
                currency.upper(),
            ))

            position_id = cursor.lastrowid
            conn.commit()

            return {
                "success": True,
                "position_id": position_id,
                "ticker": ticker.upper(),
                "entry_date": entry_date,
                "entry_price": entry_price,
                "shares": shares,
                "cost_basis": entry_price * shares
            }

        except sqlite3.IntegrityError:
            return {
                "error": "Position already exists with same ticker, entry date, and price"
            }
        finally:
            conn.close()

    async def close_position(self, position_id: int, exit_date: str, exit_price: float) -> Dict:
        """Close a position"""
        try:
            return await asyncio.to_thread(
                self._close_position_sync, position_id, exit_date, exit_price
            )
        except Exception as e:
            print(f"Error closing position: {e}")
            return {"error": str(e)}

    def _close_position_sync(self, position_id: int, exit_date: str, exit_price: float) -> Dict:
        """Synchronous version of close_position"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get position details
            cursor.execute("SELECT * FROM positions WHERE id = ?", (position_id,))
            row = cursor.fetchone()

            if not row:
                return {"error": "Position not found"}

            columns = ['id', 'ticker', 'entry_date', 'entry_price', 'shares', 'position_type',
                       'status', 'exit_date', 'exit_price', 'notes', 'created_at', 'currency']
            position = dict(zip(columns, row))

            # Update position
            cursor.execute("""
                UPDATE positions
                SET status = 'CLOSED', exit_date = ?, exit_price = ?
                WHERE id = ?
            """, (exit_date, exit_price, position_id))

            conn.commit()
        finally:
            conn.close()

        # Calculate realized P&L
        entry_value = position['entry_price'] * position['shares']
        exit_value = exit_price * position['shares']
        realized_pnl = exit_value - entry_value
        realized_pnl_pct = (realized_pnl / entry_value) * 100

        return {
            "success": True,
            "position_id": position_id,
            "ticker": position['ticker'],
            "entry_date": position['entry_date'],
            "entry_price": position['entry_price'],
            "exit_date": exit_date,
            "exit_price": exit_price,
            "shares": position['shares'],
            "realized_pnl": round(realized_pnl, 2),
            "realized_pnl_pct": round(realized_pnl_pct, 2)
        }

    async def get_open_positions(self, currency: str = None) -> List[Dict]:
        """Get all open positions, optionally filtered by currency"""
        try:
            return await asyncio.to_thread(self._get_open_positions_sync, currency)
        except Exception as e:
            print(f"Error getting open positions: {e}")
            return []

    def _get_open_positions_sync(self, currency: str = None) -> List[Dict]:
        """Synchronous version of get_open_positions"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            if currency:
                cursor.execute("""
                    SELECT * FROM positions
                    WHERE status = 'OPEN' AND UPPER(COALESCE(currency, 'USD')) = ?
                    ORDER BY entry_date DESC
                """, (currency.upper(),))
            else:
                cursor.execute("""
                    SELECT * FROM positions
                    WHERE status = 'OPEN'
                    ORDER BY entry_date DESC
                """)

            columns = ['id', 'ticker', 'entry_date', 'entry_price', 'shares', 'position_type',
                       'status', 'exit_date', 'exit_price', 'notes', 'created_at', 'currency']

            positions = []
            for row in cursor.fetchall():
                position = dict(zip(columns, row))
                positions.append(position)

            return positions
        finally:
            conn.close()

    async def get_position_performance(self, position_id: int, current_price: float,
                                      current_signal: Optional[Dict] = None) -> Dict:
        """
        Calculate current performance of a position

        Args:
            position_id: Position ID
            current_price: Current market price
            current_signal: Optional current signal data

        Returns:
            Dict with P&L, signal accuracy, and recommendations
        """
        try:
            return await asyncio.to_thread(
                self._get_position_performance_sync, position_id, current_price, current_signal
            )
        except Exception as e:
            print(f"Error getting position performance: {e}")
            return {"error": str(e)}

    def _get_position_performance_sync(self, position_id: int, current_price: float,
                                       current_signal: Optional[Dict]) -> Dict:
        """Synchronous version of get_position_performance"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get position
            cursor.execute("SELECT * FROM positions WHERE id = ?", (position_id,))
            row = cursor.fetchone()

            if not row:
                return {"error": "Position not found"}

            columns = ['id', 'ticker', 'entry_date', 'entry_price', 'shares', 'position_type',
                       'status', 'exit_date', 'exit_price', 'notes', 'created_at', 'currency']
            position = dict(zip(columns, row))

            # Calculate P&L
            entry_value = position['entry_price'] * position['shares']
            current_value = current_price * position['shares']
            unrealized_pnl = current_value - entry_value
            unrealized_pnl_pct = (unrealized_pnl / entry_value) * 100

            # Get historical snapshots
            cursor.execute("""
                SELECT date, unrealized_pnl_pct, signal, rsi
                FROM position_history
                WHERE position_id = ?
                ORDER BY date ASC
            """, (position_id,))

            history = []
            for hist_row in cursor.fetchall():
                history.append({
                    "date": hist_row[0],
                    "pnl_pct": hist_row[1],
                    "signal": hist_row[2],
                    "rsi": hist_row[3]
                })
        finally:
            conn.close()

        # Calculate days held (TRADING days to match backtest bars)
        entry_dt = datetime.strptime(position['entry_date'], '%Y-%m-%d')
        from datetime import timedelta as _td
        _entry_d = entry_dt.date() if hasattr(entry_dt, 'date') else entry_dt
        _today_d = datetime.now().date()
        days_held = sum(
            1 for n in range((_today_d - _entry_d).days)
            if (_entry_d + _td(days=n + 1)).weekday() < 5
        )

        # Determine if entry was a good decision based on P&L
        was_good_entry = unrealized_pnl_pct > 5  # Profitable by >5%

        # Build recommendation - NEW: includes analyst targets
        recommendation = ""

        # Get analyst data if available from current_signal
        upside_potential = current_signal.get('upside_potential', 0) if current_signal else 0
        analyst_target = current_signal.get('analyst_target_avg', 0) if current_signal else 0
        analyst_consensus = current_signal.get('analyst_consensus', 'No Data') if current_signal else 'No Data'
        has_analyst_data = current_signal.get('has_analyst_data', False) if current_signal else False

        if current_signal:
            signal = current_signal['signal']
            rsi = current_signal.get('rsi', 50)

            # Priority 1: Strong analyst upside + down position = BUY THE DIP
            if has_analyst_data and upside_potential > 30 and unrealized_pnl_pct < -5:
                recommendation = f"BUY THE DIP - Analysts target ${analyst_target:.0f} ({upside_potential:+.0f}% upside). Down {abs(unrealized_pnl_pct):.1f}% is a buying opportunity. Consensus: {analyst_consensus}"

            # Priority 2: Near analyst target = TAKE PROFIT
            elif has_analyst_data and analyst_target > 0 and current_price >= analyst_target * 0.9 and unrealized_pnl_pct > 0:
                recommendation = f"TAKE PROFIT - Near analyst target ${analyst_target:.0f}. Lock in {unrealized_pnl_pct:+.1f}% gain or set trailing stop"

            # Priority 3: Strong upside potential = HOLD FOR TARGET
            elif has_analyst_data and upside_potential > 20:
                recommendation = f"HOLD FOR TARGET - Analysts see {upside_potential:+.0f}% upside to ${analyst_target:.0f}. Current: ${current_price:.2f}. Consensus: {analyst_consensus}"

            # Priority 4: Down position but negative analyst view = EXIT
            elif has_analyst_data and upside_potential < 0 and unrealized_pnl_pct < -5:
                recommendation = f"CONSIDER EXITING - Analysts bearish (target ${analyst_target:.0f}, {upside_potential:.0f}% downside) and you're down {abs(unrealized_pnl_pct):.1f}%"

            # Fallback to technical signals if no analyst data
            elif signal == 'SELL' and unrealized_pnl_pct > 10:
                recommendation = "STRONG TAKE PROFIT - Technical signal SELL and position is up >10%"
            elif signal == 'SELL' and unrealized_pnl_pct > 0:
                recommendation = "CONSIDER TAKING PROFIT - Technical signal SELL and position is profitable"
            elif signal == 'BUY' and unrealized_pnl_pct < -10:
                recommendation = "AVERAGE DOWN - Technical signal BUY and position is down >10%"
            elif signal == 'HOLD':
                recommendation = "HOLD CURRENT POSITION - No clear signal. Monitor for changes"
            elif rsi > 75:
                recommendation = "CONSIDER TRIMMING - RSI extremely overbought, may pullback"
            elif rsi < 25:
                recommendation = "HOLD OR ADD - RSI extremely oversold, may bounce"
            else:
                recommendation = f"HOLD - Current signal: {signal}. Monitor position"

        result = {
            "position_id": position_id,
            "ticker": position['ticker'],
            "entry_date": position['entry_date'],
            "entry_price": position['entry_price'],
            "current_price": current_price,
            "shares": position['shares'],
            "days_held": days_held,
            "cost_basis": entry_value,
            "current_value": current_value,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
            "was_good_entry": was_good_entry,
            "current_signal": current_signal['signal'] if current_signal else None,
            "current_rsi": current_signal.get('rsi') if current_signal else None,
            "recommendation": recommendation,
            "history_points": len(history),
            "history": history[-30:]  # Last 30 days
        }

        return result

    async def update_position_snapshot(self, position_id: int, current_price: float,
                                       signal: str, signal_strength: int, rsi: float):
        """Store daily snapshot of position performance"""
        try:
            await asyncio.to_thread(
                self._update_position_snapshot_sync,
                position_id, current_price, signal, signal_strength, rsi
            )
        except Exception as e:
            print(f"Error updating position snapshot: {e}")

    def _update_position_snapshot_sync(self, position_id: int, current_price: float,
                                       signal: str, signal_strength: int, rsi: float):
        """Synchronous version of update_position_snapshot"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get position to calculate P&L
            cursor.execute("SELECT entry_price, shares FROM positions WHERE id = ?", (position_id,))
            row = cursor.fetchone()

            if not row:
                return

            entry_price, shares = row
            entry_value = entry_price * shares
            current_value = current_price * shares
            unrealized_pnl = current_value - entry_value
            unrealized_pnl_pct = (unrealized_pnl / entry_value) * 100

            today = datetime.now().strftime('%Y-%m-%d')

            cursor.execute("""
                INSERT OR REPLACE INTO position_history
                (position_id, date, current_price, unrealized_pnl, unrealized_pnl_pct,
                 signal, signal_strength, rsi, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position_id,
                today,
                current_price,
                unrealized_pnl,
                unrealized_pnl_pct,
                signal,
                signal_strength,
                rsi,
                int(datetime.now().timestamp())
            ))

            conn.commit()
        finally:
            conn.close()

    async def get_all_positions(self, include_closed: bool = False) -> List[Dict]:
        """Get all positions"""
        try:
            return await asyncio.to_thread(self._get_all_positions_sync, include_closed)
        except Exception as e:
            print(f"Error getting all positions: {e}")
            return []

    def _get_all_positions_sync(self, include_closed: bool) -> List[Dict]:
        """Synchronous version of get_all_positions"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            if include_closed:
                cursor.execute("SELECT * FROM positions ORDER BY entry_date DESC")
            else:
                cursor.execute("""
                    SELECT * FROM positions
                    WHERE status = 'OPEN'
                    ORDER BY entry_date DESC
                """)

            columns = ['id', 'ticker', 'entry_date', 'entry_price', 'shares', 'position_type',
                       'status', 'exit_date', 'exit_price', 'notes', 'created_at', 'currency']

            positions = []
            for row in cursor.fetchall():
                position = dict(zip(columns, row))
                positions.append(position)

            return positions
        finally:
            conn.close()

    async def delete_position(self, position_id: int) -> Dict:
        """Delete a position and its history"""
        try:
            return await asyncio.to_thread(self._delete_position_sync, position_id)
        except Exception as e:
            print(f"Error deleting position: {e}")
            return {"error": str(e)}

    def _delete_position_sync(self, position_id: int) -> Dict:
        """Synchronous version of delete_position"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Delete history first
            cursor.execute("DELETE FROM position_history WHERE position_id = ?", (position_id,))

            # Delete position
            cursor.execute("DELETE FROM positions WHERE id = ?", (position_id,))

            deleted = cursor.rowcount > 0
            conn.commit()
        finally:
            conn.close()

        if deleted:
            return {"success": True, "message": "Position deleted"}
        else:
            return {"error": "Position not found"}

    # ── Transaction Methods ──

    def add_transaction(self, ticker: str, action: str, price: float, shares: float,
                        fee: float = 1.50, realized_pnl: float = None,
                        notes: str = "", position_id: int = None) -> Dict:
        """Record a buy/sell transaction."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            total = price * shares
            now = datetime.now()

            cursor.execute("""
                INSERT INTO transactions
                (position_id, ticker, action, date, price, shares, total, fee, realized_pnl, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position_id,
                ticker.upper(),
                action.upper(),
                now.strftime('%Y-%m-%d'),
                price,
                shares,
                total,
                fee,
                realized_pnl,
                notes,
                now.isoformat(),
            ))

            tx_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()

        return {
            "success": True,
            "transaction_id": tx_id,
            "ticker": ticker.upper(),
            "action": action.upper(),
            "shares": shares,
            "price": price,
            "total": total,
            "fee": fee,
        }

    def get_transactions(self, ticker: str = None, limit: int = 100) -> List[Dict]:
        """Get transaction history, optionally filtered by ticker."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            if ticker:
                cursor.execute("""
                    SELECT id, position_id, ticker, action, date, price, shares, total, fee,
                           realized_pnl, notes, created_at
                    FROM transactions
                    WHERE ticker = ?
                    ORDER BY date DESC, id DESC
                    LIMIT ?
                """, (ticker.upper(), limit))
            else:
                cursor.execute("""
                    SELECT id, position_id, ticker, action, date, price, shares, total, fee,
                           realized_pnl, notes, created_at
                    FROM transactions
                    ORDER BY date DESC, id DESC
                    LIMIT ?
                """, (limit,))

            columns = ['id', 'position_id', 'ticker', 'action', 'date', 'price',
                        'shares', 'total', 'fee', 'realized_pnl', 'notes', 'created_at']
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return rows
        finally:
            conn.close()

    def get_transaction_summary(self) -> Dict:
        """Get total fees paid and realized P&L.
        Uses actual fees recorded per transaction (broker-verified).
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("SELECT COALESCE(SUM(realized_pnl), 0) FROM transactions WHERE realized_pnl IS NOT NULL")
            total_pnl = cursor.fetchone()[0]

            # Use actual fees from transactions (broker-verified)
            cursor.execute("SELECT COALESCE(SUM(fee), 0), COUNT(*) FROM transactions")
            row = cursor.fetchone()
            total_fees = row[0]
            count = row[1]
        finally:
            conn.close()

        return {
            "total_fees": total_fees,
            "total_realized_pnl": total_pnl,
            "trade_count": count,
        }
