"""Local, demo-only MT5 runner. No credentials or real-account execution.

One worker serializes terminal access. SQLite records decisions before sending
orders, so an ambiguous broker response is never retried for the same candle.
"""
from __future__ import annotations

import importlib
import json
import math
import os
import sqlite3
import threading
import time
from dataclasses import asdict
from contextlib import contextmanager
from datetime import datetime, timezone
from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SYMBOL = "Volatility 75 (1s) Index"
MAGIC = 751006
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class DemoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(SYMBOL, min_length=1, max_length=128, pattern=r"^[^\x00-\x1f\x7f]+$")
    timeframe: Literal["M1", "M5", "M15", "M30", "H1", "H4"] = "M5"
    min_confluence: int = Field(6, ge=1, le=20)
    risk_pct: float = Field(0.005, gt=0, le=0.01)
    daily_loss_pct: float = Field(0.03, gt=0, le=0.05)
    use_zscore: bool = True
    use_rsi: bool = True
    use_bb: bool = True
    use_vwap: bool = True
    use_stoch: bool = True
    use_lsl: bool = True
    use_smc: bool = True
    use_volume: bool = True
    use_hurst: bool = True
    use_linear_regression: bool = False
    use_tree_model: bool = False
    use_time_series_nn: bool = False
    use_smt: bool = False
    use_day_levels: bool = False
    use_candle_reversal: bool = False
    use_candle_continuation: bool = False
    use_crt: bool = False

    @model_validator(mode="after")
    def validate_selection(self):
        if self.symbol != self.symbol.strip():
            raise ValueError('Use the exact broker symbol without surrounding whitespace')
        from app.core.engine.signal_engine import EngineConfig
        EngineConfig(**self.model_dump(exclude={'symbol', 'timeframe', 'daily_loss_pct'}))
        if not any((self.use_zscore, self.use_rsi, self.use_bb, self.use_vwap,
                    self.use_stoch, self.use_lsl, self.use_smc)):
            raise ValueError("Select at least one directional indicator; volume and Hurst alone cannot determine a direction")
        return self


