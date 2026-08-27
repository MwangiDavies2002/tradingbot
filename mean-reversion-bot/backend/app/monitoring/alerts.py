"""
alerts.py
────────────────────────────────────────────────────────────────────────────────
Alert System — Telegram + Logging
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Sends real-time alerts to Telegram and/or logs when important bot events
    occur. Every critical event the bot experiences should flow through here.

    ALERT TYPES:
        TRADE_OPEN          New position opened
        TRADE_CLOSE         Position closed (with P&L)
        CIRCUIT_BREAKER     CB triggered (pause/halt)
        DAILY_REPORT        End-of-day performance summary
        API_ERROR           Deriv API connection issues
        SIGNAL_APLUS        A+ setup detected (for manual review mode)
        BOT_START / STOP    Bot lifecycle events
        DRAWDOWN_WARNING    Approaching daily/weekly limits

    TELEGRAM SETUP:
        1. Create a bot via @BotFather on Telegram → get BOT_TOKEN
        2. Send a message to your bot, then call:
           https://api.telegram.org/bot<TOKEN>/getUpdates
           to find your CHAT_ID
        3. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env

USAGE:
    alerter = AlertManager(bot_token="...", chat_id="...")
    await alerter.trade_opened(position)
    await alerter.circuit_breaker_triggered("consecutive_losses", details)
    await alerter.daily_report(stats)
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    INFO     = "ℹ️"
    SUCCESS  = "✅"
    WARNING  = "⚠️"
    CRITICAL = "🚨"
    TRADE    = "📈"


@dataclass
class AlertMessage:
    level:   AlertLevel
    title:   str
    body:    str
    ts:      datetime = None

    def __post_init__(self):
        if self.ts is None:
            self.ts = datetime.utcnow()

    def format_telegram(self) -> str:
        """Format as a clean Telegram message (no markdown to avoid parse errors)."""
        ts_str = self.ts.strftime("%H:%M:%S UTC")
        lines  = [
            f"{self.level.value} {self.title}",
            f"──────────────────",
            self.body,
            f"",
            f"🕐 {ts_str}",
        ]
        return "\n".join(lines)


class AlertManager:
    """
    Sends alerts to Telegram and always logs to the standard logger.

    Parameters
    ----------
    bot_token : str   Telegram bot token from @BotFather
    chat_id   : str   Telegram chat/channel ID to send to
    enabled   : bool  Set False to disable Telegram (log-only mode)
    """

    def __init__(
        self,
        bot_token:  Optional[str] = None,
        chat_id:    Optional[str] = None,
        enabled:    bool = True,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id   = chat_id
        self.enabled   = enabled and bool(bot_token and chat_id)

        if self.enabled:
            logger.info("AlertManager: Telegram alerts enabled (chat_id=%s)", chat_id)
        else:
            logger.info("AlertManager: Log-only mode (no Telegram token configured)")

    # ── Typed Alert Methods ───────────────────────────────────────────────────

    async def trade_opened(self, position) -> None:
        """Alert when a new position is opened."""
        emoji = "🟢" if position.direction == "buy" else "🔴"
        body  = (
            f"{emoji} {position.direction.upper()}  {position.symbol}\n"
            f"Entry:  {position.entry_price:.5f}\n"
            f"SL:     {position.stop_loss:.5f}\n"
            f"TP:     {position.take_profit:.5f}\n"
            f"Stake:  ${position.stake:.2f}\n"
            f"Score:  {position.confluence_score} pts\n"
            f"Code:   {position.reason_code}"
        )
        await self.send(AlertMessage(
            level=AlertLevel.TRADE,
            title="POSITION OPENED",
            body=body,
        ))

    async def trade_closed(self, position) -> None:
        """Alert when a position closes with P&L."""
        pnl    = position.pnl or 0.0
        emoji  = "💚" if pnl >= 0 else "❤️"
        reason = position.close_reason.value if position.close_reason else "unknown"
        dur    = int(position.duration_seconds or 0)
        body   = (
            f"{emoji} {position.direction.upper()}  {position.symbol}\n"
            f"Entry:    {position.entry_price:.5f}\n"
            f"Exit:     {position.exit_price:.5f}\n"
            f"P&L:      ${pnl:+.2f}\n"
            f"Reason:   {reason.replace('_', ' ').upper()}\n"
            f"Duration: {dur // 60}m {dur % 60}s"
        )
        level = AlertLevel.SUCCESS if pnl >= 0 else AlertLevel.WARNING
        await self.send(AlertMessage(level=level, title="POSITION CLOSED", body=body))

    async def circuit_breaker_triggered(self, trigger: str, details: str) -> None:
        """Alert when the circuit breaker pauses or halts the bot."""
        body = (
            f"Trigger: {trigger.replace('_', ' ').upper()}\n"
            f"Details: {details}\n"
            f"Action:  Bot trading SUSPENDED"
        )
        await self.send(AlertMessage(
            level=AlertLevel.CRITICAL,
            title="CIRCUIT BREAKER TRIGGERED",
            body=body,
        ))
        logger.critical("CIRCUIT BREAKER: %s — %s", trigger, details)

    async def circuit_breaker_resumed(self) -> None:
        """Alert when the circuit breaker auto-resumes."""
        await self.send(AlertMessage(
            level=AlertLevel.SUCCESS,
            title="BOT RESUMED",
            body="Circuit breaker cooldown expired. Trading resumed.",
        ))

    async def daily_report(
        self,
        balance:       float,
        daily_pnl:     float,
        trade_count:   int,
        win_rate:      float,
        drawdown_pct:  float,
    ) -> None:
        """End-of-day performance summary."""
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"
        body = (
            f"Balance:    ${balance:.2f}\n"
            f"Day P&L:    ${daily_pnl:+.2f}  {pnl_emoji}\n"
            f"Trades:     {trade_count}\n"
            f"Win Rate:   {win_rate:.1%}\n"
            f"Drawdown:   {drawdown_pct:.1%}"
        )
        await self.send(AlertMessage(
            level=AlertLevel.INFO,
            title="DAILY PERFORMANCE REPORT",
            body=body,
        ))

    async def drawdown_warning(self, pct: float, limit_pct: float, scope: str) -> None:
        """Alert when drawdown approaches the configured limit."""
        body = (
            f"Scope:    {scope.upper()} drawdown\n"
            f"Current:  {pct:.1%}\n"
            f"Limit:    {limit_pct:.1%}\n"
            f"Margin:   {(limit_pct - pct):.1%} remaining"
        )
        await self.send(AlertMessage(
            level=AlertLevel.WARNING,
            title="DRAWDOWN WARNING",
            body=body,
        ))

    async def api_error(self, error: str, reconnect_attempt: int) -> None:
        """Alert on Deriv API connection issues."""
        body = (
            f"Error:   {error}\n"
            f"Attempt: #{reconnect_attempt} reconnect"
        )
        await self.send(AlertMessage(
            level=AlertLevel.WARNING,
            title="API CONNECTION ERROR",
            body=body,
        ))

    async def signal_aplus(self, symbol: str, direction: str, score: int, reason: str) -> None:
        """Alert for A+ high-conviction setups (score ≥ 9)."""
        emoji = "🟢" if direction == "buy" else "🔴"
        body  = (
            f"{emoji} {direction.upper()}  {symbol}\n"
            f"Score:  {score} pts  (A+ Setup)\n"
            f"Code:   {reason}"
        )
        await self.send(AlertMessage(
            level=AlertLevel.TRADE,
            title="A+ SETUP DETECTED",
            body=body,
        ))

    async def bot_started(self, balance: float, symbols: list[str]) -> None:
        """Alert when the bot starts up."""
        body = (
            f"Balance:  ${balance:.2f}\n"
            f"Symbols:  {', '.join(symbols)}\n"
            f"Mode:     LIVE TRADING"
        )
        await self.send(AlertMessage(
            level=AlertLevel.SUCCESS,
            title="BOT STARTED",
            body=body,
        ))

    async def bot_stopped(self, reason: str) -> None:
        """Alert when the bot shuts down."""
        await self.send(AlertMessage(
            level=AlertLevel.WARNING,
            title="BOT STOPPED",
            body=f"Reason: {reason}",
        ))

    # ── Core Send ─────────────────────────────────────────────────────────────

    async def send(self, alert: AlertMessage) -> None:
        """
        Send an alert. Always logs. Sends Telegram if configured.
        Never raises — alert failures must not crash the bot.
        """
        # Always log
        log_msg = f"[{alert.level.value}] {alert.title} | {alert.body.replace(chr(10), ' | ')}"
        logger.info(log_msg)

        # Send Telegram if enabled
        if self.enabled:
            asyncio.create_task(self._send_telegram(alert))

    async def _send_telegram(self, alert: AlertMessage) -> None:
        """Fire-and-forget Telegram message. Retries once on failure."""
        try:
            import httpx
        except ImportError:
            logger.debug("httpx not installed — Telegram alerts disabled")
            return

        url  = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        text = alert.format_telegram()

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(url, json={
                        "chat_id":    self.chat_id,
                        "text":       text,
                        "parse_mode": "",    # Plain text — safest
                    })
                    resp.raise_for_status()
                    return
            except Exception as exc:
                if attempt == 0:
                    await asyncio.sleep(2)
                else:
                    logger.warning("Telegram alert failed after retry: %s", exc)
