"""
Alert System for Trading Dashboard
====================================
Email (SMTP/Gmail) + Telegram Bot notifications.
Sends buy/sell signals, health alerts, upgrade opportunities, and portfolio reports.
"""

import asyncio
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Dict, List, Optional

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "data", "alerts_config.json")

DEFAULT_CONFIG = {
    "enabled": bool(os.environ.get("ALERT_EMAIL", "")),
    # Email
    "email": os.environ.get("ALERT_EMAIL", ""),
    "smtp_server": os.environ.get("SMTP_SERVER", "smtp.gmail.com"),
    "smtp_port": int(os.environ.get("SMTP_PORT", "587")),
    "smtp_user": os.environ.get("SMTP_USER", ""),
    "smtp_password": os.environ.get("SMTP_PASSWORD", ""),
    # Notification types
    "notify_sell_signals": True,
    "notify_buy_signals": True,
    "notify_upgrades": True,
    "notify_critical_alerts": True,
    "notify_earnings_warning": True,
}


_config_cache: Optional[Dict] = None
_config_cache_time: float = 0

def load_config() -> Dict:
    """Load config with 60-second in-memory cache to avoid disk reads on every alert."""
    global _config_cache, _config_cache_time
    import time
    now = time.time()
    if _config_cache and (now - _config_cache_time) < 60:
        return _config_cache
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            _config_cache = {**DEFAULT_CONFIG, **json.load(f)}
    else:
        _config_cache = DEFAULT_CONFIG.copy()
    _config_cache_time = now
    return _config_cache


def save_config(config: Dict):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


# ── Email via SMTP ──

def _send_email_sync(subject: str, html_body: str, config: Optional[Dict] = None) -> bool:
    """Send an email using SMTP (blocking). Use _send_email() for async callers."""
    cfg = config or load_config()
    if not cfg.get("enabled") or not cfg.get("email"):
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Trading Alert] {subject}"
    msg["From"] = cfg.get("smtp_user", cfg["email"])
    msg["To"] = cfg["email"]
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"], timeout=10) as server:
            server.starttls()
            server.login(cfg["smtp_user"], cfg["smtp_password"])
            server.send_message(msg)
        print(f"[Email] Sent: {subject}")
        return True
    except Exception as e:
        print(f"[Email] Failed: {e}")
        return False


async def _send_email(subject: str, html_body: str, config: Optional[Dict] = None) -> bool:
    """Send an email using SMTP in a background thread (non-blocking)."""
    return await asyncio.to_thread(_send_email_sync, subject, html_body, config)


async def _notify(subject: str, html_body: str, text_msg: str = "", config: Optional[Dict] = None):
    """Send via email (non-blocking)."""
    cfg = config or load_config()
    return await _send_email(subject, html_body, cfg)


# ── Signal Alerts ──

