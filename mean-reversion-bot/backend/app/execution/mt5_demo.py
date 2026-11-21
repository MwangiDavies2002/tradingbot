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
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.quant.research_sessions import in_window, market_is_open
from app.quant.instruments import (classify_instrument, specification_fingerprint,
                                   specification_issues, specification_payload,
                                   configuration_fingerprint, timeframe_seconds)
from app.quant.strategy_identity import EXECUTION_STRATEGY_NAME, EXECUTION_STRATEGY_VERSION

MAGIC = 751006
LEGACY_UNQUALIFIED_JOURNAL_SYMBOL = "Volatility 75 (1s) Index"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def compare_forward_performance(candidate, deals, orders=(), minimum_sample=20):
    baseline = (candidate or {}).get('research_baseline')
    if not baseline:
        return {'status': 'no_baseline', 'alert': False, 'closed_trades': 0}
    snapshot = candidate.get('snapshot') or {}
    scope = f"{snapshot.get('server')}:{snapshot.get('account')}"
    run_id = candidate.get('run_id')
    symbol = (candidate.get('strategy') or {}).get('symbol')
    loaded_at = float(candidate.get('loaded_at') or candidate.get('validated_at') or 0)
    linked_orders = set()
    linked_deals = set()
    for row in orders:
        order = row.get('data') or {}
        ticket = order.get('order')
        if (row.get('account') == scope and run_id and order.get('research_run_id') == run_id
                and order.get('strategy') == candidate.get('strategy') and order.get('symbol') == symbol
                and order.get('accepted') is True):
            if type(ticket) is int and ticket > 0:
                linked_orders.add(ticket)
            deal_ticket = order.get('deal')
            if type(deal_ticket) is int and deal_ticket > 0:
                linked_deals.add(deal_ticket)
    positions = {}
    for row in deals:
        deal = row.get('data') or {}
        position_id = deal.get('position_id')
        if (row.get('account') != scope or deal.get('symbol') != symbol
                or type(position_id) is not int or position_id <= 0):
            continue
        positions.setdefault(position_id, []).append(deal)
    pnl = []
    incomplete = 0
    for position_deals in positions.values():
        entries = [d for d in position_deals if d.get('entry') == 0]
        exits = [d for d in position_deals if d.get('entry') == 1]
        if not entries or not all((d.get('order') in linked_orders or d.get('ticket') in linked_deals)
                                  and d.get('magic') == MAGIC
                                  and float(d.get('time') or 0) >= loaded_at for d in entries):
            continue
        if any(d.get('entry') not in (0, 1) for d in position_deals):
            incomplete += 1
            continue
        try:
            opened = sum(float(d['volume']) for d in entries)
            closed = sum(float(d['volume']) for d in exits)
            if not math.isfinite(opened) or not math.isfinite(closed) or opened <= 0 or closed < 0:
                raise ValueError()
            if abs(opened - closed) > max(1e-8, opened * 1e-6):
                incomplete += 1
                continue
            value = sum(float(d.get(key, 0) or 0) for d in position_deals
                        for key in ('profit', 'commission', 'swap', 'fee'))
            if not math.isfinite(value):
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            incomplete += 1
            continue
        pnl.append(value)
    wins = sum(value for value in pnl if value > 0)
    losses = -sum(value for value in pnl if value < 0)
    profit_factor = wins / losses if losses else None
    baseline_pf = baseline.get('holdout', {}).get('profit_factor')
    alert = (len(pnl) >= minimum_sample and baseline_pf is not None and baseline_pf > 0
             and profit_factor is not None and profit_factor < baseline_pf * .5)
    return {'status': 'deteriorating' if alert else ('observing' if len(pnl) >= minimum_sample else 'insufficient_sample'),
            'alert': alert, 'closed_trades': len(pnl), 'total_pnl': round(sum(pnl), 2),
            'profit_factor': round(profit_factor, 3) if profit_factor is not None else None,
            'minimum_sample': minimum_sample, 'baseline_profit_factor': baseline_pf,
            'incomplete_positions': incomplete, 'linked_orders': len(linked_orders),
            'linked_deals': len(linked_deals),
            'research_run_id': run_id, 'account_scope': scope, 'symbol': symbol,
            'currency': snapshot.get('currency'), 'attribution': 'candidate_order_position_v1'}


class DemoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field("", max_length=128, pattern=r"^[^\x00-\x1f\x7f]*$")
    timeframe: Literal["M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15",
               "M20", "M30", "H1", "H2", "H3", "H4", "H6", "H8", "H12",
               "D1", "W1"] = "M5"
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
        if self.symbol and self.symbol != self.symbol.strip():
            raise ValueError('Use the exact broker symbol without surrounding whitespace')
        from app.core.engine.signal_engine import EngineConfig
        EngineConfig(**self.model_dump(exclude={'symbol', 'timeframe', 'daily_loss_pct'}))
        if not any((self.use_zscore, self.use_rsi, self.use_bb, self.use_vwap,
                    self.use_stoch, self.use_lsl, self.use_smc)):
            raise ValueError("Select at least one directional indicator; volume and Hurst alone cannot determine a direction")
        return self


def research_session_allowed(candidate, bar_timestamp, interval):
    candidate = candidate or {}
    sessions = candidate.get('research_scope', {}).get('sessions', [])
    if sessions and not (
            any(in_window(bar_timestamp, session) for session in sessions)
            and any(in_window(bar_timestamp + interval, session) for session in sessions)):
        return False
    calendar = (candidate.get('configuration') or {}).get('session_calendar')
    if calendar:
        from app.quant.schemas import Session
        verified_calendar = Session.model_validate(calendar)
        return (verified_calendar.confirmed
                and market_is_open(bar_timestamp, verified_calendar)
                and market_is_open(bar_timestamp + interval, verified_calendar))
    return not candidate.get('configuration')


