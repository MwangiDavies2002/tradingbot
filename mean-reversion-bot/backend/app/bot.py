"""
bot.py
────────────────────────────────────────────────────────────────────────────────
Bot Runner — Top-Level Async Trading Loop
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    The single entry point that wires every component together and runs
    the live trading bot. This is what you start on the server.

    RUN:
        python -m app.bot
        # or via Makefile:
        make run-bot

    BOOT SEQUENCE:
        1.  Load & validate settings from .env
        2.  Configure logging
        3.  Connect to MySQL — verify tables exist
        4.  Connect to Redis — for signal/candle caching
        5.  Authenticate with Deriv API
        6.  Initialise SignalEngine, CircuitBreaker, PositionSizer
        7.  Initialise OrderManager and AlertManager
        8.  Bootstrap candle buffers for all active symbols (load history)
        9.  Subscribe to live candle streams
        10. Subscribe to live balance stream
        11. Enter the main asyncio event loop (runs indefinitely)
        12. On SIGINT/SIGTERM: graceful shutdown

    GRACEFUL SHUTDOWN:
        - Closes all open positions
        - Unsubscribes from all Deriv streams
        - Logs final P&L to DB
        - Sends shutdown alert to Telegram
        - Closes DB and Redis connections

    DEMO vs LIVE:
        Set DERIV_DEMO=True in .env to trade on a demo account.
        All logic is identical — only the Deriv account differs.
        ALWAYS validate with demo + paper trading before DERIV_DEMO=False.

────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from datetime import datetime

logger = logging.getLogger(__name__)


class BotRunner:
    """
    Orchestrates the entire bot lifecycle.
    Instantiated once, then run() is called to start the event loop.
    """

    def __init__(self) -> None:
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Components — initialised in _setup()
        self.client         = None
        self.signal_engine  = None
        self.order_manager  = None
        self.tick_consumer  = None
        self.alert_manager  = None
        self.circuit_breaker = None
        self.redis          = None
        self.store = None

    # ── Public Entry Point ────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Main entry point. Call this from __main__.
        Runs until shutdown signal received.
        Phase 6: Includes Automated Recovery Mode.
        """
        retry_count = 0
        max_retries = 5
        retry_delay = 10 # seconds

        while retry_count < max_retries and not self._shutdown_event.is_set():
            try:
                await self._setup()
                await self._main_loop()
                break # Normal exit
            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt — shutting down gracefully")
                break
            except Exception as exc:
                retry_count += 1
                logger.critical("Fatal error in bot runner (Attempt %d/%d): %s", 
                                retry_count, max_retries, exc, exc_info=True)
                
                if self.alert_manager:
                    await self.alert_manager.bot_stopped(f"RECOVERY MODE: Attempting restart {retry_count}/{max_retries} after error: {exc}")
                
                # Cleanup before retry
                await self._shutdown()
                
                if retry_count < max_retries:
                    logger.info("Recovery Mode: Waiting %d seconds before restart...", retry_delay)
                    try:
                        await asyncio.wait_for(self._shutdown_event.wait(), timeout=retry_delay)
                        break
                    except asyncio.TimeoutError:
                        pass
                    # Reset components for clean setup
                    self.client = None
                    self.signal_engine = None
                    self.order_manager = None
                    self.tick_consumer = None
                    self.alert_manager = None
                    self.circuit_breaker = None
                    self.redis = None
                    self.store = None
                else:
                    logger.error("Recovery Mode: Max retries reached. Manual intervention required.")
                    break # Exit the loop after max retries
        
        # Final shutdown after loop exit
        await self._shutdown()

    # ── Setup ─────────────────────────────────────────────────────────────────

    async def _setup(self) -> None:
        """Initialise every component in the correct dependency order."""
        from app.config import settings
        from app.core.engine.signal_engine import EngineConfig, SignalEngine
        from app.core.risk.circuit_breaker import CircuitBreaker
        from app.core.risk.position_sizer import PositionSizer
        from app.data.tick_consumer import TickConsumer
        from app.database.session import check_connection, create_tables, AsyncSessionLocal, engine
        from app.execution.safety import ExecutionStore, account_scope, validate_account
        from app.execution.deriv_client import DerivClient, DerivConfig
        from app.execution.order_manager import OrderManager
        from app.monitoring.alerts import AlertManager

        _configure_logging(settings.LOG_LEVEL)
        logger.info("=" * 60)
        logger.info("BOT STARTING | %s | demo=%s", settings.APP_NAME, settings.DERIV_DEMO)
        logger.info("=" * 60)

        # ── 1. Database ───────────────────────────────────────────────────────
        logger.info("Connecting to database...")
        if not await check_connection():
            raise RuntimeError("Database connection failed — check DATABASE_URL")
        await create_tables()
        self.store = ExecutionStore(AsyncSessionLocal, account_scope(settings))
        await self.store.acquire(engine)
        logger.info("Database connected")

        # ── 2. Redis ──────────────────────────────────────────────────────────
        try:
            import redis.asyncio as aioredis
            self.redis = aioredis.from_url(
                settings.REDIS_URL, encoding="utf-8", decode_responses=True
            )
            await self.redis.ping()
            logger.info("Redis connected")
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — running without cache", exc)
            self.redis = None

        # ── 3. Alert Manager ──────────────────────────────────────────────────
        self.alert_manager = AlertManager(
            bot_token = settings.TELEGRAM_BOT_TOKEN,
            chat_id   = settings.TELEGRAM_CHAT_ID,
        )

        # ── 4. Deriv Client ───────────────────────────────────────────────────
        logger.info("Connecting to Deriv API (demo=%s)...", settings.DERIV_DEMO)
        self.client = DerivClient(
            config=DerivConfig(
                app_id    = settings.DERIV_APP_ID,
                api_token = settings.DERIV_API_TOKEN,
            )
        )
        await self.client.connect()
        validate_account(settings, self.client.state)
        logger.info("Deriv connected | account=%s | balance=$%.2f",
                    self.client.state.account_id, self.client.state.balance)

        # ── 5. Risk Components ────────────────────────────────────────────────
        self.circuit_breaker = CircuitBreaker(
            max_consecutive_losses = settings.CB_MAX_CONSECUTIVE_LOSSES,
            daily_drawdown_pct     = settings.CB_DAILY_DRAWDOWN_PCT,
            weekly_drawdown_pct    = settings.CB_WEEKLY_DRAWDOWN_PCT,
            single_trade_loss_pct  = settings.CB_SINGLE_TRADE_LOSS_PCT,
            pause_hours_losses     = settings.CB_PAUSE_HOURS_LOSSES,
            max_open_positions     = settings.MAX_OPEN_POSITIONS,
        )
        sizer = PositionSizer(
            account_balance = self.client.state.balance,
            risk_pct        = settings.RISK_PCT,
            max_risk_pct    = settings.MAX_RISK_PCT,
            sl_atr_mult     = settings.SL_ATR_MULTIPLIER,
            tp_rr           = settings.TP_RR_RATIO,
        )
        self.circuit_breaker.initialise(self.client.state.balance)

        # ── 6. Signal Engine ──────────────────────────────────────────────────
        engine_cfg = EngineConfig(
            risk_pct         = settings.RISK_PCT,
            max_risk_pct     = settings.MAX_RISK_PCT,
            sl_atr_mult      = settings.SL_ATR_MULTIPLIER,
            tp_rr            = settings.TP_RR_RATIO,
            min_confluence   = settings.MIN_CONFLUENCE_SCORE,
            deriv_multiplier = settings.DERIV_MULTIPLIER,
            deriv_product    = settings.DERIV_PRODUCT,
            zscore_period    = settings.ZSCORE_PERIOD,
            rsi_period       = settings.RSI_PERIOD,
            atr_period       = settings.ATR_PERIOD,
            swing_lookback   = settings.SWING_LOOKBACK,
        )
        self.signal_engine = SignalEngine(config=engine_cfg, cb=self.circuit_breaker)
        self.signal_engine.initialise(self.client.state.balance)

        # ── 7. Order Manager ──────────────────────────────────────────────────
        self.order_manager = OrderManager(
            client          = self.client,
            circuit_breaker = self.circuit_breaker,
            sizer           = sizer,
            multiplier      = settings.DERIV_MULTIPLIER,
            max_positions   = settings.MAX_OPEN_POSITIONS,
            store           = self.store,
            settings        = settings,
        )
        await self.order_manager.recover(initial=True)
        await self.store.heartbeat(self.circuit_breaker, self.order_manager.recovery_error)

        # ── 8. Tick Consumer ──────────────────────────────────────────────────
        self.tick_consumer = TickConsumer(
            client        = self.client,
            signal_engine = self.signal_engine,
            order_manager = self.order_manager,
            redis_client  = self.redis,
            buffer_size   = settings.CANDLE_BUFFER_SIZE,
            min_candles   = settings.MIN_CANDLES_SIGNAL,
        )

        # ── 9. Bootstrap + Subscribe all active symbols ───────────────────────
        for symbol in settings.ACTIVE_SYMBOLS:
            logger.info("Bootstrapping %s...", symbol)
            await self.tick_consumer.bootstrap(
                symbol    = symbol,
                timeframe = settings.PRIMARY_TIMEFRAME,
                count     = settings.CANDLE_BUFFER_SIZE,
            )
            await self.tick_consumer.subscribe(
                symbol    = symbol,
                timeframe = settings.PRIMARY_TIMEFRAME,
            )

        # ── 10. Balance subscription ──────────────────────────────────────────
        async def on_balance(msg: dict) -> None:
            bal = msg.get("balance", {})
            new_balance = float(bal.get("balance", self.client.state.balance))
            self.client.state.balance = new_balance
            self.signal_engine.sizer.update_balance(new_balance)
            logger.debug("Balance update: $%.2f", new_balance)

        await self.client.subscribe_balance(on_balance)
        self._balance_handler = on_balance
        self._subscribed_connection = self.client.state.connect_time

        # ── Alert: bot started ────────────────────────────────────────────────
        await self.alert_manager.bot_started(
            balance = self.client.state.balance,
            symbols = settings.ACTIVE_SYMBOLS,
            demo = settings.DERIV_DEMO,
        )

        self._running = True
        logger.info("=" * 60)
        logger.info("BOT LIVE | Monitoring %d symbol(s)", len(settings.ACTIVE_SYMBOLS))
        logger.info("=" * 60)

    # ── Main Loop ─────────────────────────────────────────────────────────────

    async def _main_loop(self) -> None:
        """
        Keep the bot alive. The actual trading logic runs in the tick_consumer
        callbacks. This loop handles periodic tasks and shutdown detection.
        """
        last_heartbeat = datetime.utcnow()

        while self._running:
            await asyncio.sleep(2)
            try:
                if (self.client.state.authenticated and
                        (self.client.state.connect_time != self._subscribed_connection or self.order_manager.data_errors)):
                    self.order_manager.ready = False
                    from app.config import settings
                    if self.client.state.connect_time == self._subscribed_connection:
                        await self.tick_consumer.unsubscribe_all()
                    for symbol in settings.ACTIVE_SYMBOLS:
                        await self.tick_consumer.bootstrap(symbol, settings.PRIMARY_TIMEFRAME,
                                                           settings.CANDLE_BUFFER_SIZE)
                        await self.tick_consumer.subscribe(symbol, settings.PRIMARY_TIMEFRAME)
                    await self.client.subscribe_balance(self._balance_handler)
                    self._subscribed_connection = self.client.state.connect_time
                await self.order_manager.recover()
                # Use the same mutex as execution so persisted breaker updates
                # cannot overwrite concurrent fill accounting.
                async with self.order_manager._lock:
                    enabled = await self.store.heartbeat(self.circuit_breaker,
                                                         self.order_manager.recovery_error)
                if not enabled:
                    await self.order_manager.close_all()
            except Exception as exc:
                self.order_manager.ready = False
                logger.error("Safety control unavailable; entries blocked: %s", exc)

            # Reconnect check
            if not self.client.state.connected:
                logger.warning("Deriv connection lost — waiting for reconnect...")

            # Heartbeat log every 10 minutes
            now = datetime.utcnow()
            if (now - last_heartbeat).seconds >= 600:
                logger.info(
                    "HEARTBEAT | open_positions=%d | cb_state=%s | balance=$%.2f",
                    len(self.order_manager.open_positions) if self.order_manager else 0,
                    self.circuit_breaker._state.value if self.circuit_breaker else "?",
                    self.client.state.balance if self.client else 0,
                )
                last_heartbeat = now

            if self._shutdown_event.is_set():
                self._running = False

    # ── Shutdown ──────────────────────────────────────────────────────────────

    async def _shutdown(self) -> None:
        """Graceful shutdown: close positions, unsubscribe, disconnect."""
        logger.info("Graceful shutdown initiated...")
        self._running = False
        if self.order_manager:
            self.order_manager.ready = False

        try:
            if self.order_manager:
                from app.execution.order_manager import CloseReason
                await self.order_manager.close_all(reason=CloseReason.MANUAL)
                logger.info("Shutdown close attempts finished; unresolved positions remain journaled")
        except Exception as exc:
            logger.error("Error closing positions during shutdown: %s", exc)

        try:
            if self.tick_consumer:
                await self.tick_consumer.unsubscribe_all()
        except Exception as exc:
            logger.error("Error unsubscribing during shutdown: %s", exc)

        try:
            if self.client:
                await self.client.disconnect()
        except Exception as exc:
            logger.error("Error disconnecting Deriv client: %s", exc)

        try:
            if self.redis:
                await self.redis.aclose()
        except Exception:
            pass

        try:
            if self.alert_manager:
                await self.alert_manager.bot_stopped("Graceful shutdown")
        except Exception:
            pass

        logger.info("Shutdown complete. Goodbye.")
        if self.store:
            await self.store.release()

    def request_shutdown(self) -> None:
        """Called by signal handlers (SIGINT, SIGTERM)."""
        logger.info("Shutdown requested via signal")
        self._shutdown_event.set()
        if self.order_manager:
            self.order_manager.ready = False
        self._running = False


# ── Logging ───────────────────────────────────────────────────────────────────

def _configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level   = getattr(logging, level.upper(), logging.INFO),
        format  = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt = "%Y-%m-%d %H:%M:%S",
        stream  = sys.stdout,
    )
    from app.config import settings
    if settings.is_production:
        from pythonjsonlogger.jsonlogger import JsonFormatter
        for handler in logging.getLogger().handlers:
            handler.setFormatter(JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    # Quiet noisy third-party loggers
    for noisy in ("websockets", "asyncio", "sqlalchemy", "httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ── Entry Point ───────────────────────────────────────────────────────────────

async def main() -> None:
    bot = BotRunner()

    # Register OS signal handlers for graceful shutdown
    # loop.add_signal_handler is not available on Windows
    if sys.platform != 'win32':
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, bot.request_shutdown)
    
    try:
        await bot.run()
    except (KeyboardInterrupt, SystemExit):
        bot.request_shutdown()
        # Wait for shutdown to complete if necessary
        # Note: bot.run() calls _shutdown() at the end


if __name__ == "__main__":
    asyncio.run(main())
