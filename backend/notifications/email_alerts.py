"""
emil_alerts.py - Email notification service for the trading bot.
Sends transactional emails for trade events, risk alerts, and errors.
Uses Python's built-in smtplib with no external dependencies.

Configuration (from .env):
    SMTP_EMAIL     - Sender email address
    SMTP_PASSWORD  - SMTP app password
    SMTP_TO        - Recipient email address
    SMTP_HOST      - SMTP server host (default: smtp.gmail.com)
    SMTP_PORT      - SMTP server port (default: 587)
"""
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from typing import Optional, Any, List

from backend.config import (
    SMTP_EMAIL, SMTP_PASSWORD, SMTP_TO,
    SMTP_HOST, SMTP_PORT,
    POSITION_SIZE_USDT, MAX_DAILY_LOSS_USDT,
    BTC_TRIGGER_PCT, TP_PCT, SL_PCT,
)
from backend.database.db import log_event


class EmailNotifier:
    """
    Sends email alerts for bot events.
    Gracefully handles missing SMTP config — silently skips if not configured.
    """

    def __init__(self):
        # Check env vars at runtime so tests and runtime config changes take effect
        self._configured = all([
            os.environ.get("SMTP_EMAIL", ""),
            os.environ.get("SMTP_PASSWORD", ""),
            os.environ.get("SMTP_TO", ""),
        ])

    @property
    def is_configured(self) -> bool:
        """Check if SMTP is fully configured."""
        return self._configured

    # ─── Public Alert Methods ─────────────────────────────────

    def send_trade_entry(self, signal_side: str, btc_return_pct: float,
                         entries: List[dict], failed: List[dict]) -> bool:
        """
        Send alert when a signal fires and positions are entered.

        Args:
            signal_side: 'LONG' or 'SHORT'
            btc_return_pct: BTC move percentage that triggered the signal
            entries: List of successful entry records
            failed: List of failed entry records

        Returns:
            True if sent successfully, False otherwise
        """
        if not self._configured:
            return False

        n = len(entries)
        subject = f"🟢 {signal_side} SIGNAL — {n} Position{'s' if n != 1 else ''} Entered"

        body_lines = [
            f"<h2>🚀 Trade Signal Executed</h2>",
            f"<p><b>Signal:</b> {signal_side} | <b>BTC Move:</b> {btc_return_pct:+.2f}%</p>",
            f"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-size:13px'>",
            f"<tr style='background:#1a1a2e;color:#e0e0e0'>",
            f"<th>Coin</th><th>Side</th><th>Entry</th><th>Qty</th><th>TP</th><th>SL</th><th>Method</th>",
            f"</tr>",
        ]

        for e in entries:
            body_lines.append(
                f"<tr>"
                f"<td>{e.get('coin', '?')}</td>"
                f"<td>{signal_side}</td>"
                f"<td>${e.get('entry_price', 0):.6f}</td>"
                f"<td>{e.get('filled_qty', 0):.4f}</td>"
                f"<td>${e.get('tp_price', 0):.4f}</td>"
                f"<td>${e.get('sl_price', 0):.4f}</td>"
                f"<td>{e.get('execution_method', '?')}</td>"
                f"</tr>"
            )

        body_lines.append("</table>")

        if failed:
            body_lines.append(
                f"<h3 style='color:#ff6b6b'>⚠️ {len(failed)} Failed</h3>"
                f"<ul>"
            )
            for f in failed:
                body_lines.append(
                    f"<li>{f.get('coin', '?')}: {f.get('reason', 'unknown')}</li>"
                )
            body_lines.append("</ul>")

        body_lines.append(
            f"<hr><p style='color:#888;font-size:11px'>"
            f"Position Size: ${POSITION_SIZE_USDT:.0f} | "
            f"TP: {TP_PCT}% | SL: {SL_PCT}%<br>"
            f"{self._timestamp()}</p>"
        )

        return self._send(subject, "\n".join(body_lines))

    def send_trade_exit(self, exit_type: str, symbol: str, side: str,
                        entry_price: float, exit_price: float,
                        pnl_usdt: float, pnl_pct: float,
                        exit_time: str) -> bool:
        """
        Send alert when a position exits.

        Args:
            exit_type: 'tp_hit', 'sl_hit', 'timeout', 'emergency_exit', 'external_exit'
            symbol: Trading pair symbol
            side: 'LONG' or 'SHORT'
            entry_price, exit_price, pnl_usdt, pnl_pct: Trade details
            exit_time: IST timestamp string
        """
        if not self._configured:
            return False

        if exit_type == 'tp_hit':
            emoji = "🟢"
            label = "Take Profit Hit"
        elif exit_type == 'sl_hit' or exit_type == 'app_sl_hit':
            emoji = "🔴"
            label = "Stop Loss Hit"
        elif exit_type == 'timeout':
            emoji = "🟡"
            label = "Window Timeout Exit"
        elif exit_type == 'emergency_exit':
            emoji = "🚨"
            label = "Emergency Exit"
        else:
            emoji = "ℹ️"
            label = "Exit"

        pnl_sign = "+" if pnl_usdt >= 0 else "-"
        subject = f"{emoji} {exit_type.upper()} — {symbol} ({pnl_sign}${abs(pnl_usdt):.2f})"

        body = (
            f"<h2>{emoji} Position Exit</h2>"
            f"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-size:13px'>"
            f"<tr><td><b>Symbol</b></td><td>{symbol}</td></tr>"
            f"<tr><td><b>Side</b></td><td>{side}</td></tr>"
            f"<tr><td><b>Exit Type</b></td><td>{label}</td></tr>"
            f"<tr><td><b>Entry Price</b></td><td>${entry_price:.6f}</td></tr>"
            f"<tr><td><b>Exit Price</b></td><td>${exit_price:.6f}</td></tr>"
            f"<tr><td><b>PnL</b></td><td style='color:{'#00d68f' if pnl_usdt >= 0 else '#ff6b6b'};font-weight:bold'>"
            f"{pnl_sign}$ {abs(pnl_usdt):.2f} ({pnl_pct:+.2f}%)</td></tr>"
            f"<tr><td><b>Exit Time (IST)</b></td><td>{exit_time}</td></tr>"
            f"</table>"
            f"<hr><p style='color:#888;font-size:11px'>{self._timestamp()}</p>"
        )

        return self._send(subject, body)

    def send_risk_alert(self, alert_type: str, details: str,
                        metrics: Optional[dict] = None) -> bool:
        """
        Send alert when a risk gate blocks trading.

        Args:
            alert_type: 'daily_loss_limit', 'circuit_breaker', 'max_daily_trades',
                       'trading_hours', 'insufficient_balance'
            details: Human-readable description
            metrics: Optional dict with risk state values
        """
        if not self._configured:
            return False

        subject = f"⚠️ RISK: {alert_type.replace('_', ' ').title()}"

        body_lines = [
            f"<h2>⚠️ Risk Gate Triggered</h2>",
            f"<p><b>Gate:</b> {alert_type}</p>",
            f"<p><b>Details:</b> {details}</p>",
        ]

        if metrics:
            body_lines.append("<h3>Current Risk State:</h3><ul>")
            for k, v in metrics.items():
                body_lines.append(f"<li><b>{k}:</b> {v}</li>")
            body_lines.append("</ul>")

        body_lines.append(
            f"<hr><p style='color:#888;font-size:11px'>{self._timestamp()}</p>"
        )

        return self._send(subject, "\n".join(body_lines))

    def send_error_alert(self, module: str, error_message: str,
                         context: Optional[str] = None) -> bool:
        """
        Send alert for errors (API failures, orphans, etc).

        Args:
            module: Which module the error occurred in
            error_message: The error description
            context: Optional additional context
        """
        if not self._configured:
            return False

        subject = f"🚨 ERROR — {module}: {error_message[:60]}"

        body = (
            f"<h2>🚨 Bot Error</h2>"
            f"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-size:13px'>"
            f"<tr><td><b>Module</b></td><td>{module}</td></tr>"
            f"<tr><td><b>Error</b></td><td style='color:#ff6b6b'>{error_message}</td></tr>"
        )
        if context:
            body += f"<tr><td><b>Context</b></td><td>{context}</td></tr>"
        body += (
            f"</table>"
            f"<hr><p style='color:#888;font-size:11px'>{self._timestamp()}</p>"
        )

        return self._send(subject, body)

    def send_startup(self, bot_version: str, db_path: str,
                     config_summary: str) -> bool:
        """
        Send alert when the bot starts.

        Args:
            bot_version: Version string
            db_path: Path to database
            config_summary: Brief config overview
        """
        if not self._configured:
            return False

        subject = f"🟢 Bot Started — v{bot_version}"

        body = (
            f"<h2>🟢 Trading Bot Started</h2>"
            f"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-size:13px'>"
            f"<tr><td><b>Version</b></td><td>{bot_version}</td></tr>"
            f"<tr><td><b>Database</b></td><td>{db_path}</td></tr>"
            f"<tr><td><b>Config</b></td><td>{config_summary}</td></tr>"
            f"<tr><td><b>Start Time (UTC)</b></td><td>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}</td></tr>"
            f"</table>"
            f"<hr><p style='color:#888;font-size:11px'>{self._timestamp()}</p>"
        )

        return self._send(subject, body)

    def send_shutdown(self, uptime_seconds: float) -> bool:
        """Send alert when the bot shuts down."""
        if not self._configured:
            return False

        uptime_str = str(timedelta(seconds=int(uptime_seconds)))
        subject = f"🔴 Bot Shutdown — Uptime: {uptime_str}"

        body = (
            f"<h2>🔴 Trading Bot Shutdown</h2>"
            f"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-size:13px'>"
            f"<tr><td><b>Uptime</b></td><td>{uptime_str}</td></tr>"
            f"<tr><td><b>Shutdown Time (UTC)</b></td><td>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}</td></tr>"
            f"</table>"
            f"<hr><p style='color:#888;font-size:11px'>{self._timestamp()}</p>"
        )

        return self._send(subject, body)

    def send_status_summary(self, status_data: dict) -> bool:
        """
        Send a periodic status summary email.

        Args:
            status_data: Dict with keys like in_trade, daily_trade_count,
                        daily_pnl, consecutive_losses, etc.
        """
        if not self._configured:
            return False

        now_ist = datetime.now(timezone.utc) + timedelta(hours=5.5)
        subject = f"📊 Bot Status — {now_ist.strftime('%Y-%m-%d %H:%M')} IST"

        in_trade = status_data.get('in_trade', False)
        health_emoji = "🟢" if status_data.get('health') == 'ok' else "🔴"

        body = (
            f"<h2>{health_emoji} Bot Status Report</h2>"
            f"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;font-size:13px'>"
            f"<tr><td><b>Status</b></td><td>{status_data.get('health', '?')}</td></tr>"
            f"<tr><td><b>In Trade</b></td><td>{'Yes' if in_trade else 'No'}</td></tr>"
            f"<tr><td><b>BTC Price</b></td><td>${status_data.get('btc_current', 0):,.2f}</td></tr>"
            f"<tr><td><b>Daily Trades</b></td><td>{status_data.get('daily_trade_count', 0)}</td></tr>"
            f"<tr><td><b>Daily PnL</b></td><td style='color:{'#00d68f' if status_data.get('daily_pnl', 0) >= 0 else '#ff6b6b'};font-weight:bold'>"
            f"${status_data.get('daily_pnl', 0):+.2f}</td></tr>"
            f"<tr><td><b>Max Daily Loss</b></td><td>${MAX_DAILY_LOSS_USDT:.0f}</td></tr>"
            f"<tr><td><b>Consecutive Losses</b></td><td>{status_data.get('consecutive_losses', 0)}</td></tr>"
            f"<tr><td><b>Circuit Breaker</b></td><td>{'⚠️ Active' if status_data.get('circuit_breaker_triggered', False) else '✅ Normal'}</td></tr>"
            f"</table>"
            f"<hr><p style='color:#888;font-size:11px'>{self._timestamp()}</p>"
        )

        return self._send(subject, body)

    def send_test(self) -> bool:
        """Send a test email to verify SMTP configuration."""
        if not self._configured:
            return False

        subject = "🧪 Test Email — BTC Leads Bot"
        body = (
            f"<h2>✅ SMTP Test Successful</h2>"
            f"<p>Your email notification configuration is working.</p>"
            f"<p>You will now receive alerts for:</p>"
            f"<ul>"
            f"<li>🟢 Trade entries with position details</li>"
            f"<li>🔴 Trade exits with PnL</li>"
            f"<li>⚠️ Risk gate activations</li>"
            f"<li>🚨 Errors and anomalies</li>"
            f"<li>🟢🔴 Bot startup/shutdown</li>"
            f"<li>📊 Periodic status summaries</li>"
            f"</ul>"
            f"<hr><p style='color:#888;font-size:11px'>{self._timestamp()}</p>"
        )

        return self._send(subject, body)

    # ─── SMTP Sending ─────────────────────────────────────────

    def _send(self, subject: str, html_body: str) -> bool:
        """
        Send an HTML email via SMTP.
        Returns True if sent, False on failure (logged).
        """
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = SMTP_EMAIL
            msg['To'] = SMTP_TO
            msg['Subject'] = subject

            # Plain text fallback
            plain_text = self._strip_html(html_body)
            msg.attach(MIMEText(plain_text, 'plain', 'utf-8'))
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

            context = ssl.create_default_context()
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.starttls(context=context)
                server.login(SMTP_EMAIL, SMTP_PASSWORD)
                server.sendmail(SMTP_EMAIL, SMTP_TO, msg.as_string())

            log_event('INFO', 'email', f"Sent: {subject}")
            return True

        except smtplib.SMTPAuthenticationError:
            log_event('ERROR', 'email',
                      "SMTP auth failed — check SMTP_EMAIL/SMTP_PASSWORD in .env")
        except smtplib.SMTPException as e:
            log_event('ERROR', 'email',
                      f"SMTP error sending '{subject[:40]}': {e}")
        except Exception as e:
            log_event('ERROR', 'email',
                      f"Failed to send '{subject[:40]}': {e}")

        return False

    @staticmethod
    def _strip_html(html: str) -> str:
        """Very basic HTML-to-text conversion for plain text fallback."""
        import re
        text = re.sub(r'<br\s*/?>', '\n', html)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    @staticmethod
    def _timestamp() -> str:
        """Get formatted timestamp."""
        now = datetime.now(timezone.utc)
        now_ist = now + timedelta(hours=5.5)
        return f"Sent: {now_ist.strftime('%Y-%m-%d %H:%M:%S')} IST (UTC)"


# ─── Module-level singleton ──────────────────────────────────
_notifier: Optional[EmailNotifier] = None


def get_notifier() -> EmailNotifier:
    """Get or create the EmailNotifier singleton."""
    global _notifier
    if _notifier is None:
        _notifier = EmailNotifier()
    return _notifier