def candidate_configuration_matches(candidate):
    configuration = (candidate or {}).get('configuration')
    strategy = (candidate or {}).get('strategy')
    snapshot = (candidate or {}).get('snapshot') or {}
    if not isinstance(configuration, dict) or not isinstance(strategy, dict):
        return False
    try:
        if configuration_fingerprint(configuration) != candidate.get('configuration_fingerprint'):
            return False
        instrument = configuration['instrument']
        strategy_spec = configuration['strategy']
        risk = configuration['risk']
        session_calendar = configuration['session_calendar']
        profile = candidate['instrument_profile']
        cost_fields = ('commission_per_lot', 'financing_long', 'financing_short',
                       'rollover_timezone', 'rollover_minute', 'rollover_weights',
                       'spread_price', 'slippage_ticks', 'market_impact_ticks_per_lot',
                       'price_basis', 'fx_rates', 'fx_max_age_seconds', 'costs_confirmed',
                       'cost_source', 'rollover_confirmed', 'rollover_source',
                       'slippage_confirmed', 'slippage_source')
        parameters = {key: value for key, value in strategy.items()
                      if key not in {'symbol', 'timeframe', 'risk_pct', 'daily_loss_pct'}}
        return (instrument['symbol'] == strategy['symbol'] == snapshot.get('symbol')
                and instrument['broker_server'] == snapshot.get('server')
                and instrument['asset_class'] == profile['asset_class'] == snapshot.get('asset_class')
                and instrument['broker_group'] == profile['broker_group'] == snapshot.get('broker_group')
                and profile['account_currency'] == snapshot.get('currency')
                and configuration['timeframe'] == strategy['timeframe']
                and strategy_spec['name'] == EXECUTION_STRATEGY_NAME
                and strategy_spec['version'] == EXECUTION_STRATEGY_VERSION
                and strategy_spec['parameters'] == parameters
                and profile['specification_confirmed'] is True
                and profile['costs_confirmed'] is True
                and profile['slippage_confirmed'] is True
                and configuration['profile_fingerprint'] == configuration_fingerprint(profile)
                and configuration['cost_model_fingerprint'] == configuration_fingerprint(
                    {key: profile[key] for key in cost_fields})
                and profile['specification_fingerprint'] == configuration['specification_fingerprint']
                and profile['session'] == session_calendar
                and session_calendar['confirmed'] is True
                and bool(session_calendar['source'].strip())
                and risk == {'risk_pct': strategy['risk_pct'],
                             'daily_loss_pct': strategy['daily_loss_pct']}
                and configuration['specification_fingerprint'] == snapshot.get('specification_fingerprint'))
    except (KeyError, TypeError, ValueError):
        return False


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
        self.state = {"running": False, "connected": False, "symbol": "",
                      "mode": "demo", "message": "Connect MT5 after logging into a demo account"}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY, ts TEXT NOT NULL, account TEXT NOT NULL,
                    kind TEXT NOT NULL, event_key TEXT UNIQUE, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS journal_kind_account ON journal(kind,account);
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
        if not symbol:
            raise ValueError('Select an exact broker instrument first')
        info = self._market_info(symbol)
        problem = self._symbol_problem(info)
        if problem:
            raise ValueError(f'{symbol}: {problem or "Exact broker symbol required"}')
        return info

    def _market_info(self, symbol):
        if not symbol:
            raise ValueError('Select an exact broker instrument first')
        info = self.mt5.symbol_info(symbol)
        if not info or info.name != symbol:
            raise ValueError(f'{symbol}: exact broker symbol unavailable')
        if not self.mt5.symbol_select(symbol, True):
            raise ValueError(f'{symbol}: cannot select this symbol in Market Watch')
        return info

    def symbols(self):
        with self.lock:
            account, _, _ = self._require_connection()
            rows = self.mt5.symbols_get()
            if rows is None:
                raise ValueError('MT5 symbol catalog unavailable; reconnect and retry')
            return {'account': account.login, 'server': account.server, 'account_currency': account.currency, 'symbols': [
                {'name': info.name, 'description': info.description,
                 'asset_class': classify_instrument(info, self.mt5),
                 'broker_group': getattr(info, 'path', '') or '',
                 'account_currency': account.currency,
                 'eligible': self._symbol_problem(info) is None, 'reason': self._symbol_problem(info),
                 'specification_fingerprint': specification_fingerprint(info),
                 'specification_issues': specification_issues(info),
                 'specification': specification_payload(info)}
                for info in sorted(rows, key=lambda row: row.name)]}

    def _exposure(self):
        # Existing bot exposure on an earlier symbol still blocks new entries.
        positions, orders = self.mt5.positions_get(), self.mt5.orders_get()
        if positions is None or orders is None:
            raise ValueError('Cannot verify MT5 positions/pending orders; trading paused')
        def relevant(row):
            return row.symbol == self.config.symbol or row.magic == MAGIC
        return [p for p in positions if relevant(p)], [o for o in orders if relevant(o)]

    def _account(self):
        terminal = self.mt5.terminal_info()
        account = self.mt5.account_info()
        if not terminal:
            raise ValueError("Could not communicate with MT5 terminal. Check that it is open.")
        if not terminal.connected:
            raise ValueError("MT5 terminal is not connected to a broker server. Check your internet and broker login.")
        if not account:
            raise ValueError("No MT5 account info. Log into your demo account in the desktop terminal.")
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
            # Try some common default paths if not set
            if not path:
                defaults = [
                    r"C:\Program Files\MetaTrader 5\terminal64.exe",
                    r"C:\Program Files\Deriv MetaTrader 5\terminal64.exe",
                    r"C:\Program Files\MetaTrader 5 Terminal\terminal64.exe"
                ]
                for d in defaults:
                    if os.path.exists(d):
                        path = d
                        break

            ok = self.mt5.initialize(path=path, timeout=60000) if path else self.mt5.initialize(timeout=60000)
            if not ok:
                err = self.mt5.last_error()
                message = f"Cannot connect to MT5: {err}. Open the desktop terminal and log in. Error code: {err}"
                if err == -5: # Terminal not found
                    message += " (Terminal executable not found. Set MT5_TERMINAL_PATH in .env)"
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
            deal_rows, order_rows = [], []
            if evidence:
                snapshot = evidence.get('snapshot') or {}
                scope = f"{snapshot.get('server')}:{snapshot.get('account')}"
                symbol = (evidence.get('strategy') or {}).get('symbol')
                with self.db() as db:
                    deal_rows = [{'account': scope, 'data': json.loads(payload)} for (payload,) in db.execute(
                        "SELECT payload FROM journal WHERE kind='deal' AND account=? AND json_extract(payload,'$.symbol')=?",
                        (scope, symbol))]
                    order_rows = [{'account': scope, 'data': json.loads(payload)} for (payload,) in db.execute(
                        "SELECT payload FROM journal WHERE kind='order_result' AND account=? AND json_extract(payload,'$.research_run_id')=?",
                        (scope, evidence.get('run_id')))]
            comparison = compare_forward_performance(evidence, deal_rows, order_rows)
            snapshot = (evidence or {}).get('snapshot') or {}
            age = time.time() - (evidence or {}).get('validated_at', 0)
            return {**self.state, "config": self.config.model_dump(),
                    "research_candidate": evidence,
                    "research_comparison": comparison,
                    "research_validated": bool(evidence and self.state.get('connected')
                        and snapshot.get('server') == self.state.get('server')
                        and snapshot.get('account') == self.state.get('account')
                        and evidence.get('strategy') == self.config.model_dump()
                        and candidate_configuration_matches(evidence)
                        and 0 <= age <= 7 * 86400)}

    def preflight(self):
        """Read-only checks for one demo pair. This never selects a symbol or sends an order."""
        with self.lock:
            now = time.time()
            checks = []
            def add(code, stage, ok, message, success_message=None):
                checks.append({'code': code, 'stage': stage, 'ok': bool(ok),
                               'message': success_message if ok and success_message else message})

            evidence = self._research_candidate()
            add('instrument_selected', 'start', bool(self.config.symbol),
                'Select an exact broker instrument',
                'Exact broker instrument selected')
            add('candidate_loaded', 'start', evidence is not None,
                'Load a passing instrument-specific candidate from research',
                'Validated research candidate loaded')
            if evidence:
                age = now - evidence.get('validated_at', 0)
                add('candidate_fresh', 'start', 0 <= age <= 7 * 86400,
                    'Research candidate is older than seven days; rerun Analyze',
                    'Research candidate is within seven days')
                add('strategy_match', 'start', evidence.get('strategy') == self.config.model_dump(),
                    'Saved MT5 strategy differs from the research candidate',
                    'Saved strategy matches the research candidate')
                add('candidate_identity', 'start', candidate_configuration_matches(evidence),
                    'Candidate instrument, timeframe, strategy or risk identity is inconsistent',
                    'Candidate research configuration identity matches')

            account = terminal = scope = None
            try:
                account, terminal, scope = self._require_connection()
            except ValueError as exc:
                add('demo_connected', 'start', False, str(exc))
            else:
                add('demo_connected', 'start', True, 'Connect MT5 demo before selecting a broker symbol',
                    'Connected MT5 demo account')
                snapshot = (evidence or {}).get('snapshot') or {}
                if evidence:
                    add('account_match', 'start', account.server == snapshot.get('server')
                        and account.login == snapshot.get('account'),
                        'Connected demo account/server differs from the research candidate',
                        'Connected demo account/server matches the research candidate')
                allowed = bool(terminal.trade_allowed and not terminal.tradeapi_disabled
                               and account.trade_allowed and account.trade_expert)
                add('trading_permissions', 'start', allowed,
                    'Enable Algo Trading and external Python trading in MT5',
                    'MT5 algorithmic trading permissions are enabled')

            info = None
            if account is not None and self.config.symbol:
                info = self.mt5.symbol_info(self.config.symbol)
                problem = self._symbol_problem(info)
                exact = bool(info and info.name == self.config.symbol)
                add('broker_symbol', 'start', problem is None and exact,
                    f'{self.config.symbol}: {problem or "Exact broker symbol unavailable"}',
                    f'{self.config.symbol}: exact broker symbol available')
                if evidence and info and problem is None and exact:
                    snapshot = evidence.get('snapshot') or {}
                    contract = all(snapshot.get(key) is not None and getattr(info, attr, None) == snapshot[key]
                                   for attr, key in (('trade_contract_size', 'contract_size'),
                                                     ('trade_tick_size', 'tick_size'),
                                                     ('volume_min', 'volume_min'),
                                                     ('volume_step', 'volume_step'),
                                                     ('volume_max', 'volume_max')))
                    add('contract_match', 'start', contract,
                        'Broker contract changed; rerun Analyze for this pair',
                        'Broker contract matches the research candidate')
                    fingerprint_match = (snapshot.get('specification_fingerprint')
                                         == specification_fingerprint(info))
                    add('specification_match', 'start', fingerprint_match,
                        'Broker instrument specifications changed; rerun research',
                        'Full broker specification matches the candidate')
            elif account is not None:
                add('broker_symbol', 'start', False, 'Select an exact broker instrument')

            if account is not None:
                try:
                    positions, orders = self._exposure()
                except ValueError as exc:
                    add('exposure_query', 'start', False, str(exc))
                else:
                    add('exposure_query', 'start', True, 'Cannot verify broker exposure',
                        'Broker exposure query available')
                    add('no_exposure', 'market', not positions and not orders,
                        'Existing position or pending order blocks a new demo entry',
                        'No relevant positions or pending orders')
                day = datetime.now(timezone.utc).date().isoformat()
                with self.db() as db:
                    halted = db.execute("SELECT 1 FROM settings WHERE key=?",
                                        (f'day:{scope}:{day}:halted',)).fetchone() is not None
                add('daily_limit', 'market', not halted,
                    'Daily equity loss limit is latched; entries are paused today',
                    'Daily equity loss guard is clear')

            if account is not None and info is not None:
                session_calendar = ((evidence or {}).get('configuration') or {}).get('session_calendar')
                if session_calendar:
                    from app.quant.schemas import Session
                    calendar_open = market_is_open(int(now), Session.model_validate(session_calendar))
                    add('instrument_session', 'market', calendar_open,
                        'Instrument broker calendar is closed or unverified',
                        'Instrument broker calendar is open')
                tick = self.mt5.symbol_info_tick(self.config.symbol)
                valid_quote = bool(tick and all(math.isfinite(v) and v > 0 for v in
                    (tick.bid, tick.ask, tick.time)) and tick.ask >= tick.bid
                    and abs(now - tick.time) <= 30)
                add('fresh_quote', 'market', valid_quote,
                    'No fresh bid/ask quote for this pair; wait for an open market',
                    'Fresh bid/ask quote available')
                rates = self.mt5.copy_rates_from_pos(self.config.symbol,
                    getattr(self.mt5, f'TIMEFRAME_{self.config.timeframe}'), 1, 100)
                interval = timeframe_seconds(self.config.timeframe)
                latest = int(rates[-1]['time']) if rates is not None and len(rates) >= 100 else None
                fresh_bars = latest is not None and 0 <= now - latest <= interval * 2 + 30
                add('fresh_candles', 'market', fresh_bars,
                    'At least 100 recent closed candles are needed; open the pair chart or wait for an open market',
                    'Recent closed candles available')

            start_blockers = [c['message'] for c in checks if c['stage'] == 'start' and not c['ok']]
            market_blockers = [c['message'] for c in checks if c['stage'] == 'market' and not c['ok']]
            return {'symbol': self.config.symbol, 'timeframe': self.config.timeframe,
                    'account_scope': scope, 'research_run_id': (evidence or {}).get('run_id'),
                    'monitoring': bool(self.state['running']),
                    'ready_to_start': not start_blockers and not self.state['running'],
                    'live_market_ready': not start_blockers and not market_blockers,
                    'checks': checks, 'start_blockers': start_blockers,
                    'market_blockers': market_blockers, 'read_only': True}

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
            if not candidate_configuration_matches(evidence):
                raise ValueError('Research candidate configuration identity is incomplete or inconsistent')
            info = self._symbol_info(config.symbol)
            if specification_fingerprint(info) != snapshot.get('specification_fingerprint'):
                raise ValueError('Broker instrument specifications changed; rerun research')
            current = {'contract_size': info.trade_contract_size, 'tick_size': info.trade_tick_size,
                       'volume_min': info.volume_min, 'volume_step': info.volume_step, 'volume_max': info.volume_max}
            if any(current[key] != snapshot[key] for key in current):
                raise ValueError('Broker contract specification changed; rerun research')
            previous = self._research_candidate()
            same_candidate = (previous and previous.get('run_id') == evidence.get('run_id')
                              and previous.get('strategy') == evidence.get('strategy')
                              and previous.get('snapshot') == evidence.get('snapshot'))
            self.configure(config)
            evidence = {**evidence, 'loaded_at': (previous.get('loaded_at') if same_candidate else None) or time.time()}
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
            if not symbol:
                raise ValueError('Select an exact broker instrument before loading history')
            self._symbol_info(symbol)
            if not 1 <= days <= 90:
                raise ValueError('Choose a supported MT5 timeframe and 1–90 days')
            try:
                timeframe_seconds(timeframe)
                mt5_timeframe = getattr(self.mt5, f'TIMEFRAME_{timeframe}')
            except (ValueError, AttributeError) as exc:
                raise ValueError(f'{timeframe}: timeframe is not supported by this MT5 terminal') from exc
            current_bar = self.mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, 1)
            if current_bar is None or len(current_bar) != 1:
                raise ValueError(f'{symbol} {timeframe}: cannot determine the current broker candle boundary')
            end_epoch = int(current_bar[0]['time'])
            end = datetime.fromtimestamp(end_epoch - 1, tz=timezone.utc)
            start = datetime.fromtimestamp(end_epoch - days * 86400, tz=timezone.utc)
            rates = self.mt5.copy_rates_range(symbol, mt5_timeframe, start, end)
            # Session-based instruments do not trade 24/7. Do not infer missing
            # candles from wall-clock time; comprehensive gap auditing is separate.
            if rates is None or len(rates) < 100:
                available = 0 if rates is None else len(rates)
                raise ValueError(f'{symbol}: MT5 returned {available} candles; at least 100 are required. Open its chart and load more history or increase the requested days')
            return [dict(timestamp=int(r['time']), open=float(r['open']), high=float(r['high']),
                         low=float(r['low']), close=float(r['close']), volume=float(r['tick_volume']))
                    for r in rates if int(r['time']) < end_epoch]

    def start(self, expected_symbol):
        with self.lock:
            if not expected_symbol or expected_symbol != self.config.symbol:
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
            if (not evidence or evidence.get('strategy') != self.config.model_dump()
                    or not candidate_configuration_matches(evidence)
                    or time.time() - evidence.get('validated_at', 0) > 7 * 86400):
                raise ValueError('Run Analyze selected assets and load a passing research candidate before starting demo entries')
            snapshot = evidence['snapshot']
            if account.login != snapshot['account'] or account.server != snapshot['server']:
                raise ValueError('Research candidate belongs to a different account/server')
            if any(getattr(info, attr) != snapshot[key] for attr, key in
                   [('trade_contract_size','contract_size'), ('trade_tick_size','tick_size'),
                    ('volume_min','volume_min'), ('volume_max','volume_max'), ('volume_step','volume_step')]):
                raise ValueError('Broker contract changed; rerun research')
            if specification_fingerprint(info) != snapshot.get('specification_fingerprint'):
                raise ValueError('Broker instrument specifications changed; rerun research')
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
        interval = timeframe_seconds(self.config.timeframe)
        if time.time() - bar > interval * 2 + 30 or bar > time.time():
            self.state['message'] = 'Waiting for current closed candles; history is stale'
            return
        # Preserve the old runner's unqualified candle key during migration.
        symbol_key = '' if self.config.symbol == LEGACY_UNQUALIFIED_JOURNAL_SYMBOL else f'{self.config.symbol}:'
        bar_key = f"bar:{self.account_key}:{symbol_key}{self.config.timeframe}:{bar}"
        with self.db() as db:
            if db.execute("SELECT 1 FROM journal WHERE event_key=?", (bar_key,)).fetchone():
                return
        self.engine.sizer.update_balance(account.balance)
        decision = self.engine.evaluate(candles, symbol=self.config.symbol, timeframe=self.config.timeframe)
        session_allowed = research_session_allowed(self._research_candidate(), bar, interval)
        reason = decision.reason if session_allowed else 'outside_research_session'
        payload = {"bar": bar, "symbol": self.config.symbol, "direction": decision.direction,
                   "score": decision.confluence_score, "reason": reason,
                   "should_trade": decision.should_trade and session_allowed, "strategy": self.config.model_dump(),
                   "breakdown": asdict(decision.confluence.breakdown) if decision.confluence else {}}
        if not self.record("signal", payload, bar_key):
            return
        self.state.update(last_signal=payload, message=reason)
        if decision.should_trade and session_allowed and not self.stop_event.is_set():
            self._send(decision, account, bar_key)

    def _send(self, decision, account, bar_key):
        evidence = self._research_candidate()
        age = time.time() - evidence.get('validated_at', 0) if evidence else None
        if (not evidence or not 0 <= age <= 7 * 86400
                or evidence.get('strategy') != self.config.model_dump()
                or not candidate_configuration_matches(evidence)):
            raise ValueError('A current matching research candidate is required before preparing an order')

        snapshot = evidence.get('snapshot') or {}
        current, _, _ = self._account()
        if current.login != snapshot.get('account') or current.server != snapshot.get('server'):
            raise ValueError('Research candidate belongs to a different account/server')
        if not self._daily_guard(current):
            return
        positions, orders = self._exposure()
        if positions or orders:
            return
        symbol = self.config.symbol
        info = self._symbol_info(symbol)
        if specification_fingerprint(info) != snapshot.get('specification_fingerprint'):
            raise ValueError('Broker instrument specifications changed; rerun research')
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
        profile = evidence['instrument_profile']
        commission = profile['commission_per_lot']
        financing = profile['financing_long' if buy else 'financing_short']
        slippage_ticks = profile['slippage_ticks']
        impact_ticks_per_lot = profile['market_impact_ticks_per_lot']
        if (not all(math.isfinite(value) for value in
                    (commission, financing, slippage_ticks, impact_ticks_per_lot))
                or commission < 0 or slippage_ticks < 0 or impact_ticks_per_lot < 0):
            raise ValueError('Candidate execution costs are invalid')
        if financing > 0:
            raise ValueError('Positive financing cannot be bounded without a maximum holding period; no order submitted')
        budget = min(current.balance, current.equity) * self.config.risk_pct
        if not math.isfinite(budget) or budget <= 0:
            raise ValueError('Invalid account risk budget')

        def estimated_risk(volume):
            adverse_slippage = (slippage_ticks + impact_ticks_per_lot * volume) * step
            sign = 1 if buy else -1
            adverse_entry = price + sign * adverse_slippage
            adverse_stop = sl - sign * adverse_slippage
            if adverse_entry <= 0 or adverse_stop <= 0:
                raise ValueError('Candidate slippage makes the order price invalid')
            pnl = self.mt5.order_calc_profit(side, symbol, volume, adverse_entry, adverse_stop)
            if pnl is None or not math.isfinite(pnl) or pnl >= 0:
                raise ValueError('MT5 could not calculate stop risk in account currency')
            return abs(pnl) + commission * volume

        min_steps = math.ceil(info.volume_min / info.volume_step - 1e-12)
        max_steps = math.floor(info.volume_max / info.volume_step + 1e-12)
        if min_steps > max_steps:
            raise ValueError('Broker volume limits have no valid increment')
        low, high = min_steps - 1, max_steps
        while low < high:
            middle = (low + high + 1) // 2
            candidate_volume = round(middle * info.volume_step, 8)
            if estimated_risk(candidate_volume) <= budget:
                low = middle
            else:
                high = middle - 1
        volume = round(low * info.volume_step, 8)
        if volume < info.volume_min:
            self.state["message"] = "Skipped: minimum broker lot exceeds the configured risk budget"
            self.record("skipped", {"reason": self.state["message"]})
            return
        if estimated_risk(volume) > budget:
            raise ValueError('Calculated order risk exceeds the configured budget; no order submitted')
        try:
            margin_free = float(current.margin_free)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError('MT5 did not provide available free margin; no order submitted') from exc
        if not math.isfinite(margin_free) or margin_free < 0:
            raise ValueError('MT5 returned invalid available free margin; no order submitted')
        margin_required = self.mt5.order_calc_margin(side, symbol, volume, price)
        if margin_required is None or not math.isfinite(margin_required) or margin_required < 0:
            raise ValueError('MT5 could not calculate required margin; no order submitted')
        if margin_required > margin_free:
            self.state["message"] = "Skipped: broker margin requirement exceeds available free margin"
            self.record("skipped", {"reason": self.state["message"],
                                    "required_margin": margin_required, "free_margin": margin_free})
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
        evidence = self._research_candidate()
        self.record("order_result", {**(result._asdict() if result else {"error": str(self.mt5.last_error())}),
                                     'symbol': symbol, 'research_run_id': evidence.get('run_id') if evidence else None,
                                     'strategy': self.config.model_dump(),
                                     'accepted': bool(result and result.retcode in (
                                         self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_DONE_PARTIAL))})
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