async def send_signal_alert(signals: List[Dict]):
    """Send alert for buy/sell/rotation signals."""
    cfg = load_config()
    if not cfg.get("enabled"):
        return

    sell_signals = [s for s in signals if s.get("action") in ("SELL", "ROTATION")]
    buy_signals = [s for s in signals if s.get("action") == "BUY"]

    if not sell_signals and not buy_signals:
        return

    # HTML for email
    rows = ""
    for s in signals:
        color = "#ef4444" if s["action"] in ("SELL", "ROTATION") else "#10b981"
        rows += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #333;color:#fff">{s['ticker']}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:{color};font-weight:bold">{s['action']}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#aaa">${s.get('price', 0):.2f}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#aaa">{s.get('reason', '')}</td>
        </tr>"""

    html = f"""
    <div style="background:#0a0a0a;padding:24px;font-family:monospace;max-width:600px">
        <h2 style="color:#fff;margin:0 0 16px">Trading Signals</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr style="color:#666">
                <th style="padding:8px;text-align:left">Ticker</th>
                <th style="padding:8px;text-align:left">Signal</th>
                <th style="padding:8px;text-align:left">Price</th>
                <th style="padding:8px;text-align:left">Reason</th>
            </tr>
            {rows}
        </table>
        <p style="color:#666;font-size:12px;margin-top:16px">
            {datetime.now().strftime('%Y-%m-%d %H:%M')} | ATLAS V2
        </p>
    </div>"""

    # WhatsApp text
    lines = [f"{'🔴' if s['action'] in ('SELL', 'ROTATION') else '🟢'} {s['action']} {s['ticker']} ${s.get('price', 0):.2f}" for s in signals]
    wa_text = f"📊 *Trading Signal*\n" + "\n".join(lines)

    subject = f"{'SELL' if sell_signals else 'BUY'} Signal: {', '.join(s['ticker'] for s in signals)}"
    await _notify(subject, html, wa_text, cfg)


# ── Health Alerts ──

async def send_health_alert(alerts: List[Dict]):
    """Send alert for critical health issues."""
    cfg = load_config()
    if not cfg.get("enabled") or not cfg.get("notify_critical_alerts"):
        return

    critical = [a for a in alerts if a.get("severity") == "CRITICAL"]
    if not critical:
        return

    rows = ""
    for a in critical:
        rows += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #333;color:#fff">{a.get('ticker', '?')}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#ef4444">{a.get('signal', '?')}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#aaa">{a.get('summary', '')}</td>
        </tr>"""

    html = f"""
    <div style="background:#0a0a0a;padding:24px;font-family:monospace;max-width:600px">
        <h2 style="color:#ef4444;margin:0 0 16px">CRITICAL Portfolio Alert</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr style="color:#666">
                <th style="padding:8px;text-align:left">Ticker</th>
                <th style="padding:8px;text-align:left">Signal</th>
                <th style="padding:8px;text-align:left">Issue</th>
            </tr>
            {rows}
        </table>
        <p style="color:#666;font-size:12px;margin-top:16px">
            {datetime.now().strftime('%Y-%m-%d %H:%M')} | Portfolio Health Monitor
        </p>
    </div>"""

    lines = [f"🔴 {a.get('ticker','?')}: {a.get('summary','')}" for a in critical]
    wa_text = f"🚨 *CRITICAL Alert*\n" + "\n".join(lines)

    await _notify(f"CRITICAL: {len(critical)} alerts", html, wa_text, cfg)


# ── Upgrade Alerts ──

async def send_upgrade_alert(upgrades: List[Dict]):
    """Send alert for upgrade opportunities."""
    cfg = load_config()
    if not cfg.get("enabled") or not cfg.get("notify_upgrades"):
        return
    if not upgrades:
        return

    rows = ""
    for u in upgrades:
        rows += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #333;color:#10b981;font-weight:bold">{u['ticker']}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#fff">replaces {', '.join(u.get('beats', []))}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#aaa">{u.get('score', 0):.2f}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#aaa">{u.get('win_rate', 0):.0f}%</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#10b981">+{u.get('zone_return', 0):.1f}%</td>
        </tr>"""

    html = f"""
    <div style="background:#0a0a0a;padding:24px;font-family:monospace;max-width:600px">
        <h2 style="color:#10b981;margin:0 0 16px">Upgrade Opportunity</h2>
        <table style="width:100%;border-collapse:collapse">
            <tr style="color:#666">
                <th style="padding:8px;text-align:left">Ticker</th>
                <th style="padding:8px;text-align:left">Replaces</th>
                <th style="padding:8px;text-align:left">Score</th>
                <th style="padding:8px;text-align:left">WR</th>
                <th style="padding:8px;text-align:left">Zone Ret</th>
            </tr>
            {rows}
        </table>
        <p style="color:#666;font-size:12px;margin-top:16px">
            {datetime.now().strftime('%Y-%m-%d %H:%M')} | Deep Scanner
        </p>
    </div>"""

    lines = [f"🟢 {u['ticker']} (score {u.get('score',0):.1f}, WR {u.get('win_rate',0):.0f}%, +{u.get('zone_return',0):.1f}%) → replaces {', '.join(u.get('beats',[]))}" for u in upgrades]
    wa_text = f"📈 *Upgrade Found*\n" + "\n".join(lines)

    await _notify(f"Upgrade: {', '.join(u['ticker'] for u in upgrades)}", html, wa_text, cfg)


# ── Price Level Alerts (Stop Loss / Target Hit) ──

async def send_price_level_alert(alerts: List[Dict]):
    """
    Send alert when price hits stop loss or target.
    Each alert: {ticker, alert_type, price, level, entry_price, pnl_pct, shares}
    alert_type: "STOP_LOSS", "TARGET_1", "TARGET_2"
    """
    cfg = load_config()
    if not cfg.get("enabled"):
        return

    rows = ""
    for a in alerts:
        at = a.get("alert_type", "")
        if at == "STOP_LOSS":
            color = "#ef4444"
            icon = "STOP LOSS"
        elif at == "TARGET_2":
            color = "#10b981"
            icon = "TARGET 2 HIT"
        else:
            color = "#f59e0b"
            icon = "TARGET 1 HIT"

        pnl_pct = a.get("pnl_pct", 0)
        pnl_color = "#10b981" if pnl_pct >= 0 else "#ef4444"
        rows += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #333;color:#fff;font-weight:bold">{a['ticker']}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:{color};font-weight:bold">{icon}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#fff">${a.get('price', 0):.2f}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#aaa">Level: ${a.get('level', 0):.2f}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:{pnl_color}">{'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%</td>
        </tr>"""

    stop_alerts = [a for a in alerts if a["alert_type"] == "STOP_LOSS"]
    target_alerts = [a for a in alerts if a["alert_type"] != "STOP_LOSS"]

    html = f"""
    <div style="background:#0a0a0a;padding:24px;font-family:monospace;max-width:600px">
        <h2 style="color:{'#ef4444' if stop_alerts else '#10b981'};margin:0 0 16px">
            {'STOP LOSS' if stop_alerts else 'TARGET'} Alert
        </h2>
        <table style="width:100%;border-collapse:collapse">
            <tr style="color:#666">
                <th style="padding:8px;text-align:left">Ticker</th>
                <th style="padding:8px;text-align:left">Alert</th>
                <th style="padding:8px;text-align:left">Price</th>
                <th style="padding:8px;text-align:left">Level</th>
                <th style="padding:8px;text-align:left">P&L</th>
            </tr>
            {rows}
        </table>
        <p style="color:#aaa;font-size:13px;margin-top:16px">
            {'Sell immediately to limit losses.' if stop_alerts else 'Consider taking profit.'}
        </p>
        <p style="color:#666;font-size:12px;margin-top:8px">
            {datetime.now().strftime('%Y-%m-%d %H:%M')} | ATLAS V2 Price Monitor
        </p>
    </div>"""

    tickers = ", ".join(a["ticker"] for a in alerts)
    types = "STOP LOSS" if stop_alerts else "TARGET HIT"
    lines = []
    for a in alerts:
        at = a.get("alert_type", "")
        emoji = "🔴" if at == "STOP_LOSS" else "🟢"
        lines.append(f"{emoji} {a['ticker']} ${a.get('price',0):.2f} ({'+' if a.get('pnl_pct',0) >= 0 else ''}{a.get('pnl_pct',0):.1f}%)")
    wa_text = f"{'🚨' if stop_alerts else '🎯'} *{types}*\n" + "\n".join(lines)

    await _notify(f"{types}: {tickers}", html, wa_text, cfg)