class MT5DemoRunner:
    def __init__(self, journal_path=None, terminal=None):
        self.path = Path(journal_path) if journal_path else DATA_DIR / "mt5_journal.sqlite3"
        self.mt5 = terminal
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker = None
        self.account_key = None
        self.engine = None
        self.last_sync = 0.0
        self.process_lock = None
        self.config = DemoConfig()
        self.state = {"running": False, "connected": False, "symbol": SYMBOL,
                      "mode": "demo", "message": "Connect MT5 after logging into a demo account"}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, account TEXT NOT NULL,
                    kind TEXT NOT NULL, event_key TEXT UNIQUE, payload TEXT NOT NULL);
            """)
            row = db.execute("SELECT value FROM settings WHERE key='strategy'").fetchone()
            if row:
                self.config = DemoConfig.model_validate_json(row[0])
        self.state['symbol'] = self.config.symbol

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def record(self, kind, payload, key=None):
        with self.db() as db:
            cur = db.execute(
                "INSERT OR IGNORE INTO journal(ts, account, kind, event_key, payload) VALUES(?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), self.account_key or "", kind, key,
                 json.dumps(payload, default=str, allow_nan=False)))
            return cur.rowcount == 1

    def configure(self, config):
        with self.lock:
            if self.state["running"]:
                raise ValueError("Stop the demo runner before changing its strategy")
            self._require_connection()
            self._symbol_info(config.symbol)
            with self.db() as db:
                db.execute("INSERT OR REPLACE INTO settings VALUES('strategy', ?)",
                           (config.model_dump_json(),))
                db.execute("DELETE FROM settings WHERE key='research_candidate'")
            self.config = config
            self.state.update(symbol=config.symbol, last_signal=None, open_positions=[],
                              message=f'Saved demo strategy for {config.symbol}. Start explicitly to monitor entries.')
            return self.status()

    def _require_connection(self):
        if not self.mt5 or not self.state['connected']:
            raise ValueError('Connect MT5 demo before selecting a broker symbol')
        return self._account()

    @staticmethod
    def _symbol_problem(info):
        if info is None:
            return 'Symbol unavailable on this account/server'
        # MT5 trade mode: 0 disabled, 1 long-only, 2 short-only, 3 close-only, 4 full.
        if info.trade_mode not in (1, 2, 4):
            return 'Symbol does not allow new positions'
        # Market orders plus broker-held stop loss and take profit are required.
        if info.order_mode & 49 != 49:
            return 'Symbol must support market orders, stop loss and take profit'
        values = (info.point, info.trade_tick_size, info.volume_min, info.volume_max, info.volume_step)
        if any(not math.isfinite(v) or v <= 0 for v in values) or info.volume_max < info.volume_min:
            return 'Invalid broker price or lot specification'
        if not 0 <= info.digits <= 12 or not math.isfinite(info.trade_stops_level) or info.trade_stops_level < 0:
            return 'Invalid broker precision or stop distance'
        return None

    def _symbol_info(self, symbol):
        info = self.mt5.symbol_info(symbol)
        problem = self._symbol_problem(info)
        if problem or info.name != symbol:
            raise ValueError(f'{symbol}: {problem or "Exact broker symbol required"}')
        if not self.mt5.symbol_select(symbol, True):
            raise ValueError(f'{symbol}: cannot select this symbol in Market Watch')
        return info

    def symbols(self):
        with self.lock:
            account, _, _ = self._require_connection()
            rows = self.mt5.symbols_get()
            if rows is None:
                raise ValueError('MT5 symbol catalog unavailable; reconnect and retry')
            return {'account': account.login, 'server': account.server, 'symbols': [
                {'name': info.name, 'description': info.description,
                 'eligible': self._symbol_problem(info) is None, 'reason': self._symbol_problem(info)}
                for info in sorted(rows, key=lambda row: row.name)]}

    def _exposure(self):
        # Existing bot exposure on an earlier symbol still blocks new entries.
        positions, orders = self.mt5.positions_get(), self.mt5.orders_get()
        if positions is None or orders is None:
            raise ValueError('Cannot verify MT5 positions/pending orders; trading paused')
        relevant = lambda row: row.symbol == self.config.symbol or row.magic == MAGIC
        return [p for p in positions if relevant(p)], [o for o in orders if relevant(o)]

    def _account(self):
        terminal = self.mt5.terminal_info()
        account = self.mt5.account_info()
        if not terminal or not terminal.connected or not account:
            raise ValueError("MT5 is disconnected. Log into your demo account in the desktop terminal")
        if account.trade_mode != self.mt5.ACCOUNT_TRADE_MODE_DEMO:
            raise ValueError("Demo account required. This runner does not execute real-money trades")
        key = f"{account.server}:{account.login}"
        if self.account_key and key != self.account_key:
            raise ValueError("MT5 account changed. Stop and reconnect before continuing")
        return account, terminal, key

    def connect(self):
        with self.lock:
            if self.state["running"]:
                raise ValueError("Stop the runner before reconnecting")
            if self.mt5 is None:
                try:
                    self.mt5 = importlib.import_module("MetaTrader5")
                except ImportError as exc:
                    raise ValueError("Install backend requirements-mt5.txt on Windows first") from exc
            self.account_key = None
            path = os.getenv("MT5_TERMINAL_PATH")
            ok = self.mt5.initialize(path, timeout=5000) if path else self.mt5.initialize(timeout=5000)
            if not ok:
                message = f"Cannot connect to MT5: {self.mt5.last_error()}. Open the desktop terminal and log in"
                self.state.update(connected=False, message=message)
                raise ValueError(message)
            try:
                account, terminal, key = self._account()
                self.account_key = key
                self._sync_deals()
                self.state.update(connected=True, account=account.login, server=account.server,
                                  balance=account.balance, equity=account.equity,
                                  trading_allowed=bool(terminal.trade_allowed and not terminal.tradeapi_disabled
                                                       and account.trade_allowed and account.trade_expert),
                                  message="Demo connected. Save your Strategy Lab selection, then start")
            except Exception as exc:
                self.state.update(connected=False, message=str(exc))
                raise
            return self.status()

    def status(self):
        with self.lock:
            evidence = self._research_candidate()
            return {**self.state, "config": self.config.model_dump(),
                    "research_candidate": evidence,
                    "research_validated": bool(evidence and evidence.get('strategy') == self.config.model_dump()
                        and time.time() - evidence.get('validated_at', 0) <= 7 * 86400)}

    def _research_candidate(self):
        with self.db() as db:
            row = db.execute("SELECT value FROM settings WHERE key='research_candidate'").fetchone()
        return json.loads(row[0]) if row else None

    def adopt_research_candidate(self, evidence):
        # Called only with evidence loaded from the server's durable research store.
        with self.lock:
            account, _, _ = self._require_connection()
            snapshot = evidence['snapshot']
            if account.login != snapshot['account'] or account.server != snapshot['server']:
                raise ValueError('Research belongs to a different demo account/server')
            config = DemoConfig(**evidence['strategy'])
            info = self._symbol_info(config.symbol)
            current = {'contract_size': info.trade_contract_size, 'tick_size': info.trade_tick_size,
                       'volume_min': info.volume_min, 'volume_step': info.volume_step, 'volume_max': info.volume_max}
            if any(current[key] != snapshot[key] for key in current):
                raise ValueError('Broker contract specification changed; rerun research')
            self.configure(config)
            with self.db() as db:
                db.execute("INSERT OR REPLACE INTO settings VALUES('research_candidate', ?)", (json.dumps(evidence),))
            self.state['message'] = 'Validated research candidate loaded. Review the saved pair and explicitly Start demo.'
            return self.status()

    def history(self, timeframe, days, symbol=None):
        with self.lock:
            if not self.mt5 or not self.state['connected']:
                raise ValueError('Connect MT5 demo before loading historical candles, or import a CSV')
            self._account()
            symbol = symbol or self.config.symbol
            self._symbol_info(symbol)
            if timeframe not in ('M1', 'M5', 'M15', 'M30', 'H1', 'H4') or not 1 <= days <= 90:
                raise ValueError('Choose M1/M5/M15/M30/H1/H4 and 1–90 days')
            interval = int(timeframe[1:]) * (60 if timeframe.startswith('M') else 3600)
            end_epoch = int(time.time() // interval) * interval
            end = datetime.fromtimestamp(end_epoch - 1, tz=timezone.utc)
            start = end - timedelta(days=days)
            rates = self.mt5.copy_rates_range(symbol, getattr(self.mt5, f'TIMEFRAME_{timeframe}'), start, end)
            # Session-based instruments do not trade 24/7. Do not infer missing
            # candles from wall-clock time; comprehensive gap auditing is separate.
            if rates is None or len(rates) < 100:
                available = 0 if rates is None else len(rates)
                raise ValueError(f'{symbol}: MT5 returned {available} candles; at least 100 are required. Open its chart and load more history or increase the requested days')
            return [dict(timestamp=int(r['time']), open=float(r['open']), high=float(r['high']),
                         low=float(r['low']), close=float(r['close']), volume=float(r['tick_volume'])) for r in rates]

    def start(self, expected_symbol):
        with self.lock:
            if expected_symbol != self.config.symbol:
                raise ValueError('Selected pair differs from the saved strategy. Reload and save before starting.')
            if self.state["running"]:
                return self.status()
            if self.worker and self.worker.is_alive():
                raise ValueError("Previous worker is still stopping")
            if not self.mt5 or not self.state["connected"]:
                raise ValueError("Connect to the MT5 demo terminal first")
            account, terminal, _ = self._account()
            info = self._symbol_info(self.config.symbol)
            evidence = self._research_candidate()
            if not evidence or evidence.get('strategy') != self.config.model_dump() or time.time() - evidence.get('validated_at', 0) > 7 * 86400:
                raise ValueError('Run Analyze selected assets and load a passing research candidate before starting demo entries')
            snapshot = evidence['snapshot']
            if account.login != snapshot['account'] or account.server != snapshot['server']:
                raise ValueError('Research candidate belongs to a different account/server')
            if any(getattr(info, attr) != snapshot[key] for attr, key in
                   [('trade_contract_size','contract_size'), ('trade_tick_size','tick_size'),
                    ('volume_min','volume_min'), ('volume_max','volume_max'), ('volume_step','volume_step')]):
                raise ValueError('Broker contract changed; rerun research')
            if not (terminal.trade_allowed and not terminal.tradeapi_disabled
                    and account.trade_allowed and account.trade_expert):
                raise ValueError("Enable Algo Trading and allow external Python trading in MT5 Options > Expert Advisors")
            from app.core.engine.signal_engine import EngineConfig, SignalEngine
            values = self.config.model_dump(exclude={"symbol", "timeframe", "daily_loss_pct"})
            self.engine = SignalEngine(EngineConfig(**values))
            self.engine.initialise(account.balance)
            # Prevent a second API process from running another strategy on this terminal.
            if os.name == 'nt':
                import msvcrt
                handle = open(self.path.with_suffix('.lock'), 'a+b')
                handle.seek(0)
                if not handle.read(1):
                    handle.write(b'0')
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    handle.close()
                    raise ValueError('Another MT5 demo worker is already running; stop it first') from exc
                self.process_lock = handle
            self.stop_event.clear()
            self.record("started", self.config.model_dump())
            self.state.update(running=True, message=f"Monitoring {self.config.symbol} closed candles for qualifying entries")
            self.worker = threading.Thread(target=self._run, name="mt5-demo", daemon=True)
            self.worker.start()
            return self.status()

    def stop(self):
        self.stop_event.set()
        worker = self.worker
        if worker and worker is not threading.current_thread():
            worker.join(timeout=15)
        with self.lock:
            if worker and worker.is_alive():
                raise ValueError("Stop requested; terminal call is still finishing")
            self.state.update(running=False, message="Stopped. Existing positions retain their broker SL/TP; manage them in MT5")
            self.record("stopped", {})
            return self.status()

    def _run(self):
        try:
            while not self.stop_event.is_set():
                with self.lock:
                    self._tick()
                self.stop_event.wait(2)
        except Exception as exc:
            with self.lock:
                self.state.update(message=str(exc), connected=False)
                self.record("error", {"message": str(exc)})
        finally:
            with self.lock:
                self.state["running"] = False
                if self.process_lock:
                    self.process_lock.close()
                    self.process_lock = None

    def _sync_deals(self):
        # Full bot history also recovers exits that occurred while the backend was off.
        deals = self.mt5.history_deals_get(datetime(2020, 1, 1, tzinfo=timezone.utc),
                                            datetime.now(timezone.utc))
        if deals is None:
            raise ValueError("MT5 deal history unavailable; trading paused to preserve the journal")
        ids = {(d.position_id, d.symbol) for d in deals if d.magic == MAGIC}
        for deal in deals:
            if (deal.position_id, deal.symbol) in ids:
                self.record("deal", deal._asdict(), f"deal:{self.account_key}:{deal.ticket}")
        self.last_sync = time.monotonic()

    def _daily_guard(self, account):
        day = datetime.now(timezone.utc).date().isoformat()
        key = f"day:{self.account_key}:{day}"
        with self.db() as db:
            if db.execute("SELECT 1 FROM settings WHERE key=?", (key + ':halted',)).fetchone():
                return False
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            baseline = float(row[0]) if row else account.equity
            if not row:
                db.execute("INSERT INTO settings VALUES(?, ?)", (key, str(baseline)))
            if baseline <= 0 or account.equity <= baseline * (1 - self.config.daily_loss_pct):
                db.execute("INSERT OR REPLACE INTO settings VALUES(?, 'true')", (key + ':halted',))
                return False
        return True

    def _tick(self):
        account, terminal, _ = self._account()
        if not (terminal.trade_allowed and not terminal.tradeapi_disabled
                and account.trade_allowed and account.trade_expert):
            raise ValueError("MT5 algorithmic trading permission was disabled")
        if time.monotonic() - self.last_sync >= 15:
            self._sync_deals()
        positions, orders = self._exposure()
        self.state.update(balance=account.balance, equity=account.equity,
                          open_positions=[p._asdict() for p in positions],
                          last_poll=datetime.now(timezone.utc).isoformat())
        if not self._daily_guard(account):
            self.state["message"] = "Daily equity loss limit reached; entries paused until the next UTC day"
            return
        if positions or orders:
            self.state["message"] = f"Waiting: exposure exists on {self.config.symbol} or an earlier bot pair"
            return
        rates = self.mt5.copy_rates_from_pos(self.config.symbol, getattr(self.mt5, f"TIMEFRAME_{self.config.timeframe}"), 1, 500)
        if rates is None or len(rates) < 100:
            self.state["message"] = "Waiting for at least 100 closed MT5 candles; open the symbol chart"
            return
        from app.core.lsl.lsl_detector import Candle
        candles = [Candle(timestamp=int(r["time"]), open=float(r["open"]), high=float(r["high"]),
                          low=float(r["low"]), close=float(r["close"]), volume=float(r["tick_volume"])) for r in rates]
        bar = candles[-1].timestamp
        interval = int(self.config.timeframe[1:]) * (60 if self.config.timeframe.startswith('M') else 3600)
        if time.time() - bar > interval * 2 + 30 or bar > time.time():
            self.state['message'] = 'Waiting for current closed candles; history is stale'
            return
        # Preserve V75's legacy key so upgrading cannot replay its last candle.
        symbol_key = '' if self.config.symbol == SYMBOL else f'{self.config.symbol}:'
        bar_key = f"bar:{self.account_key}:{symbol_key}{self.config.timeframe}:{bar}"
        with self.db() as db:
            if db.execute("SELECT 1 FROM journal WHERE event_key=?", (bar_key,)).fetchone():
                return
        self.engine.sizer.update_balance(account.balance)
        decision = self.engine.evaluate(candles, symbol=self.config.symbol, timeframe=self.config.timeframe)
        payload = {"bar": bar, "symbol": self.config.symbol, "direction": decision.direction,
                   "score": decision.confluence_score, "reason": decision.reason,
                   "should_trade": decision.should_trade, "strategy": self.config.model_dump(),
                   "breakdown": asdict(decision.confluence.breakdown) if decision.confluence else {}}
        if not self.record("signal", payload, bar_key):
            return
        self.state.update(last_signal=payload, message=decision.reason)
        if decision.should_trade and not self.stop_event.is_set():
            self._send(decision, account, bar_key)

    def _send(self, decision, account, bar_key):
        # Recheck immediately before preparing any broker request.
        current, _, _ = self._account()
        if not self._daily_guard(current):
            return
        positions, orders = self._exposure()
        if positions or orders:
            return
        symbol = self.config.symbol
        info = self._symbol_info(symbol)
        tick = self.mt5.symbol_info_tick(symbol)
        if not tick or abs(time.time() - tick.time) > 30:
            raise ValueError(f"No fresh {symbol} quote; no order submitted")
        if decision.direction not in ('buy', 'sell'):
            raise ValueError('Invalid order direction')
        buy = decision.direction == "buy"
        if (info.trade_mode == 1 and not buy) or (info.trade_mode == 2 and buy):
            raise ValueError(f'{symbol}: broker does not allow this order direction')
        if not all(math.isfinite(v) and v > 0 for v in (tick.ask, tick.bid)) or tick.ask < tick.bid:
            raise ValueError('Invalid bid/ask; no order submitted')
        price = tick.ask if buy else tick.bid
        distance = decision.atr.value * 1.5
        if not math.isfinite(distance) or distance <= 0 or price <= 0:
            raise ValueError("Invalid price or ATR; no order submitted")
        step = info.trade_tick_size or info.point
        sl = round(round((price - distance if buy else price + distance) / step) * step, info.digits)
        tp = round(round((price + 2 * distance if buy else price - 2 * distance) / step) * step, info.digits)
        minimum = info.trade_stops_level * info.point
        if (buy and (sl >= tick.bid - minimum or tp <= tick.bid + minimum)) or (
                not buy and (sl <= tick.ask + minimum or tp >= tick.ask - minimum)):
            raise ValueError("Strategy stop distances do not meet broker limits; no order submitted")
        side = self.mt5.ORDER_TYPE_BUY if buy else self.mt5.ORDER_TYPE_SELL
        if sl <= 0 or tp <= 0:
            raise ValueError('Protective prices must be positive')
        reference_loss = self.mt5.order_calc_profit(side, symbol, info.volume_min, price, sl)
        unit_loss = reference_loss / info.volume_min if reference_loss is not None else None
        if unit_loss is None or not math.isfinite(unit_loss) or unit_loss >= 0:
            raise ValueError("MT5 could not calculate risk in account currency")
        budget = min(current.balance, current.equity) * self.config.risk_pct
        if not math.isfinite(budget) or budget <= 0:
            raise ValueError('Invalid account risk budget')
        volume = round(math.floor(min(budget / abs(unit_loss), info.volume_max) / info.volume_step) * info.volume_step, 8)
        if volume < info.volume_min:
            self.state["message"] = "Skipped: minimum broker lot exceeds the configured risk budget"
            self.record("skipped", {"reason": self.state["message"]})
            return
        if not info.filling_mode & 3 and info.trade_exemode == 2:
            raise ValueError(f'{symbol}: no supported market filling policy')
        filling = (self.mt5.ORDER_FILLING_FOK if info.filling_mode & 1 else
                   self.mt5.ORDER_FILLING_IOC if info.filling_mode & 2 else self.mt5.ORDER_FILLING_RETURN)
        request = dict(action=self.mt5.TRADE_ACTION_DEAL, symbol=symbol, volume=volume,
                       type=side, price=price, sl=sl, tp=tp, deviation=20,
                       magic=MAGIC, comment="Strategy lab demo", type_time=self.mt5.ORDER_TIME_GTC,
                       type_filling=filling)
        check = self.mt5.order_check(request)
        if check is None or check.retcode != 0:
            raise ValueError(f"MT5 order check rejected: {check.comment if check else self.mt5.last_error()}")
        if self.stop_event.is_set():
            return
        account, terminal, _ = self._account()
        if not (terminal.trade_allowed and not terminal.tradeapi_disabled
                and account.trade_allowed and account.trade_expert):
            raise ValueError('MT5 algorithmic trading permission was disabled')
        if not self.record("order_request", request, f"request:{bar_key}"):
            return
        result = self.mt5.order_send(request)
        self.record("order_result", {**(result._asdict() if result else {"error": str(self.mt5.last_error())}), 'symbol': symbol})
        if result is None or result.retcode not in (self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_DONE_PARTIAL):
            raise ValueError("MT5 order response requires review in the journal/terminal; no automatic retry")
        self.state["message"] = f"Demo order executed: {result.order}"

    def journal(self, limit=200):
        with self.lock:
            if self.mt5 and self.state['connected'] and not self.state['running'] and time.monotonic() - self.last_sync >= 15:
                try:
                    account, _, _ = self._account()
                    self._sync_deals()
                    positions, _ = self._exposure()
                    self.state.update(balance=account.balance, equity=account.equity,
                                      open_positions=[p._asdict() for p in positions])
                except Exception as exc:
                    self.state.update(connected=False, message=str(exc))
        with self.db() as db:
            rows = db.execute("SELECT id,ts,account,kind,payload FROM journal ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [{"id": r[0], "ts": r[1], "account": r[2], "kind": r[3], "data": json.loads(r[4])} for r in rows]
