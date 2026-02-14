"""
Price and RSI Alert System
Notify users when stocks hit price targets or RSI levels
"""

import sqlite3
import asyncio
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path


class AlertManager:
    """
    Manages price and RSI alerts for stocks
    """

    def __init__(self, db_path: str = "data/alerts.db"):
        self.db_path = db_path

        # Ensure data directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_database()

        # Active alerts cache (for fast checking)
        self.active_alerts = []

    def _init_database(self):
        """Create database tables if they don't exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Alerts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                condition TEXT NOT NULL,
                target_value REAL NOT NULL,
                status TEXT DEFAULT 'ACTIVE',
                created_at INTEGER NOT NULL,
                triggered_at INTEGER,
                triggered_price REAL,
                triggered_rsi REAL,
                message TEXT,
                UNIQUE(ticker, alert_type, condition, target_value, status)
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_ticker ON alerts(ticker)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alert_status ON alerts(status)")

        # Alert history - track when alerts fire
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER NOT NULL,
                triggered_at INTEGER NOT NULL,
                price REAL NOT NULL,
                rsi REAL NOT NULL,
                signal TEXT,
                message TEXT,
                FOREIGN KEY(alert_id) REFERENCES alerts(id)
            )
        """)

        conn.commit()
        conn.close()

        print(f"Alert database initialized at {self.db_path}")

    async def create_alert(self, ticker: str, alert_type: str, condition: str,
                          target_value: float) -> Dict:
        """
        Create a new alert

        Args:
            ticker: Stock ticker
            alert_type: 'PRICE' or 'RSI'
            condition: 'ABOVE' or 'BELOW'
            target_value: Target price or RSI value

        Returns:
            Dict with alert details
        """
        try:
            return await asyncio.to_thread(
                self._create_alert_sync, ticker, alert_type, condition, target_value
            )
        except Exception as e:
            print(f"Error creating alert: {e}")
            return {"error": str(e)}

    def _create_alert_sync(self, ticker: str, alert_type: str, condition: str,
                           target_value: float) -> Dict:
        """Synchronous version of create_alert"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Validate inputs
        if alert_type not in ['PRICE', 'RSI']:
            conn.close()
            return {"error": "alert_type must be 'PRICE' or 'RSI'"}

        if condition not in ['ABOVE', 'BELOW']:
            conn.close()
            return {"error": "condition must be 'ABOVE' or 'BELOW'"}

        try:
            cursor.execute("""
                INSERT INTO alerts
                (ticker, alert_type, condition, target_value, created_at, status)
                VALUES (?, ?, ?, ?, ?, 'ACTIVE')
            """, (
                ticker.upper(),
                alert_type,
                condition,
                target_value,
                int(datetime.now().timestamp())
            ))

            alert_id = cursor.lastrowid
            conn.commit()

            # Update cache
            asyncio.create_task(self.refresh_active_alerts())

            return {
                "success": True,
                "alert_id": alert_id,
                "ticker": ticker.upper(),
                "alert_type": alert_type,
                "condition": condition,
                "target_value": target_value,
                "message": f"Alert created: {ticker} {alert_type} {condition} {target_value}"
            }

        except sqlite3.IntegrityError:
            return {
                "error": "Alert already exists with same parameters"
            }
        finally:
            conn.close()

    async def check_alerts(self, ticker: str, current_price: float, current_rsi: float,
                          current_signal: str) -> List[Dict]:
        """
        Check if any alerts should be triggered

        Args:
            ticker: Stock ticker
            current_price: Current price
            current_rsi: Current RSI
            current_signal: Current signal (BUY/SELL/HOLD)

        Returns:
            List of triggered alerts
        """
        try:
            return await asyncio.to_thread(
                self._check_alerts_sync, ticker, current_price, current_rsi, current_signal
            )
        except Exception as e:
            print(f"Error checking alerts: {e}")
            return []

    def _check_alerts_sync(self, ticker: str, current_price: float, current_rsi: float,
                           current_signal: str) -> List[Dict]:
        """Synchronous version of check_alerts"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get active alerts for this ticker
        cursor.execute("""
            SELECT * FROM alerts
            WHERE ticker = ? AND status = 'ACTIVE'
        """, (ticker.upper(),))

        columns = ['id', 'ticker', 'alert_type', 'condition', 'target_value', 'status',
                   'created_at', 'triggered_at', 'triggered_price', 'triggered_rsi', 'message']

        triggered = []

        for row in cursor.fetchall():
            alert = dict(zip(columns, row))

            should_trigger = False

            # Check price alerts
            if alert['alert_type'] == 'PRICE':
                if alert['condition'] == 'ABOVE' and current_price >= alert['target_value']:
                    should_trigger = True
                elif alert['condition'] == 'BELOW' and current_price <= alert['target_value']:
                    should_trigger = True

            # Check RSI alerts
            elif alert['alert_type'] == 'RSI':
                if alert['condition'] == 'ABOVE' and current_rsi >= alert['target_value']:
                    should_trigger = True
                elif alert['condition'] == 'BELOW' and current_rsi <= alert['target_value']:
                    should_trigger = True

            if should_trigger:
                # Build message
                message = f"🚨 ALERT: {ticker} {alert['alert_type']} {alert['condition']} {alert['target_value']}"
                if alert['alert_type'] == 'PRICE':
                    message += f" | Current: ${current_price:.2f}"
                else:
                    message += f" | Current RSI: {current_rsi:.2f}"
                message += f" | Signal: {current_signal}"

                # Update alert status
                cursor.execute("""
                    UPDATE alerts
                    SET status = 'TRIGGERED',
                        triggered_at = ?,
                        triggered_price = ?,
                        triggered_rsi = ?,
                        message = ?
                    WHERE id = ?
                """, (
                    int(datetime.now().timestamp()),
                    current_price,
                    current_rsi,
                    message,
                    alert['id']
                ))

                # Add to history
                cursor.execute("""
                    INSERT INTO alert_history
                    (alert_id, triggered_at, price, rsi, signal, message)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    alert['id'],
                    int(datetime.now().timestamp()),
                    current_price,
                    current_rsi,
                    current_signal,
                    message
                ))

                triggered.append({
                    "alert_id": alert['id'],
                    "ticker": ticker,
                    "alert_type": alert['alert_type'],
                    "condition": alert['condition'],
                    "target_value": alert['target_value'],
                    "current_price": current_price,
                    "current_rsi": current_rsi,
                    "current_signal": current_signal,
                    "message": message,
                    "triggered_at": datetime.now().isoformat()
                })

        conn.commit()
        conn.close()

        return triggered

    async def get_active_alerts(self, ticker: Optional[str] = None) -> List[Dict]:
        """Get all active alerts, optionally filtered by ticker"""
        try:
            return await asyncio.to_thread(self._get_active_alerts_sync, ticker)
        except Exception as e:
            print(f"Error getting active alerts: {e}")
            return []

    def _get_active_alerts_sync(self, ticker: Optional[str]) -> List[Dict]:
        """Synchronous version of get_active_alerts"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if ticker:
            cursor.execute("""
                SELECT * FROM alerts
                WHERE ticker = ? AND status = 'ACTIVE'
                ORDER BY created_at DESC
            """, (ticker.upper(),))
        else:
            cursor.execute("""
                SELECT * FROM alerts
                WHERE status = 'ACTIVE'
                ORDER BY created_at DESC
            """)

        columns = ['id', 'ticker', 'alert_type', 'condition', 'target_value', 'status',
                   'created_at', 'triggered_at', 'triggered_price', 'triggered_rsi', 'message']

        alerts = []
        for row in cursor.fetchall():
            alert = dict(zip(columns, row))
            alerts.append(alert)

        conn.close()
        return alerts

    async def get_triggered_alerts(self, limit: int = 50) -> List[Dict]:
        """Get recently triggered alerts"""
        try:
            return await asyncio.to_thread(self._get_triggered_alerts_sync, limit)
        except Exception as e:
            print(f"Error getting triggered alerts: {e}")
            return []

    def _get_triggered_alerts_sync(self, limit: int) -> List[Dict]:
        """Synchronous version of get_triggered_alerts"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM alerts
            WHERE status = 'TRIGGERED'
            ORDER BY triggered_at DESC
            LIMIT ?
        """, (limit,))

        columns = ['id', 'ticker', 'alert_type', 'condition', 'target_value', 'status',
                   'created_at', 'triggered_at', 'triggered_price', 'triggered_rsi', 'message']

        alerts = []
        for row in cursor.fetchall():
            alert = dict(zip(columns, row))
            alerts.append(alert)

        conn.close()
        return alerts

    async def delete_alert(self, alert_id: int) -> Dict:
        """Delete an alert"""
        try:
            return await asyncio.to_thread(self._delete_alert_sync, alert_id)
        except Exception as e:
            print(f"Error deleting alert: {e}")
            return {"error": str(e)}

    def _delete_alert_sync(self, alert_id: int) -> Dict:
        """Synchronous version of delete_alert"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        deleted = cursor.rowcount > 0

        conn.commit()
        conn.close()

        # Update cache
        asyncio.create_task(self.refresh_active_alerts())

        if deleted:
            return {"success": True, "message": "Alert deleted"}
        else:
            return {"error": "Alert not found"}

    async def refresh_active_alerts(self):
        """Refresh the active alerts cache"""
        try:
            self.active_alerts = await self.get_active_alerts()
        except Exception as e:
            print(f"Error refreshing alerts cache: {e}")

    async def clear_triggered_alerts(self) -> Dict:
        """Clear all triggered alerts"""
        try:
            return await asyncio.to_thread(self._clear_triggered_alerts_sync)
        except Exception as e:
            print(f"Error clearing triggered alerts: {e}")
            return {"error": str(e)}

    def _clear_triggered_alerts_sync(self) -> Dict:
        """Synchronous version of clear_triggered_alerts"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM alerts WHERE status = 'TRIGGERED'")
        count = cursor.rowcount

        conn.commit()
        conn.close()

        return {
            "success": True,
            "message": f"Cleared {count} triggered alerts"
        }
