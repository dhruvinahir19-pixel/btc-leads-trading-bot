"""
emil_alerts.py - Email notification service for the trading bot.
Sends transactional emails for trade events, risk alerts, and errors.
Supports multiple delivery methods (tried in order):
  1. Brevo HTTP API (preferred — uses HTTPS/443, works on Render free tier)
  2. SendGrid HTTP API (fallback — also uses HTTPS/443)
  3. SMTP (last resort — requires port 587/465, blocked on Render free tier)

Configuration (from .env):
    Brevo API (recommended for Render):
        BREVO_API_KEY  - API key from brevo.com (free tier: 300 emails/day)
        SMTP_EMAIL     - Sender email address
        SMTP_TO        - Recipient email address
    
    SendGrid API (alternative HTTPS option):
        SENDGRID_API_KEY - API key from sendgrid.com (free tier: 100 emails/day)
        SMTP_EMAIL       - Sender email address
        SMTP_TO          - Recipient email address
    
    SMTP (last resort):
        SMTP_EMAIL     - Sender email address
        SMTP_PASSWORD  - SMTP app password
        SMTP_TO        - Recipient email address
        SMTP_HOST      - SMTP server host (default: smtp.gmail.com)
        SMTP_PORT      - SMTP server port (default: 587)
"""
import os
import json
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from typing import Optional, Any, List
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from backend.config import (
    SMTP_EMAIL, SMTP_PASSWORD, SMTP_TO,
    SMTP_HOST, SMTP_PORT, SENDGRID_API_KEY, BREVO_API_KEY,
    POSITION_SIZE_USDT, MAX_DAILY_LOSS_USDT,
    BTC_TRIGGER_PCT, TP_PCT, SL_PCT,
)
from backend.database.db import log_event