# ── Exit Strategy Trigger Alerts ──

async def send_exit_trigger_alert(triggers: List[Dict]):
    """
    Send alert when a per-stock exit strategy fires (SMA crossover, RSI threshold, fixed hold, etc.).
    Each trigger: {ticker, strategy, price, entry_price, pnl_pct, oos_wr, is_wr, overfit, validation, ci_lo, ci_hi, label}
    """
    cfg = load_config()
    if not cfg.get("enabled") or not cfg.get("notify_sell_signals"):
        return
    if not triggers:
        return

    rows = ""
    for t in triggers:
        val = t.get("validation", "")
        val_color = "#10b981" if val == "VALID" else "#f59e0b" if val in ("CAUTION", "LOW_DATA") else "#ef4444"
        pnl_pct = t.get("pnl_pct", 0)
        pnl_color = "#10b981" if pnl_pct >= 0 else "#ef4444"
        overfit = t.get("overfit", 0)
        overfit_warn = f' <span style="color:#f59e0b">{overfit:.1f}x</span>' if overfit > 1.3 else ""
        rows += f"""
        <tr>
            <td style="padding:8px;border-bottom:1px solid #333;color:#fff;font-weight:bold">{t['ticker']}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#f59e0b;font-weight:bold">{t['strategy']}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#fff">${t.get('price', 0):.2f}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:{pnl_color}">{'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:#aaa">OOS {t.get('oos_wr', 0):.0f}%{overfit_warn}</td>
            <td style="padding:8px;border-bottom:1px solid #333;color:{val_color};font-weight:bold">{val}</td>
        </tr>"""

    html = f"""
    <div style="background:#0a0a0a;padding:24px;font-family:monospace;max-width:650px">
        <h2 style="color:#f59e0b;margin:0 0 8px">Exit Strategy Triggered</h2>
        <p style="color:#aaa;margin:0 0 16px;font-size:13px">
            Walk-forward validated exit conditions met. Review and consider selling.
        </p>
        <table style="width:100%;border-collapse:collapse;font-size:12px">
            <tr style="color:#666;font-size:11px">
                <th style="padding:8px;text-align:left">Ticker</th>
                <th style="padding:8px;text-align:left">Strategy</th>
                <th style="padding:8px;text-align:left">Price</th>
                <th style="padding:8px;text-align:left">P&L</th>
                <th style="padding:8px;text-align:left">OOS WR</th>
                <th style="padding:8px;text-align:left">Status</th>
            </tr>
            {rows}
        </table>
        <p style="color:#666;font-size:11px;margin-top:16px;border-top:1px solid #333;padding-top:12px">
            {datetime.now().strftime('%Y-%m-%d %H:%M')} | ATLAS V2 Exit Monitor
        </p>
    </div>"""

    tickers = ", ".join(t["ticker"] for t in triggers)
    await _notify(f"EXIT: {tickers}", html, "", cfg)


