"""
deriv_client.py
────────────────────────────────────────────────────────────────────────────────
Deriv WebSocket Client
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Manages the persistent WebSocket connection to the Deriv API v3.
    Handles authentication, subscription management, automatic reconnection,
    request/response correlation, and error recovery.

    ALL Deriv API communication goes through this single client.
    The rest of the bot calls methods on this class — never raw WebSockets.

    ARCHITECTURE:
        - One persistent WS connection per instance
        - Request/response matched by req_id (auto-incremented)
        - Subscriptions tracked separately — each gets a subscription_id
        - Heartbeat ping every 30s to keep connection alive
        - Exponential backoff reconnection (1s → 2s → 4s → 8s → 30s max)
        - All messages dispatched to registered callback handlers

    DERIV WS ENDPOINT:
        wss://ws.derivws.com/websockets/v3?app_id={APP_ID}
        App ID obtained from: https://api.deriv.com/

    AUTHENTICATION:
        After connect → send authorize request with API token
        Token is READ-ONLY for data, TRADING for order placement
        Store both in env vars, never in code

USAGE:
    client = DerivClient(app_id="YOUR_APP_ID", api_token="YOUR_TOKEN")
    await client.connect()

    # Subscribe to ticks
    await client.subscribe_ticks("R_75", callback=on_tick)

    # Place a trade
    contract = await client.buy_contract(
        contract_type="MULTUP", symbol="R_75",
        amount=10.0, multiplier=100, basis="stake"
    )
    print(contract["contract_id"])
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

# Type aliases
MessageHandler  = Callable[[dict], Coroutine]
SubscriptionId  = str


@dataclass
class DerivConfig:
    """Configuration for the Deriv WebSocket client."""
    app_id:          str
    api_token:       str
    endpoint:        str   = "wss://ws.derivws.com/websockets/v3"
    ping_interval:   float = 30.0      # Seconds between heartbeat pings
    reconnect_delay: float = 1.0       # Initial reconnect delay (doubles each attempt)
    max_reconnect:   float = 30.0      # Max reconnect delay cap
    request_timeout: float = 10.0      # Seconds before a request times out
    max_retries:     int   = 5         # Max retries per request


@dataclass
class DerivConnectionState:
    connected:     bool     = False
    authenticated: bool     = False
    reconnects:    int      = 0
    last_ping:     Optional[float] = None
    last_pong:     Optional[float] = None
    connect_time:  Optional[datetime] = None
    account_id:    Optional[str] = None
    balance:       float    = 0.0
    currency:      str      = "USD"


class DerivClient:
    """
    Async Deriv WebSocket API client.

    Requires: pip install websockets

    Parameters
    ----------
    config : DerivConfig
        Connection and authentication configuration.
        Alternatively pass app_id and api_token directly.
    """

    def __init__(
        self,
        app_id:    str = "",
        api_token: str = "",
        config:    Optional[DerivConfig] = None,
    ) -> None:
        if config is None:
            config = DerivConfig(app_id=app_id, api_token=api_token)
        self.cfg   = config
        self.state = DerivConnectionState()

        self._ws:               Any = None                              # websockets connection
        self._req_id:           int = 1
        self._pending:          dict[int, asyncio.Future] = {}          # req_id → Future
        self._subscriptions:    dict[str, MessageHandler] = {}          # sub_id → handler
        self._topic_handlers:   dict[str, list[MessageHandler]] = {}    # msg_type → [handlers]
        self._reconnect_delay:  float = config.reconnect_delay
        self._running:          bool  = False
        self._recv_task:        Optional[asyncio.Task] = None
        self._ping_task:        Optional[asyncio.Task] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """
        Establish WebSocket connection and authenticate.
        Starts background tasks for message receiving and heartbeat.
        """
        try:
            import websockets
        except ImportError:
            raise RuntimeError("websockets not installed. Run: pip install websockets")

        url = f"{self.cfg.endpoint}?app_id={self.cfg.app_id}"
        logger.info("Connecting to Deriv: %s", url)

        self._ws = await websockets.connect(
            url,
            ping_interval=None,     # We handle pings manually
            close_timeout=5,
            max_size=2**20,         # 1MB max message
        )

        self.state.connected    = True
        self.state.connect_time = datetime.utcnow()
        self._reconnect_delay   = self.cfg.reconnect_delay
        self._running           = True

        # Start background tasks
        self._recv_task = asyncio.create_task(self._receive_loop(), name="deriv_recv")
        self._ping_task = asyncio.create_task(self._ping_loop(),    name="deriv_ping")

        logger.info("WebSocket connected. Authenticating...")
        await self._authenticate()

    async def disconnect(self) -> None:
        """Gracefully disconnect and clean up."""
        self._running = False
        if self._recv_task:
            self._recv_task.cancel()
        if self._ping_task:
            self._ping_task.cancel()
        if self._ws:
            await self._ws.close()
        self.state.connected    = False
        self.state.authenticated = False
        logger.info("Deriv client disconnected cleanly")

    async def reconnect(self) -> None:
        """
        Reconnect with exponential backoff.
        Called automatically when the connection drops.
        """
        self.state.connected     = False
        self.state.authenticated = False
        self._pending.clear()

        while self._running:
            delay = min(self._reconnect_delay, self.cfg.max_reconnect)
            logger.warning("Reconnecting in %.0fs (attempt #%d)...",
                           delay, self.state.reconnects + 1)
            await asyncio.sleep(delay)
            self._reconnect_delay *= 2   # Exponential backoff

            try:
                await self.connect()
                self.state.reconnects += 1
                logger.info("Reconnected successfully after %d attempt(s)",
                            self.state.reconnects)
                # Re-subscribe to all active subscriptions
                await self._restore_subscriptions()
                return
            except Exception as exc:
                logger.error("Reconnect failed: %s", exc)

    # ── Deriv API Methods ─────────────────────────────────────────────────────

    async def get_candles(
        self,
        symbol:    str,
        timeframe: int,           # Granularity in seconds: 60=M1, 300=M5, etc.
        count:     int = 500,
        end:       Optional[int] = None,   # UNIX timestamp, defaults to now
    ) -> list[dict]:
        """
        Fetch historical OHLCV candles.

        Parameters
        ----------
        symbol    : str  Deriv symbol e.g. "R_75", "BOOM500", "frxEURUSD"
        timeframe : int  Granularity in seconds (60, 300, 900, 3600, 86400)
        count     : int  Number of candles to fetch. Max 5000.
        end       : int  End time as UNIX timestamp. Defaults to now.

        Returns list of dicts with keys: epoch, open, high, low, close
        """
        req: dict[str, Any] = {
            "ticks_history": symbol,
            "style":         "candles",
            "granularity":   timeframe,
            "count":         count,
            "end":           end or "latest",
            "adjust_start_time": 1,
        }
        response = await self._send_request(req)
        candles  = response.get("candles", [])
        logger.debug("Fetched %d candles for %s", len(candles), symbol)
        return candles

    async def subscribe_ticks(
        self,
        symbol:   str,
        callback: MessageHandler,
    ) -> SubscriptionId:
        """
        Subscribe to live tick stream for a symbol.
        callback(message) is called on every incoming tick.
        Returns subscription_id for later unsubscription.
        """
        req = {"ticks": symbol, "subscribe": 1}
        response = await self._send_request(req)
        sub_id   = response.get("subscription", {}).get("id", "")
        if sub_id:
            self._subscriptions[sub_id] = callback
            logger.info("Subscribed to ticks: %s (sub_id=%s)", symbol, sub_id)
        return sub_id

    async def subscribe_candles(
        self,
        symbol:    str,
        timeframe: int,
        callback:  MessageHandler,
    ) -> SubscriptionId:
        """
        Subscribe to live OHLCV candle stream.
        New candle emitted on each close. callback called on every update.
        """
        req = {
            "ticks_history": symbol,
            "style":         "candles",
            "granularity":   timeframe,
            "count":         1,
            "end":           "latest",
            "subscribe":     1,
        }
        response = await self._send_request(req)
        sub_id   = response.get("subscription", {}).get("id", "")
        if sub_id:
            self._subscriptions[sub_id] = callback
            logger.info("Subscribed to candles: %s %ds (sub_id=%s)",
                        symbol, timeframe, sub_id)
        return sub_id

    async def subscribe_balance(self, callback: MessageHandler) -> SubscriptionId:
        """Subscribe to real-time account balance updates."""
        req    = {"balance": 1, "subscribe": 1, "account": "current"}
        resp   = await self._send_request(req)
        sub_id = resp.get("subscription", {}).get("id", "")
        if sub_id:
            self._subscriptions[sub_id] = callback
        # Update local state immediately
        bal = resp.get("balance", {})
        self.state.balance  = float(bal.get("balance", 0))
        self.state.currency = bal.get("currency", "USD")
        logger.info("Balance subscription: $%.2f %s (sub_id=%s)",
                    self.state.balance, self.state.currency, sub_id)
        return sub_id

    async def get_portfolio(self) -> list[dict]:
        """Return list of all currently open contracts."""
        resp = await self._send_request({"portfolio": 1})
        return resp.get("portfolio", {}).get("contracts", [])

    async def get_proposal(
        self,
        contract_type:  str,
        symbol:         str,
        amount:         float,
        multiplier:     int,
        basis:          str = "stake",
        duration:       Optional[int] = None,
        duration_unit:  Optional[str] = None,
    ) -> dict:
        """
        Get a price proposal before placing an order.
        Use to validate contract parameters and see payout before buying.
        """
        req: dict[str, Any] = {
            "proposal":       1,
            "contract_type":  contract_type,   # MULTUP, MULTDOWN, CALL, PUT
            "symbol":         symbol,
            "amount":         amount,
            "basis":          basis,
            "currency":       "USD",
        }
        if multiplier:
            req["multiplier"] = multiplier
        if duration:
            req["duration"]      = duration
            req["duration_unit"] = duration_unit or "m"

        return await self._send_request(req)

    async def buy_contract(
        self,
        contract_type: str,
        symbol:        str,
        amount:        float,
        multiplier:    int   = 100,
        basis:         str   = "stake",
        price:         float = 0,        # Max price to pay (0 = any)
    ) -> dict:
        """
        Place a buy order on Deriv.

        For mean reversion bot, primary products:
            MULTUP   → Long position (Multiplier Up)
            MULTDOWN → Short position (Multiplier Down)

        Returns the full buy response including contract_id.
        """
        # Get proposal first to validate and get price
        proposal = await self.get_proposal(
            contract_type=contract_type,
            symbol=symbol,
            amount=amount,
            multiplier=multiplier,
            basis=basis,
        )

        proposal_id = proposal.get("proposal", {}).get("id")
        ask_price   = float(proposal.get("proposal", {}).get("ask_price", amount))

        if not proposal_id:
            raise ValueError(f"Could not get proposal for {symbol} {contract_type}")

        req = {
            "buy":   proposal_id,
            "price": price or ask_price,
        }

        response = await self._send_request(req)
        contract = response.get("buy", {})

        logger.info(
            "ORDER PLACED | %s %s | type=%s | stake=$%.2f | contract_id=%s",
            symbol, contract_type, basis,
            amount, contract.get("contract_id", "?"),
        )
        return contract

    async def sell_contract(
        self,
        contract_id: int,
        price:       float = 0,   # Min price to accept (0 = any)
    ) -> dict:
        """
        Close an open contract (sell/close position).
        price=0 means sell at market (any price).
        """
        req = {"sell": contract_id, "price": price}
        response = await self._send_request(req)
        sold = response.get("sell", {})
        logger.info("CONTRACT CLOSED | contract_id=%s | sold_for=$%s",
                    contract_id, sold.get("sold_for", "?"))
        return sold

    async def forget_subscription(self, subscription_id: str) -> bool:
        """Unsubscribe from a specific subscription."""
        req  = {"forget": subscription_id}
        resp = await self._send_request(req)
        self._subscriptions.pop(subscription_id, None)
        success = resp.get("forget") == 1
        logger.debug("Forget sub %s: %s", subscription_id, "OK" if success else "FAIL")
        return success

    async def forget_all(self, subscription_type: str = "ticks") -> None:
        """Unsubscribe from all subscriptions of a given type."""
        req = {"forget_all": subscription_type}
        await self._send_request(req)
        self._subscriptions.clear()
        logger.info("Forgot all %s subscriptions", subscription_type)

    async def get_account_info(self) -> dict:
        """Fetch current account details: balance, currency, login ID."""
        resp = await self._send_request({"get_account_status": 1})
        return resp.get("get_account_status", {})

    # ── Internal: Auth ────────────────────────────────────────────────────────

    async def _authenticate(self) -> None:
        req  = {"authorize": self.cfg.api_token}
        resp = await self._send_request(req)
        auth = resp.get("authorize", {})

        if not auth:
            raise PermissionError("Deriv authentication failed — check API token")

        self.state.authenticated = True
        self.state.account_id    = str(auth.get("loginid", ""))
        self.state.balance       = float(auth.get("balance", 0))
        self.state.currency      = auth.get("currency", "USD")

        logger.info(
            "Authenticated | account=%s | balance=$%.2f %s",
            self.state.account_id, self.state.balance, self.state.currency,
        )

    # ── Internal: Request / Response ──────────────────────────────────────────

    async def _send_request(self, payload: dict) -> dict:
        """
        Send a request and await the correlated response.
        Attaches a req_id, stores a Future, returns when response arrives.
        Raises asyncio.TimeoutError if response doesn't arrive within timeout.
        """
        if not self.state.connected or self._ws is None:
            raise ConnectionError("Not connected to Deriv API")

        req_id          = self._req_id
        self._req_id   += 1
        payload["req_id"] = req_id

        future                  = asyncio.get_event_loop().create_future()
        self._pending[req_id]   = future

        try:
            await self._ws.send(json.dumps(payload))
            logger.debug("→ Sent req_id=%d: %s", req_id, list(payload.keys()))
        except Exception as exc:
            self._pending.pop(req_id, None)
            raise ConnectionError(f"Failed to send request: {exc}") from exc

        try:
            response = await asyncio.wait_for(future, timeout=self.cfg.request_timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise asyncio.TimeoutError(
                f"Request req_id={req_id} timed out after {self.cfg.request_timeout}s"
            )

        # Raise on Deriv API errors
        if "error" in response:
            err = response["error"]
            raise RuntimeError(
                f"Deriv API error [{err.get('code')}]: {err.get('message')}"
            )

        return response

    # ── Internal: Receive Loop ────────────────────────────────────────────────

    async def _receive_loop(self) -> None:
        """Background task: reads messages from WebSocket, dispatches to handlers."""
        import websockets.exceptions as ws_exc

        logger.debug("Receive loop started")
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Malformed WS message: %s", raw[:100])
                    continue

                await self._dispatch(msg)

        except (ws_exc.ConnectionClosed, ws_exc.ConnectionClosedError) as exc:
            if self._running:
                logger.warning("WS connection closed: %s — reconnecting", exc)
                asyncio.create_task(self.reconnect())
        except Exception as exc:
            if self._running:
                logger.error("Receive loop error: %s", exc, exc_info=True)
                asyncio.create_task(self.reconnect())

    async def _dispatch(self, msg: dict) -> None:
        """
        Route an incoming message to the right handler.
        Priority: pending request futures → subscription handlers.
        """
        req_id = msg.get("req_id")

        # Resolve pending request future
        if req_id and req_id in self._pending:
            future = self._pending.pop(req_id)
            if not future.done():
                future.set_result(msg)
            return

        # Subscription message — dispatch to registered handler
        sub_id = msg.get("subscription", {}).get("id")
        if sub_id and sub_id in self._subscriptions:
            handler = self._subscriptions[sub_id]
            try:
                await handler(msg)
            except Exception as exc:
                logger.error("Subscription handler error (sub=%s): %s", sub_id, exc)

    # ── Internal: Heartbeat ───────────────────────────────────────────────────

    async def _ping_loop(self) -> None:
        """Background task: sends ping every ping_interval seconds."""
        while self._running:
            await asyncio.sleep(self.cfg.ping_interval)
            if self.state.connected and self._ws:
                try:
                    await self._ws.send(json.dumps({"ping": 1}))
                    self.state.last_ping = time.time()
                    logger.debug("Ping sent")
                except Exception as exc:
                    logger.warning("Ping failed: %s", exc)

    async def _restore_subscriptions(self) -> None:
        """
        After reconnect, log that subscriptions need to be re-established.
        The application layer (tick_consumer) should handle re-subscription
        by listening for the 'reconnected' event.
        """
        if self._subscriptions:
            logger.warning(
                "Reconnected — %d subscriptions need to be re-established by the app layer",
                len(self._subscriptions),
            )
            self._subscriptions.clear()