class EmailNotifier:
    """
    Sends email alerts for bot events.
    Supports Brevo HTTP API (preferred for Render), SendGrid HTTP API, and SMTP.
    Gracefully handles missing config — silently skips if not configured.
    """

    def __init__(self):
        # Check env vars at runtime so tests and runtime config changes take effect
        self._brevo_key = os.environ.get("BREVO_API_KEY", "")
        self._sg_key = os.environ.get("SENDGRID_API_KEY", "")
        self._smtp_email = os.environ.get("SMTP_EMAIL", "")
        self._smtp_password = os.environ.get("SMTP_PASSWORD", "")
        self._smtp_to = os.environ.get("SMTP_TO", "")
        
        # Configured if we have sender + recipient + any delivery method
        self._configured = bool(self._smtp_email and self._smtp_to) and bool(
            self._brevo_key or self._sg_key or self._smtp_password
        )

    @property
    def is_configured(self) -> bool:
        """Check if any email delivery method is configured."""
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

    # ─── Email Delivery ────────────────────────────────────────

    def _send(self, subject: str, html_body: str) -> bool:
        """
        Send an HTML email. Tries delivery methods in order:
        1. Brevo HTTP API (if BREVO_API_KEY is set — works on Render via HTTPS/443)
        2. SendGrid HTTP API (if SENDGRID_API_KEY is set — also HTTPS/443)
        3. SMTP (if SMTP_PASSWORD is set — may be blocked on Render free tier)
        
        Returns True if sent, False on failure (logged as WARNING).
        
        Email failures are intentionally logged as WARNING (not ERROR)
        because they never affect trading — the bot continues running
        normally even if email is down or misconfigured.
        """
        # 1. Brevo API (recommended — free tier: 300/day, works over HTTPS)
        if self._brevo_key:
            if self._send_via_brevo(subject, html_body):
                return True
            # If Brevo fails, try next method
        
        # 2. SendGrid API (fallback HTTPS option)
        if self._sg_key:
            if self._send_via_sendgrid(subject, html_body):
                return True
        
        # 3. SMTP (last resort — blocked on Render free tier)
        return self._send_via_smtp(subject, html_body)

    def _send_via_brevo(self, subject: str, html_body: str) -> bool:
        """
        Send email via Brevo (formerly Sendinblue) v3 SMTP API (HTTPS/443).
        Free tier: 300 emails/day. Uses api-key header auth.
        This works on Render because it uses standard HTTPS, not SMTP.
        """
        try:
            plain_text = self._strip_html(html_body)
            payload = json.dumps({
                "sender": {"email": self._smtp_email},
                "to": [{"email": self._smtp_to}],
                "subject": subject,
                "htmlContent": html_body,
                "textContent": plain_text,
            }            ).encode('utf-8')

            req = Request(
                "https://api.brevo.com/v3/smtp/email",
                data=payload,
                headers={
                    "api-key": self._brevo_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            with urlopen(req, timeout=15) as resp:
                if resp.status == 201:
                    log_event('INFO', 'email', f"Sent via Brevo: {subject}")
                    return True
                else:
                    log_event('WARNING', 'email',
                              f"Brevo returned status {resp.status} for '{subject[:40]}'")
                    return False
        except HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')[:200] if e.fp else ''
            if e.code == 401:
                log_event('WARNING', 'email',
                          f"Brevo 401 Unauthorized: API key is invalid. "
                          f"Regenerate your BREVO_API_KEY at brevo.com "
                          f"and add it to Render environment variables.")
            else:
                log_event('WARNING', 'email',
                          f"Brevo HTTP {e.code} for '{subject[:40]}': {body}")
        except URLError as e:
            log_event('WARNING', 'email',
                      f"Brevo network error sending '{subject[:40]}': {e}")
        except (TypeError, ValueError) as e:
            log_event('WARNING', 'email',
                      f"Brevo encoding error: {e}")
        except Exception as e:
            log_event('WARNING', 'email',
                      f"Brevo failed to send '{subject[:40]}': {e}")
        return False

    def _send_via_sendgrid(self, subject: str, html_body: str) -> bool:
        """
        Send email via SendGrid v3 Mail Send API (HTTPS/443).
        This works on Render because it uses standard HTTPS, not SMTP.
        """
        try:
            plain_text = self._strip_html(html_body)
            payload = json.dumps({
                "personalizations": [{"to": [{"email": self._smtp_to}]}],
                "from": {"email": self._smtp_email},
                "subject": subject,
                "content": [
                    {"type": "text/plain", "value": plain_text},
                    {"type": "text/html", "value": html_body},
                ],
            }).encode('utf-8')

            req = Request(
                "https://api.sendgrid.com/v3/mail/send",
                data=payload,
                headers={
                    "Authorization": f"Bearer {self._sg_key}",
                    "Content-Type": "application/json",
                },
            )
            with urlopen(req, timeout=15) as resp:
                if resp.status == 202:
                    log_event('INFO', 'email', f"Sent via SendGrid: {subject}")
                    return True
                else:
                    log_event('WARNING', 'email',
                              f"SendGrid returned status {resp.status} for '{subject[:40]}'")
                    return False
        except URLError as e:
            log_event('WARNING', 'email',
                      f"SendGrid network error sending '{subject[:40]}': {e}")
        except (TypeError, ValueError) as e:
            log_event('WARNING', 'email',
                      f"SendGrid encoding error: {e}")
        except Exception as e:
            log_event('WARNING', 'email',
                      f"SendGrid failed to send '{subject[:40]}': {e}")
        return False

    def _send_via_smtp(self, subject: str, html_body: str) -> bool:
        """
        Send email via SMTP as fallback.
        May fail on Render free tier which blocks outbound SMTP ports.
        """
        if not self._smtp_password:
            return False
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = self._smtp_email
            msg['To'] = self._smtp_to
            msg['Subject'] = subject

            plain_text = self._strip_html(html_body)
            msg.attach(MIMEText(plain_text, 'plain', 'utf-8'))
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

            context = ssl.create_default_context()
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.starttls(context=context)
                server.login(self._smtp_email, self._smtp_password)
                server.sendmail(self._smtp_email, self._smtp_to, msg.as_string())

            log_event('INFO', 'email', f"Sent via SMTP: {subject}")
            return True

        except smtplib.SMTPAuthenticationError:
            log_event('WARNING', 'email',
                      "SMTP auth failed — check SMTP_EMAIL/SMTP_PASSWORD in .env")
        except smtplib.SMTPException as e:
            log_event('WARNING', 'email',
                      f"SMTP error sending '{subject[:40]}': {e}")
        except OSError as e:
            # [Errno 101] Network is unreachable — Render blocks SMTP
            log_event('WARNING', 'email',
                      f"SMTP network error (port {SMTP_PORT} blocked?): {e}. "
                      f"Set BREVO_API_KEY or SENDGRID_API_KEY in .env to use HTTPS-based email.")
        except Exception as e:
            log_event('WARNING', 'email',
                      f"SMTP failed to send '{subject[:40]}': {e}")

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