# ── Portfolio Report ──

async def send_portfolio_report(positions: List[Dict], buy_signals: List[Dict], upgrades: List[Dict]) -> bool:
    """
    Send full portfolio report with:
    - Current holdings with P&L and signals
    - BUY signals from portfolio (positions with BUY signal)
    - Upgrade opportunities from scanner
    """
    cfg = load_config()

    # Holdings table
    pos_rows = ""
    total_value = 0
    total_pnl = 0
    for p in positions:
        pnl = p.get("pnl", 0)
        pnl_pct = p.get("pnl_pct", 0)
        signal = p.get("signal", "HOLD")
        color = "#10b981" if pnl >= 0 else "#ef4444"
        sig_color = "#10b981" if signal == "BUY" else "#ef4444" if signal in ("SELL", "ROTATION") else "#aaa"
        total_value += p.get("current_value", 0)
        total_pnl += pnl
        pos_rows += f"""
        <tr>
            <td style="padding:6px 8px;border-bottom:1px solid #333;color:#fff;font-weight:bold">{p['ticker']}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #333;color:#aaa">{p.get('shares', 0):.2f}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #333;color:#aaa">${p.get('current_price', 0):.2f}</td>
            <td style="padding:6px 8px;border-bottom:1px solid #333;color:{color}">{'+' if pnl >= 0 else ''}${pnl:.2f} ({'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%)</td>
            <td style="padding:6px 8px;border-bottom:1px solid #333;color:#aaa">{p.get('win_rate', 0):.0f}%</td>
            <td style="padding:6px 8px;border-bottom:1px solid #333;color:{sig_color};font-weight:bold">{signal}</td>
        </tr>"""

    # Buy signals section
    buy_section = ""
    if buy_signals:
        buy_rows = ""
        for b in buy_signals:
            buy_rows += f"""
            <tr>
                <td style="padding:6px 8px;border-bottom:1px solid #333;color:#10b981;font-weight:bold">{b['ticker']}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #333;color:#aaa">${b.get('price', 0):.2f}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #333;color:#aaa">{b.get('win_rate', 0):.0f}%</td>
                <td style="padding:6px 8px;border-bottom:1px solid #333;color:#10b981">+{b.get('zone_return', 0):.1f}%</td>
                <td style="padding:6px 8px;border-bottom:1px solid #333;color:#aaa">{b.get('score', 0):.2f}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #333;color:#aaa">{b.get('reason', '')}</td>
            </tr>"""
        buy_section = f"""
        <h3 style="color:#10b981;margin:20px 0 8px">🟢 BUY Signals</h3>
        <table style="width:100%;border-collapse:collapse">
            <tr style="color:#666;font-size:11px">
                <th style="padding:6px 8px;text-align:left">Ticker</th>
                <th style="padding:6px 8px;text-align:left">Price</th>
                <th style="padding:6px 8px;text-align:left">WR</th>
                <th style="padding:6px 8px;text-align:left">Zone Ret</th>
                <th style="padding:6px 8px;text-align:left">Score</th>
                <th style="padding:6px 8px;text-align:left">Reason</th>
            </tr>
            {buy_rows}
        </table>"""

    # Upgrades section
    upgrade_section = ""
    if upgrades:
        upg_rows = ""
        for u in upgrades:
            upg_rows += f"""
            <tr>
                <td style="padding:6px 8px;border-bottom:1px solid #333;color:#3b82f6;font-weight:bold">{u['ticker']}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #333;color:#fff">→ {', '.join(u.get('beats', []))}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #333;color:#aaa">{u.get('score', 0):.2f}</td>
                <td style="padding:6px 8px;border-bottom:1px solid #333;color:#aaa">{u.get('win_rate', 0):.0f}%</td>
                <td style="padding:6px 8px;border-bottom:1px solid #333;color:#10b981">+{u.get('zone_return', 0):.1f}%</td>
            </tr>"""
        upgrade_section = f"""
        <h3 style="color:#3b82f6;margin:20px 0 8px">📈 Upgrade Opportunities</h3>
        <table style="width:100%;border-collapse:collapse">
            <tr style="color:#666;font-size:11px">
                <th style="padding:6px 8px;text-align:left">Ticker</th>
                <th style="padding:6px 8px;text-align:left">Replaces</th>
                <th style="padding:6px 8px;text-align:left">Score</th>
                <th style="padding:6px 8px;text-align:left">WR</th>
                <th style="padding:6px 8px;text-align:left">Zone Ret</th>
            </tr>
            {upg_rows}
        </table>"""

    pnl_color = "#10b981" if total_pnl >= 0 else "#ef4444"
    html = f"""
    <div style="background:#0a0a0a;padding:24px;font-family:monospace;max-width:650px">
        <h2 style="color:#fff;margin:0 0 4px">Portfolio Report</h2>
        <p style="color:#aaa;margin:0 0 16px;font-size:13px">
            Value: <b style="color:#fff">${total_value:,.2f}</b> |
            P&L: <b style="color:{pnl_color}">{'+' if total_pnl >= 0 else ''}${total_pnl:,.2f}</b>
        </p>
        <table style="width:100%;border-collapse:collapse;font-size:12px">
            <tr style="color:#666;font-size:11px">
                <th style="padding:6px 8px;text-align:left">Ticker</th>
                <th style="padding:6px 8px;text-align:left">Shares</th>
                <th style="padding:6px 8px;text-align:left">Price</th>
                <th style="padding:6px 8px;text-align:left">P&L</th>
                <th style="padding:6px 8px;text-align:left">WR</th>
                <th style="padding:6px 8px;text-align:left">Signal</th>
            </tr>
            {pos_rows}
        </table>
        {buy_section}
        {upgrade_section}
        <p style="color:#666;font-size:11px;margin-top:20px;border-top:1px solid #333;padding-top:12px">
            {datetime.now().strftime('%Y-%m-%d %H:%M')} | ATLAS V2 Trading Dashboard
        </p>
    </div>"""

    # WhatsApp text version
    wa_lines = [f"📊 *Portfolio Report*", f"Value: ${total_value:,.0f} | P&L: {'+' if total_pnl >= 0 else ''}${total_pnl:,.0f}", ""]
    wa_lines.append("*Holdings:*")
    for p in positions:
        pnl = p.get("pnl", 0)
        sig = p.get("signal", "HOLD")
        icon = "🟢" if sig == "BUY" else "🔴" if sig in ("SELL", "ROTATION") else "⚪"
        wa_lines.append(f"{icon} {p['ticker']} {p.get('shares',0):.1f}sh ${p.get('current_price',0):.0f} {'+' if pnl >= 0 else ''}${pnl:.0f} ({sig})")

    if buy_signals:
        wa_lines.append("")
        wa_lines.append("*BUY Signals:*")
        for b in buy_signals:
            wa_lines.append(f"🟢 {b['ticker']} ${b.get('price',0):.0f} WR:{b.get('win_rate',0):.0f}% +{b.get('zone_return',0):.1f}%")

    if upgrades:
        wa_lines.append("")
        wa_lines.append("*Upgrades:*")
        for u in upgrades:
            wa_lines.append(f"📈 {u['ticker']} (score {u.get('score',0):.1f}) → {', '.join(u.get('beats',[]))}")

    wa_text = "\n".join(wa_lines)

    subject = f"Portfolio: ${total_value:,.0f} ({'+' if total_pnl >= 0 else ''}${total_pnl:,.0f})"
    return await _notify(subject, html, wa_text, cfg)


# ── Test Functions ──

async def send_test_email() -> bool:
    """Send a test email to verify email configuration."""
    html = f"""
    <div style="background:#0a0a0a;padding:24px;font-family:monospace;max-width:600px">
        <h2 style="color:#10b981;margin:0 0 16px">Test Alert</h2>
        <p style="color:#fff">Email notifications are working correctly.</p>
        <p style="color:#666;font-size:12px;margin-top:16px">
            {datetime.now().strftime('%Y-%m-%d %H:%M')} | Trading Dashboard
        </p>
    </div>"""
    return await _send_email("Test - Notifications Working", html)


