#!/usr/bin/env python3
"""
Reconcile positions.db with Blink broker PDF statement (23.02.2026).
Rebuilds positions and transactions tables from broker-verified data.
Preserves ILS positions (LUMI.TA, MAXO.TA) which are from a different broker.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "positions.db")

# ============================================================
# BROKER-VERIFIED DATA (from PDF statement dated 23.02.2026)
# ============================================================

DEPOSITS = [
    ("2026-01-04", 1500.00),
    ("2026-01-07", 1500.00),
    ("2026-01-08", 200.00),
    ("2026-01-15", 500.00),
    ("2026-01-30", 1500.21),
    ("2026-02-13", 3213.37),
]
TOTAL_DEPOSITED = sum(d[1] for d in DEPOSITS)  # $8,413.58
DIVIDEND = 0.40  # MRVL dividend on 2026-01-29

# All positions with broker-verified data
# Format: (ticker, entry_date, exit_date, status, entry_price_avg, shares, cost_basis,
#          exit_price, sell_proceeds, realized_pnl, currency, notes)
POSITIONS = [
    # --- CLOSED positions (chronological) ---
    # Pos 1: MRVL (original batch)
    ("MRVL", "2026-01-07", "2026-01-14", "CLOSED", 86.50, 0, 778.50,
     79.49, 715.41, -63.09, "USD", "Original batch - 9 shares"),
    # Pos 2: VST
    ("VST", "2026-01-07", "2026-01-20", "CLOSED", 169.58, 0, 1340.34,
     161.53, 1276.66, -63.68, "USD", "5sh@167.47 + 2.9038sh@173.22"),
    # Pos 3: LLY
    ("LLY", "2026-01-07", "2026-01-20", "CLOSED", 1080.50, 0, 1080.50,
     1030.80, 1030.80, -49.70, "USD", "Eli Lilly"),
    # Pos 4: COIN
    ("COIN", "2026-01-14", "2026-01-20", "CLOSED", 256.39, 0, 715.99,
     230.80, 644.54, -71.45, "USD", "Coinbase"),
    # Pos 5: QQQ
    ("QQQ", "2026-01-15", "2026-02-10", "CLOSED", 616.12, 0, 1466.98,
     615.09, 1464.53, -2.45, "USD", "0.799sh@625.78 + 1.582sh@611.24"),
    # Pos 6: MU
    ("MU", "2026-01-20", "2026-02-04", "CLOSED", 391.05, 0, 1258.99,
     368.26, 1185.63, -73.36, "USD", "2.5404sh@377.89 + 0.6791sh@440.27"),
    # Pos 7: NVDA
    ("NVDA", "2026-01-20", "2026-02-04", "CLOSED", 179.90, 0, 1019.99,
     172.51, 978.10, -41.89, "USD", "5.6698 shares"),
    # Pos 8: SLB
    ("SLB", "2026-01-30", "2026-02-05", "CLOSED", 48.47, 0, 1293.99,
     49.74, 1328.14, 34.15, "USD", "24.8443sh@48.30 + 1.8548sh@50.68"),
    # Pos 9: MRVL (micro batch)
    ("MRVL", "2026-01-30", "2026-02-04", "CLOSED", 80.40, 0, 0.39,
     72.35, 0.35, -0.04, "USD", "Micro lot 0.0049 shares"),
    # Pos 10: SYK
    ("SYK", "2026-02-04", "2026-02-06", "CLOSED", 364.13, 0, 1091.98,
     357.98, 1073.56, -18.42, "USD", "2.9989 shares"),
    # Pos 11: SPG
    ("SPG", "2026-02-04", "2026-02-06", "CLOSED", 195.47, 0, 975.99,
     198.79, 992.55, 16.56, "USD", "4.993 shares"),
    # Pos 12: NEM
    ("NEM", "2026-02-05", "2026-02-06", "CLOSED", 114.25, 0, 665.00,
     113.82, 662.48, -2.52, "USD", "5.8205 shares"),
    # Pos 13: LRCX
    ("LRCX", "2026-02-05", "2026-02-13", "CLOSED", 220.42, 0, 1002.98,
     237.21, 1079.34, 76.36, "USD", "3.1069sh@213.71 + 1.4433sh@234.87"),
    # Pos 14: LIN
    ("LIN", "2026-02-06", "2026-02-10", "CLOSED", 452.78, 0, 999.97,
     462.90, 1022.31, 22.34, "USD", "2.2085 shares"),
    # Pos 15: ALB
    ("ALB", "2026-02-06", "2026-02-18", "CLOSED", 164.09, 0, 1933.99,
     172.48, 2033.05, 99.06, "USD", "6.5893sh@162.38 + 5.1978sh@166.22"),
    # Pos 16: GOOGL
    ("GOOGL", "2026-02-10", "2026-02-12", "CLOSED", 318.67, 0, 1020.99,
     310.47, 994.72, -26.27, "USD", "3.2039 shares"),
    # Pos 17: VRT
    ("VRT", "2026-02-10", "2026-02-11", "CLOSED", 201.80, 0, 1461.99,
     245.08, 1775.54, 313.55, "USD", "7.2447 shares"),
    # Pos 18: COHR
    ("COHR", "2026-02-11", "2026-02-23", "CLOSED", 220.07, 0, 3053.96,
     248.47, 3447.88, 393.92, "USD", "4.7599sh@223.11 + 4.5514sh@217.95 + 4.5651sh@219.05"),
    # Pos 19: JOUT
    ("JOUT", "2026-02-13", "2026-02-18", "CLOSED", 48.77, 0, 498.00,
     48.93, 499.61, 1.61, "USD", "10.2115 shares"),
    # Pos 20: CMC
    ("CMC", "2026-02-18", "2026-02-19", "CLOSED", 78.39, 0, 1329.99,
     77.62, 1316.96, -13.03, "USD", "16.9659 shares"),

    # --- OPEN positions ---
    # Pos 21: BE
    ("BE", "2026-02-06", None, "OPEN", 141.84, 15.6302, 2216.98,
     None, None, None, "USD", "4.64sh@139.87 + 2.5267sh@145.64 + 8.4635sh@141.78"),
    # Pos 22: GHM
    ("GHM", "2026-02-13", None, "OPEN", 84.88, 8.4703, 719.00,
     None, None, None, "USD", "8.4703 shares"),
    # Pos 23: BWA
    ("BWA", "2026-02-18", None, "OPEN", 61.47, 19.0987, 1174.00,
     None, None, None, "USD", "19.0987 shares"),
    # Pos 24: MTRN
    ("MTRN", "2026-02-19", None, "OPEN", 150.15, 8.7844, 1318.99,
     None, None, None, "USD", "CMC swap - 8.7844 shares"),
    # Pos 25: WDC
    ("WDC", "2026-02-23", None, "OPEN", 281.80, 6.3874, 1799.98,
     None, None, None, "USD", "COHR rotation - 6.3874 shares"),
    # Pos 26: CGNX
    ("CGNX", "2026-02-23", None, "OPEN", 56.02, 27.5412, 1543.00,
     None, None, None, "USD", "COHR rotation - 27.5412 shares"),

    # --- ILS positions (different broker, preserve as-is) ---
    # Pos 27: LUMI.TA
    ("LUMI.TA", "2026-02-17", None, "OPEN", 7900.00, 126, None,
     None, None, None, "ILS", "Israeli bank stock"),
    # Pos 28: MAXO.TA
    ("MAXO.TA", "2026-02-19", None, "OPEN", 3030.00, 165, None,
     None, None, None, "ILS", "Israeli stock"),
]

# All transactions with broker-verified data
# Format: (position_idx, ticker, action, date, price, shares, total, fee, realized_pnl, notes)
# position_idx is 0-based index into POSITIONS list above
TRANSACTIONS = [
    # --- January trades ---
    # MRVL original
    (0, "MRVL", "BUY", "2026-01-07", 86.50, 9.0000, 778.50, 1.50, None, "Initial buy"),
    (0, "MRVL", "SELL", "2026-01-14", 79.49, 9.0000, 715.41, 0, -63.09, "Sold at loss"),
    # VST
    (1, "VST", "BUY", "2026-01-07", 167.47, 5.0000, 837.35, 1.50, None, "Initial buy"),
    (1, "VST", "BUY", "2026-01-09", 173.22, 2.9038, 502.99, 1.50, None, "Add shares"),
    (1, "VST", "SELL", "2026-01-20", 161.53, 7.9038, 1276.66, 0, -63.68, "Sold all"),
    # LLY
    (2, "LLY", "BUY", "2026-01-07", 1080.50, 1.0000, 1080.50, 1.50, None, "Initial buy"),
    (2, "LLY", "SELL", "2026-01-20", 1030.80, 1.0000, 1030.80, 0, -49.70, "Sold at loss"),
    # COIN
    (3, "COIN", "BUY", "2026-01-14", 256.39, 2.7926, 715.99, 0, None, "Bought with MRVL proceeds"),
    (3, "COIN", "SELL", "2026-01-20", 230.80, 2.7926, 644.54, 0, -71.45, "Sold at loss"),
    # QQQ
    (4, "QQQ", "BUY", "2026-01-15", 625.78, 0.7990, 500.00, 0, None, "First buy"),
    (4, "QQQ", "BUY", "2026-01-20", 611.24, 1.5820, 966.98, 0, None, "Add shares"),
    # MU
    (5, "MU", "BUY", "2026-01-20", 377.89, 2.5404, 960.00, 0, None, "Initial buy"),
    (5, "MU", "BUY", "2026-02-02", 440.27, 0.6791, 298.99, 0, None, "Add shares"),
    # NVDA
    (6, "NVDA", "BUY", "2026-01-20", 179.90, 5.6698, 1019.99, 0, None, "Initial buy"),
    # SLB
    (7, "SLB", "BUY", "2026-01-30", 48.30, 24.8443, 1200.00, 0, None, "Initial buy"),
    (7, "SLB", "BUY", "2026-02-04", 50.68, 1.8548, 93.99, 0, None, "Add shares"),
    # MRVL micro
    (8, "MRVL", "BUY", "2026-01-30", 80.40, 0.0049, 0.39, 0.01, None, "Micro lot"),
    (8, "MRVL", "SELL", "2026-02-04", 72.35, 0.0049, 0.35, 0, -0.04, "Sold micro lot"),

    # --- February trades ---
    # MU sell
    (5, "MU", "SELL", "2026-02-04", 368.26, 3.2195, 1185.63, 1.50, -73.36, "Sold all"),
    # NVDA sell
    (6, "NVDA", "SELL", "2026-02-04", 172.51, 5.6698, 978.10, 1.50, -41.89, "Sold at loss"),
    # SYK
    (9, "SYK", "BUY", "2026-02-04", 364.13, 2.9989, 1091.98, 1.50, None, "Initial buy"),
    # SPG
    (10, "SPG", "BUY", "2026-02-04", 195.47, 4.9930, 975.99, 1.50, None, "Initial buy"),
    # SLB add + sell
    (7, "SLB", "SELL", "2026-02-05", 49.74, 26.6991, 1328.14, 1.50, 34.15, "Sold all"),
    # NEM
    (11, "NEM", "BUY", "2026-02-05", 114.25, 5.8205, 665.00, 1.50, None, "Initial buy"),
    # LRCX first buy
    (12, "LRCX", "BUY", "2026-02-05", 213.71, 3.1069, 663.99, 1.50, None, "First buy"),
    # NEM sell
    (11, "NEM", "SELL", "2026-02-06", 113.82, 5.8205, 662.48, 1.50, -2.52, "Sold next day"),
    # SPG sell
    (10, "SPG", "SELL", "2026-02-06", 198.79, 4.9930, 992.55, 1.50, 16.56, "Sold for profit"),
    # LIN
    (13, "LIN", "BUY", "2026-02-06", 452.78, 2.2085, 999.97, 1.50, None, "Initial buy"),
    # BE first buy
    (20, "BE", "BUY", "2026-02-06", 139.87, 4.6400, 649.00, 1.50, None, "First buy"),
    # SYK sell
    (9, "SYK", "SELL", "2026-02-06", 357.98, 2.9989, 1073.56, 1.50, -18.42, "Sold at loss"),
    # ALB first buy
    (14, "ALB", "BUY", "2026-02-06", 162.38, 6.5893, 1069.99, 1.50, None, "First buy"),
    # LIN sell
    (13, "LIN", "SELL", "2026-02-10", 462.90, 2.2085, 1022.31, 1.50, 22.34, "Sold for GOOGL"),
    # GOOGL buy
    (15, "GOOGL", "BUY", "2026-02-10", 318.67, 3.2039, 1020.99, 1.50, None, "Bought with LIN proceeds"),
    # QQQ sell
    (4, "QQQ", "SELL", "2026-02-10", 615.09, 2.3810, 1464.53, 1.50, -2.45, "Sold for VRT"),
    # VRT buy
    (16, "VRT", "BUY", "2026-02-10", 201.80, 7.2447, 1461.99, 1.50, None, "Bought with QQQ proceeds"),
    # VRT sell
    (16, "VRT", "SELL", "2026-02-11", 245.08, 7.2447, 1775.54, 1.50, 313.55, "Sold next day +21.4%"),
    # COHR first buy
    (17, "COHR", "BUY", "2026-02-11", 223.11, 4.7599, 1061.98, 1.50, None, "First buy"),
    # BE second buy
    (20, "BE", "BUY", "2026-02-11", 145.64, 2.5267, 367.99, 1.50, None, "Add shares"),
    # LRCX second buy
    (12, "LRCX", "BUY", "2026-02-11", 234.87, 1.4433, 338.99, 1.50, None, "Add shares"),
    # GOOGL sell
    (15, "GOOGL", "SELL", "2026-02-12", 310.47, 3.2039, 994.72, 1.50, -26.27, "Sold at loss"),
    # COHR second buy
    (17, "COHR", "BUY", "2026-02-12", 217.95, 4.5514, 991.99, 1.50, None, "Add shares"),
    # LRCX sell
    (12, "LRCX", "SELL", "2026-02-13", 237.21, 4.5502, 1079.34, 1.50, 76.36, "Sold all"),
    # BE third buy
    (20, "BE", "BUY", "2026-02-13", 141.78, 8.4635, 1199.99, 1.50, None, "Add shares (big)"),
    # COHR third buy
    (17, "COHR", "BUY", "2026-02-13", 219.05, 4.5651, 999.99, 1.50, None, "Add shares"),
    # ALB second buy
    (14, "ALB", "BUY", "2026-02-13", 166.22, 5.1978, 864.00, 1.50, None, "Add shares"),
    # GHM buy
    (21, "GHM", "BUY", "2026-02-13", 84.88, 8.4703, 719.00, 1.50, None, "Initial buy"),
    # JOUT buy
    (18, "JOUT", "BUY", "2026-02-13", 48.77, 10.2115, 498.00, 1.50, None, "Initial buy"),
    # JOUT sell
    (18, "JOUT", "SELL", "2026-02-18", 48.93, 10.2115, 499.61, 1.50, 1.61, "Small profit"),
    # ALB sell (full position)
    (14, "ALB", "SELL", "2026-02-18", 172.48, 11.7871, 2033.05, 1.50, 99.06, "Sold all 11.7871sh"),
    # CMC buy
    (19, "CMC", "BUY", "2026-02-18", 78.39, 16.9659, 1329.99, 1.50, None, "Initial buy"),
    # BWA buy
    (22, "BWA", "BUY", "2026-02-18", 61.47, 19.0987, 1174.00, 1.50, None, "Initial buy"),
    # CMC sell
    (19, "CMC", "SELL", "2026-02-19", 77.62, 16.9659, 1316.96, 1.50, -13.03, "Swapped to MTRN"),
    # MTRN buy
    (23, "MTRN", "BUY", "2026-02-19", 150.15, 8.7844, 1318.99, 1.50, None, "CMC swap"),
    # COHR sell
    (17, "COHR", "SELL", "2026-02-23", 248.47, 13.8764, 3447.88, 1.50, 393.92, "Sold all 13.8764sh"),
    # WDC buy
    (24, "WDC", "BUY", "2026-02-23", 281.80, 6.3874, 1799.98, 1.50, None, "COHR rotation"),
    # CGNX buy
    (25, "CGNX", "BUY", "2026-02-23", 56.02, 27.5412, 1543.00, 1.50, None, "COHR rotation"),
]


def rebuild_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Backup ILS positions first
    ils_positions = []
    try:
        for row in c.execute("SELECT * FROM positions WHERE currency='ILS'"):
            ils_positions.append(row)
    except Exception:
        pass

    # Clear existing USD data
    c.execute("DELETE FROM transactions")
    c.execute("DELETE FROM positions")
    conn.commit()

    # Insert all positions
    position_ids = {}  # idx -> db id
    for idx, pos in enumerate(POSITIONS):
        ticker, entry_date, exit_date, status, entry_price, shares, cost_basis, \
            exit_price, sell_proceeds, realized_pnl, currency, notes = pos

        c.execute("""
            INSERT INTO positions (ticker, entry_date, exit_date, status, entry_price, shares,
                                   position_type, exit_price, currency, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'LONG', ?, ?, ?, ?)
        """, (ticker, entry_date, exit_date, status, entry_price, shares,
              exit_price, currency, notes, int(datetime.now().timestamp())))

        position_ids[idx] = c.lastrowid

    # Insert all transactions
    for tx in TRANSACTIONS:
        pos_idx, ticker, action, date, price, shares, total, fee, rpnl, notes = tx
        pos_id = position_ids[pos_idx]

        c.execute("""
            INSERT INTO transactions (position_id, ticker, action, date, price, shares,
                                      total, fee, realized_pnl, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pos_id, ticker, action, date, price, shares, total, fee, rpnl, notes,
              datetime.now().isoformat()))

    conn.commit()

    # Verify
    print("=" * 60)
    print("DATABASE REBUILT FROM BROKER STATEMENT")
    print("=" * 60)

    total_positions = c.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    total_txns = c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    total_fees = c.execute("SELECT SUM(fee) FROM transactions").fetchone()[0]
    total_realized = c.execute("SELECT SUM(realized_pnl) FROM transactions WHERE realized_pnl IS NOT NULL").fetchone()[0]

    print(f"\nPositions: {total_positions}")
    print(f"Transactions: {total_txns}")
    print(f"Total Fees: ${total_fees:.2f}")
    print(f"Total Realized P&L: ${total_realized:.2f}")

    # Show all closed positions with P&L
    print(f"\n{'Ticker':<8} {'Entry':<12} {'Exit':<12} {'Days':>5} {'Cost':>10} {'Proceeds':>10} {'P&L':>10} {'P&L%':>8}")
    print("-" * 80)
    for row in c.execute("""
        SELECT ticker, entry_date, exit_date, entry_price, exit_price, notes
        FROM positions WHERE status='CLOSED' AND currency='USD'
        ORDER BY exit_date, entry_date
    """):
        ticker, entry_d, exit_d, entry_p, exit_p, notes = row
        # Find realized P&L from sell transaction
        rpnl = c.execute("""
            SELECT SUM(realized_pnl) FROM transactions
            WHERE position_id = (SELECT id FROM positions WHERE ticker=? AND entry_date=? AND currency='USD' LIMIT 1)
            AND realized_pnl IS NOT NULL
        """, (ticker, entry_d)).fetchone()[0] or 0

        # Find cost basis from buy transactions
        cost = c.execute("""
            SELECT SUM(total) FROM transactions
            WHERE position_id = (SELECT id FROM positions WHERE ticker=? AND entry_date=? AND currency='USD' LIMIT 1)
            AND action='BUY'
        """, (ticker, entry_d)).fetchone()[0] or 0

        # Find sell proceeds
        proceeds = c.execute("""
            SELECT SUM(total) FROM transactions
            WHERE position_id = (SELECT id FROM positions WHERE ticker=? AND entry_date=? AND currency='USD' LIMIT 1)
            AND action='SELL'
        """, (ticker, entry_d)).fetchone()[0] or 0

        from datetime import date as dt_date
        d1 = dt_date.fromisoformat(entry_d)
        d2 = dt_date.fromisoformat(exit_d)
        days = (d2 - d1).days
        pnl_pct = (rpnl / cost * 100) if cost > 0 else 0

        print(f"{ticker:<8} {entry_d:<12} {exit_d:<12} {days:>5}d ${cost:>9.2f} ${proceeds:>9.2f} ${rpnl:>9.2f} {pnl_pct:>7.1f}%")

    # Show open positions
    print(f"\n{'Ticker':<8} {'Entry':<12} {'Shares':>10} {'Avg Price':>10} {'Cost':>10} {'Currency'}")
    print("-" * 65)
    for row in c.execute("""
        SELECT ticker, entry_date, shares, entry_price, currency, notes
        FROM positions WHERE status='OPEN'
        ORDER BY currency, entry_date
    """):
        ticker, entry_d, shares, price, currency, notes = row
        cost = shares * price if currency == 'USD' else shares * price
        print(f"{ticker:<8} {entry_d:<12} {shares:>10.4f} ${price:>9.2f} ${cost:>9.2f} {currency}")

    # Summary
    wins = c.execute("SELECT COUNT(*) FROM positions WHERE status='CLOSED' AND currency='USD' AND id IN (SELECT position_id FROM transactions WHERE realized_pnl > 0)").fetchone()[0]
    losses = c.execute("SELECT COUNT(*) FROM positions WHERE status='CLOSED' AND currency='USD' AND id IN (SELECT position_id FROM transactions WHERE realized_pnl < 0)").fetchone()[0]

    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Total Deposited: ${TOTAL_DEPOSITED:,.2f}")
    print(f"Dividend: ${DIVIDEND:.2f}")
    print(f"Total Capital In: ${TOTAL_DEPOSITED + DIVIDEND:,.2f}")
    print(f"Total Realized P&L: ${total_realized:,.2f}")
    print(f"Total Fees: ${total_fees:,.2f}")
    print(f"Wins: {wins} | Losses: {losses} | Win Rate: {wins/(wins+losses)*100:.0f}%")
    print(f"Broker Portfolio Value (23.02): $9,024.86")
    print(f"Total Account P&L: ${9024.86 - TOTAL_DEPOSITED - DIVIDEND:,.2f}")

    conn.close()


if __name__ == "__main__":
    rebuild_db()
