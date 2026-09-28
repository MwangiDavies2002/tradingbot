"""Read-only forward scanner and durable hypothetical signal ledger.

No method in this module submits or approves broker orders.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
import hashlib
import json
import math
import os
import sqlite3
import threading
import time
import uuid
from typing import Literal

from pydantic import Field, model_validator
from app.quant.schemas import Record, Bar
from app.quant.scanner_sessions import ScanCalendar
from app.quant.scanner_mappings import MappingCatalog, check_mapping
from app.quant.scanner_spreads import capture_spread, candle_spread
from app.execution.mt5_demo import DemoConfig
from app.core.engine.signal_engine import EngineConfig, SignalEngine
from app.core.lsl.lsl_detector import Candle


PAPER_MODEL = 'tick_grid_v2'


def paper_tick(instrument):
    """Use the captured contract grid; display digits are not a tick size."""
    try:
        tick = Decimal(str(instrument.get('trade_tick_size')))
    except (InvalidOperation, ValueError):
        raise ValueError('Paper entry requires a positive finite broker tick size') from None
    if not tick.is_finite() or tick <= 0:
        raise ValueError('Paper entry requires a positive finite broker tick size')
    return tick


def grid_price(value, tick, up):
    return (value / tick).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * tick


def grid_entry(p, opening, spread_override=None):
    tick = paper_tick(p['instrument'])
    buy = p['direction'] == 'buy'
    price, spread, slip, risk = map(Decimal, map(str, (opening, p['spread'] if spread_override is None else spread_override, p['slippage'], p['risk_distance'])))
    entry = grid_price(price + (spread + slip if buy else -slip), tick, buy)
    stop = grid_price(entry + (-risk if buy else risk), tick, not buy)
    risk = abs(entry - stop)
    target = entry + (2 * risk if buy else -2 * risk)
    if min(entry, stop, target) <= 0 or risk <= 0:
        raise ValueError('Tick-aligned paper levels must be positive with nonzero risk')
    p.update(entry=float(entry), stop=float(stop), target=float(target),
             requested_risk_distance=p['risk_distance'], risk_distance=float(risk))


class ScanAsset(Record):
    symbol: str = Field(min_length=1, max_length=128, pattern=r'^[^\x00-\x1f\x7f]+$')
    label: str = Field(default='', max_length=128)
    calendar: ScanCalendar | None = None
    mapping_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def exact(self):
        if self.symbol != self.symbol.strip():
            raise ValueError('Use an exact broker symbol')
        if self.calendar and self.calendar.symbol != self.symbol:
            raise ValueError('Session calendar must name the exact selected symbol')
        return self


class ScanConfig(Record):
    assets: list[ScanAsset] = Field(min_length=1, max_length=8)
    timeframe: str = Field(default='M5', pattern=r'^(M1|M5|M15|M30|H1|H4)$')
    poll_seconds: int = Field(default=30, ge=15, le=300)
    threshold: int = Field(default=6, ge=1, le=20)
    max_spread_atr: float = Field(default=.2, gt=0, le=1)
    slippage_atr: float = Field(default=.02, ge=0, le=.5)
    max_hold_bars: int = Field(default=12, ge=1, le=100)
    spread_model: Literal['fixed_quote', 'candle_proxy_v1'] = 'fixed_quote'
    strategy_mode: Literal['manual', 'research_candidate'] = 'manual'
    strategy: DemoConfig | None = None
    research_run_id: str | None = None
    candidate_snapshot: dict | None = None

    @model_validator(mode='after')
    def unique(self):
        if len({a.symbol for a in self.assets}) != len(self.assets):
            raise ValueError('Select unique broker symbols')
        for asset in self.assets:
            if asset.calendar:
                asset.calendar.check_grid(self.interval)
        if self.strategy_mode == 'research_candidate':
            if len(self.assets) != 1:
                raise ValueError('A validated research scan requires exactly one broker pair')
        elif self.strategy is not None or self.research_run_id is not None or self.candidate_snapshot is not None:
            raise ValueError('Manual scanner settings cannot assert research-candidate evidence')
        return self

    @property
    def interval(self):
        return int(self.timeframe[1:]) * (60 if self.timeframe[0] == 'M' else 3600)


def instrument_metadata(account, info, symbol):
    def value(obj, name):
        item = getattr(obj, name, None)
        if isinstance(item, str) or (isinstance(item, (int, float)) and math.isfinite(item)):
            return item
        return None
    instrument = {'provider': 'mt5', 'server': account.server, 'account': account.login,
                  'symbol': symbol, 'price_basis': 'bid' if value(info, 'chart_mode') == 0 else 'unknown_or_last', 'captured_at': time.time(),
                  'account_currency': value(account, 'currency'),
                  **{name: value(info, name) for name in (
                      'currency_base', 'currency_profit', 'trade_calc_mode',
                      'trade_contract_size', 'trade_tick_size', 'digits', 'point', 'chart_mode',
                      'volume_min', 'volume_max', 'volume_step')}}
    instrument['identity'] = hashlib.sha256(json.dumps(
        ['mt5', account.server, account.login, symbol]).encode()).hexdigest()
    return instrument


def candidate_contract(snapshot, instrument, scope):
    if scope != f'{snapshot["server"]}:{snapshot["account"]}':
        raise ValueError('Research candidate belongs to a different demo account/server')
    for contract_field, instrument_field in (
        ('contract_size', 'trade_contract_size'), ('tick_size', 'trade_tick_size'),
        ('volume_min', 'volume_min'), ('volume_step', 'volume_step'), ('volume_max', 'volume_max')
    ):
        if instrument.get(instrument_field) != snapshot.get(contract_field):
            raise ValueError(f'Research candidate broker contract changed: {instrument_field}')


def snapshot(runner, symbol, config):
    with runner.lock:
        account, _, _ = runner._require_connection()
        info = runner._symbol_info(symbol)
        tick = runner.mt5.symbol_info_tick(symbol)
        if tick is None:
            raise ValueError('Quote unavailable')
        rates = runner.mt5.copy_rates_from_pos(symbol, getattr(runner.mt5, 'TIMEFRAME_' + config.timeframe), 1, 500)
        if rates is None:
            raise ValueError('Candle history unavailable')
        instrument = instrument_metadata(account, info, symbol)
        return {'instrument': instrument, 'scope': f'{account.server}:{account.login}', 'balance': getattr(account, 'balance', 10000),
                'bid': tick.bid, 'ask': tick.ask,
                'spread_observations': {int(r['time']): capture_spread(r, instrument, config.timeframe) for r in rates},
                'quote_time': tick.time, 'bars': [dict(timestamp=int(r['time']), open=float(r['open']),
                high=float(r['high']), low=float(r['low']), close=float(r['close']),
                volume=float(r['tick_volume'])) for r in rates]}


def closed_bars(data, config, now):
    bars = [Bar.model_validate(b) for b in data['bars']]
    if any(b.low > min(b.open, b.close) or b.high < max(b.open, b.close) or b.low > b.high for b in bars):
        raise ValueError('Invalid OHLC candle')
    if any(b.timestamp <= a.timestamp for a, b in zip(bars, bars[1:])):
        raise ValueError('Candles must have unique ascending timestamps')
    if bars and bars[-1].timestamp + config.interval > now:
        raise ValueError('Forming/future candle rejected')
    return bars


def evaluate(data, config, symbol, now):
    bars = closed_bars(data, config, now)
    if len(bars) < 100:
        raise ValueError('At least 100 closed candles required')
    if now - bars[-1].timestamp > config.interval * 2 + 30:
        raise ValueError('Stale candle history or closed session')
    calendar = next(a.calendar for a in config.assets if a.symbol == symbol)
    if calendar:
        calendar.check_identity(data['scope'], symbol, now)
        if not any(w.open <= now < w.close for w in calendar.windows):
            raise ValueError('Current time is outside supplied open sessions')
        calendar.check_history(bars, config.interval)
    elif any(b.timestamp-a.timestamp != config.interval for a, b in zip(bars[-21:], bars[-20:])):
        raise ValueError('Recent candle gap; session-aware continuity not confirmed')
    bid, ask = data['bid'], data['ask']
    if not all(math.isfinite(v) and v > 0 for v in (bid, ask, data['quote_time'])) or ask < bid or abs(now-data['quote_time']) > 30:
        raise ValueError('Invalid or stale bid/ask quote')
    candles = [Candle(**b.model_dump(exclude={'spread'})) for b in bars]
    if config.strategy_mode == 'research_candidate' and config.strategy is None:
        raise ValueError('Validated research strategy must be loaded by the scanner server')
    settings = (config.strategy.model_dump(exclude={'symbol', 'timeframe', 'daily_loss_pct'})
                if config.strategy_mode == 'research_candidate' and config.strategy else
                {'min_confluence': config.threshold, 'use_hurst': False})
    engine = SignalEngine(EngineConfig(**settings))
    engine.initialise(data.get('balance', 10000))
    result = engine.evaluate(candles, symbol=symbol, timeframe=config.timeframe)
    atr = engine.atr_ind.compute(candles)
    hurst = engine.hurst_ind.compute(candles)
    z = engine.zscore.compute(candles)
    if not atr or not math.isfinite(atr.value) or atr.value <= 0:
        raise ValueError('ATR unavailable')
    h = hurst.value if hurst and math.isfinite(hurst.value) else None
    spread = ask - bid
    drift = abs(bars[-1].close-bars[-20].close) / atr.value
    flat = len({b.close for b in bars[-10:]}) == 1
    regime = ('LOW_LIQUIDITY' if flat or spread/atr.value > config.max_spread_atr else
              'HIGH_VOLATILITY' if atr.is_spike else
              'TREND' if drift >= 3 or (h is not None and h > .55) else
              'RANGE' if h is not None and h < .45 else 'UNCERTAIN')
    reasons = [result.reason]
    if regime != 'RANGE':
        reasons.append(f'Mean-reversion paper gate blocks {regime}')
    eligible = regime == 'RANGE' and result.should_trade and result.direction in ('buy', 'sell')
    return dict(bar=bars[-1].timestamp, direction=result.direction, raw_score=result.confluence_score,
                score=round(min(100, result.confluence_score/20*100), 1),
                deviation=z.value if z and math.isfinite(z.value) else None,
                hurst=h, atr=atr.value, trend_atr=drift, spread=spread, regime=regime,
                volatility='high' if atr.is_spike else 'normal', news='unknown',
                session=f'UTC {datetime.fromtimestamp(now, timezone.utc).hour//6*6:02d}-{datetime.fromtimestamp(now, timezone.utc).hour//6*6+6:02d}',
                setup='mean_reversion_v1', reasons=reasons, eligible=eligible)


class Scanner:
    def __init__(self, path=None, loader=snapshot, evaluator=evaluate):
        self.path = Path(path or Path(__file__).resolve().parents[2] / 'data' / 'scanner.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.loader, self.evaluator = loader, evaluator
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker = None
        self.handle = None
        with self.db() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS scans(id TEXT PRIMARY KEY, created REAL, status TEXT, config TEXT, role TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY, run_id TEXT, symbol TEXT, bar INTEGER, observed REAL, payload TEXT);
                CREATE INDEX IF NOT EXISTS obs_run ON observations(run_id, observed);
                CREATE TABLE IF NOT EXISTS latest(symbol TEXT PRIMARY KEY, payload TEXT);
                CREATE TABLE IF NOT EXISTS stop_requests(run_id TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS paper(id TEXT PRIMARY KEY, run_id TEXT, symbol TEXT, state TEXT, payload TEXT);
                CREATE TABLE IF NOT EXISTS instrument_mappings(
                    id TEXT PRIMARY KEY, server TEXT, account INTEGER, symbol TEXT, revision TEXT,
                    registered_at REAL, payload TEXT, UNIQUE(server,account,symbol,revision));
            ''')
        self.mappings = MappingCatalog(self.db)

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=15)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def acquire(self):
        handle = open(self.path.with_suffix('.lock'), 'a+b')
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            handle.close()
            raise ValueError('A scanner is already running')

    def start(self, config, runner, role):
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError('Stop the scanner before changing its selection')
            handle = self.acquire()
            try:
                with runner.lock:
                    account, _, _ = runner._require_connection()
                    scope = f'{account.server}:{account.login}'
                    if config.strategy_mode == 'research_candidate':
                        evidence = runner._research_candidate()
                        age = time.time() - evidence.get('validated_at', 0) if evidence else float('inf')
                        if not 0 <= age <= 7 * 86400:
                            raise ValueError('Load a passing research candidate from the last seven days')
                        strategy = DemoConfig.model_validate(evidence['strategy'])
                        if (strategy.symbol != config.assets[0].symbol or strategy.timeframe != config.timeframe
                                or strategy.min_confluence != config.threshold or runner.config != strategy):
                            raise ValueError('Selected pair, timeframe or threshold differs from the loaded research strategy')
                        config.strategy = strategy
                        config.research_run_id = evidence['run_id']
                        config.candidate_snapshot = evidence['snapshot']
                        if runner.state['running']:
                            raise ValueError('Stop demo execution before starting a validated research scan')
                    for asset in config.assets:
                        info = runner._symbol_info(asset.symbol)
                        if config.strategy_mode == 'research_candidate':
                            candidate_contract(config.candidate_snapshot, instrument_metadata(account, info, asset.symbol), scope)
                        if asset.mapping_id:
                            check_mapping(self.mappings.get(asset.mapping_id), instrument_metadata(account, info, asset.symbol), time.time())
                        if asset.calendar:
                            asset.calendar.check_identity(scope, asset.symbol, time.time())
                run = str(uuid.uuid4())
                with self.db() as db:
                    db.execute("UPDATE scans SET status='interrupted' WHERE status='running'")
                    # Never manufacture outcomes for exposure abandoned by a stopped/restarted run.
                    db.execute("UPDATE paper SET state='unresolved' WHERE state IN ('pending','open')")
                    db.execute('DELETE FROM latest')
                    db.execute('INSERT INTO scans VALUES(?,?,?,?,?,?)', (run, time.time(), 'running', config.model_dump_json(), role, None))
                self.stop_event.clear()
                self.handle = handle
                self.worker = threading.Thread(target=self._run, args=(run, config, runner, scope), daemon=True)
                self.worker.start()
            except Exception:
                handle.close()
                raise
        return self.status()

    def stop(self):
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO stop_requests SELECT id FROM scans WHERE status='running'")
        self.stop_event.set()
        worker = self.worker
        if worker:
            worker.join(timeout=5)
        return self.status()

    def stopping(self, run):
        if self.stop_event.is_set():
            return True
        with self.db() as db:
            return db.execute('SELECT 1 FROM stop_requests WHERE run_id=?', (run,)).fetchone() is not None

    def _run(self, run, config, runner, scope):
        failure = None
        try:
            while not self.stopping(run):
                self.cycle(run, config, runner, scope)
                self.stop_event.wait(config.poll_seconds)
        except Exception as exc:
            failure = str(exc)
        finally:
            try:
                with self.db() as db:
                    db.execute('UPDATE scans SET status=?, error=? WHERE id=?', ('failed' if failure else 'stopped', failure, run))
                    db.execute("UPDATE paper SET state='unresolved' WHERE run_id=? AND state IN ('pending','open')", (run,))
            finally:
                self.handle.close()
                self.handle = None

    def cycle(self, run, config, runner, scope):
        for asset in config.assets:
            if self.stopping(run):
                break
            now = time.time()
            try:
                data = self.loader(runner, asset.symbol, config)
                if data['scope'] != scope:
                    raise ValueError('Connected MT5 account changed; stop and start a new scan')
                if config.strategy_mode == 'research_candidate':
                    try:
                        candidate_contract(config.candidate_snapshot, data.get('instrument', {}), data['scope'])
                    except ValueError as exc:
                        self.unresolve(run, asset.symbol, f'Research contract rejected: {exc}')
                        raise
                mapping = None
                if asset.mapping_id:
                    try:
                        mapping = self.mappings.get(asset.mapping_id)
                        check_mapping(mapping, data.get('instrument', {}), now)
                    except (KeyError, ValueError) as exc:
                        self.unresolve(run, asset.symbol, f'Instrument mapping rejected: {exc}')
                        raise
                # Resolve validated closed history even when fresh-entry gates reject
                # a missing candle, closed session, stale quote or expired calendar.
                closed_bars(data, config, now)
                self.resolve(run, asset.symbol, data['bars'], config, now=now, spread_observations=data.get('spread_observations'))
                if asset.calendar:
                    asset.calendar.check_identity(scope, asset.symbol, now)
                result = self.evaluator(data, config, asset.symbol, now)
                result.update(symbol=asset.symbol, label=asset.label or asset.symbol, provider='mt5', scope=scope,
                              timeframe=config.timeframe, observed=now, run_id=run)
                policy_data = config.model_dump(exclude={'assets', 'poll_seconds', 'strategy_mode', 'strategy', 'research_run_id', 'candidate_snapshot'}) | {'paper_model': PAPER_MODEL}
                if config.strategy_mode == 'research_candidate':
                    policy_data.update(strategy_mode='research_candidate', strategy=config.strategy.model_dump(),
                                       research_run_id=config.research_run_id, candidate_snapshot=config.candidate_snapshot)
                if config.spread_model == 'fixed_quote':
                    policy_data.pop('spread_model')  # Preserve existing fixed-model policy IDs.
                if asset.calendar:
                    policy_data.update(calendar=asset.calendar.model_dump(), continuity_model='explicit_utc_v1')
                if mapping:
                    policy_data.update(mapping_id=mapping['id'], instrument_model='catalog_mapping_v1')
                policy = json.dumps(policy_data, sort_keys=True)
                key = hashlib.sha256(f'{scope}:{asset.symbol}:{config.timeframe}:{result["bar"]}:{policy}'.encode()).hexdigest()
                result.update(id=key, policy_id=hashlib.sha256(policy.encode()).hexdigest(),
                              policy=json.loads(policy), scanner_version='mr_v2', paper_model=PAPER_MODEL,
                              instrument=data.get('instrument', {'provider': 'mt5', 'scope': scope, 'symbol': asset.symbol}))
                if mapping:
                    result['catalog_mapping'] = mapping
                result['spread_model'] = config.spread_model
                result['strategy_mode'] = config.strategy_mode
                result['spread_observation'] = data.get('spread_observations', {}).get(result['bar'])
                try:
                    paper_tick(result['instrument'])
                    if config.spread_model == 'candle_proxy_v1':
                        candle_spread(result['spread_observation'], result, result['bar'])
                    enter_after = (int(now)//config.interval+1)*config.interval
                    if asset.calendar:
                        enter_after = asset.calendar.next_bar(enter_after, config.interval)
                except ValueError as exc:
                    result['eligible'] = False
                    result['reasons'].append(str(exc))
                with self.db() as db:
                    exists = db.execute("SELECT 1 FROM paper WHERE run_id=? AND symbol=? AND state IN ('pending','open')", (run, asset.symbol)).fetchone()
                    if result['eligible'] and exists:
                        result['reasons'].append('Existing hypothetical exposure; no additional entry')
                    inserted = db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?)',
                        (key, run, asset.symbol, result['bar'], now, json.dumps(result, allow_nan=False))).rowcount
                    db.execute('INSERT OR REPLACE INTO latest VALUES(?,?)', (asset.symbol, json.dumps(result, allow_nan=False)))
                    if inserted and result['eligible']:
                        exists = db.execute("SELECT 1 FROM paper WHERE run_id=? AND symbol=? AND state IN ('pending','open')", (run, asset.symbol)).fetchone()
                        if not exists:
                            paper = {**result, 'enter_after': enter_after,
                                     'risk_distance': result['atr']*1.5, 'slippage': result['atr']*config.slippage_atr,
                                     'last_bar': result['bar'], 'bars_held': 0, 'r_multiple': None}
                            db.execute('INSERT INTO paper VALUES(?,?,?,?,?)', (key, run, asset.symbol, 'pending', json.dumps(paper)))
            except Exception as exc:
                payload = dict(symbol=asset.symbol, label=asset.label or asset.symbol, provider='mt5', scope=scope,
                               timeframe=config.timeframe, run_id=run, observed=now, regime='UNKNOWN', eligible=False,
                               reasons=[str(exc)], news='unknown', error=True,
                               calendar=asset.calendar.model_dump() if asset.calendar else None,
                               mapping_id=asset.mapping_id)
                key = hashlib.sha256(f'{run}:{asset.symbol}:error:{int(now)//config.interval}'.encode()).hexdigest()
                with self.db() as db:
                    db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?)', (key, run, asset.symbol, None, now, json.dumps(payload)))
                    db.execute('INSERT OR REPLACE INTO latest VALUES(?,?)', (asset.symbol, json.dumps(payload)))

    def unresolve(self, run, symbol, reason):
        with self.db() as db:
            rows = db.execute("SELECT id,payload FROM paper WHERE run_id=? AND symbol=? AND state IN ('pending','open')", (run, symbol)).fetchall()
            for key, raw in rows:
                payload = json.loads(raw) | {'exit_reason': reason}
                db.execute("UPDATE paper SET state='unresolved',payload=? WHERE id=?", (json.dumps(payload, allow_nan=False), key))

    def resolve(self, run, symbol, bars, config, now=None, spread_observations=None):
        with self.db() as db:
            rows = db.execute("SELECT id,state,payload FROM paper WHERE run_id=? AND symbol=? AND state IN ('pending','open')", (run, symbol)).fetchall()
            for key, state, raw in rows:
                p = json.loads(raw)
                calendar_data = p.get('policy', {}).get('calendar')
                calendar = ScanCalendar.model_validate(calendar_data) if calendar_data else None
                for b in bars:
                    ts = b['timestamp']
                    if ts <= p['last_bar'] or ts < p['enter_after']:
                        continue
                    expected = p['enter_after'] if state == 'pending' else p['last_bar'] + config.interval
                    if calendar:
                        try:
                            expected = calendar.next_bar(expected, config.interval)
                            if not calendar.contains(ts, config.interval):
                                raise ValueError('Outcome candle outside supplied sessions or coverage')
                        except ValueError as exc:
                            state = 'unresolved'; p['exit_reason'] = str(exc); break
                    if ts != expected:
                        state = 'unresolved'; p['exit_reason'] = 'Missing outcome candles'; break
                    buy = p['direction'] == 'buy'
                    spread, slip, risk = p['spread'], p['slippage'], p['risk_distance']
                    if p.get('spread_model') == 'candle_proxy_v1':
                        evidence = (spread_observations or {}).get(ts)
                        try:
                            spread = candle_spread(evidence, p, ts)
                        except ValueError as exc:
                            state = 'unresolved'; p['exit_reason'] = str(exc)
                            p['missing_spread_bar'] = ts
                            p['rejected_spread_observation'] = evidence
                            break
                        p.setdefault('spread_history', []).append(evidence)
                    if state == 'pending':
                        if p.get('paper_model') == PAPER_MODEL:
                            try:
                                grid_entry(p, b['open'], spread)
                            except ValueError as exc:
                                state = 'unresolved'; p['exit_reason'] = str(exc); break
                            risk = p['risk_distance']
                        else:
                            # Retain the original simulation for historical pending records.
                            p['entry'] = b['open'] + (spread + slip if buy else -slip)
                            p['stop'] = p['entry'] + (-risk if buy else risk)
                            p['target'] = p['entry'] + (2*risk if buy else -2*risk)
                        p['entry_time'] = ts
                        if p.get('spread_model') == 'candle_proxy_v1':
                            p['entry_spread'] = spread
                        state = 'open'
                    # Bid OHLC + selected fixed or candle spread is only an ask proxy.
                    high, low, opening, close = (b[k] + (0 if buy else spread) for k in ('high','low','open','close'))
                    hit_stop = low <= p['stop'] if buy else high >= p['stop']
                    hit_target = high >= p['target'] if buy else low <= p['target']
                    p['bars_held'] += 1
                    p['last_bar'] = ts
                    exit_price = None
                    if hit_stop:
                        exit_price = min(opening, p['stop']) if buy else max(opening, p['stop'])
                        p['exit_reason'] = 'stop_first_ambiguous' if hit_target else 'stop'
                    elif hit_target:
                        exit_price = p['target']; p['exit_reason'] = 'target'
                    elif p['bars_held'] >= config.max_hold_bars:
                        exit_price = close; p['exit_reason'] = 'time_limit'
                    if exit_price is not None:
                        if p.get('spread_model') == 'candle_proxy_v1':
                            p['exit_spread'] = spread
                        if p.get('paper_model') == PAPER_MODEL:
                            price = Decimal(str(exit_price)) + Decimal(str(-slip if buy else slip))
                            p['exit'] = float(grid_price(price, paper_tick(p['instrument']), not buy))
                            if p['exit'] <= 0:
                                state = 'unresolved'; p['exit_reason'] = 'Nonpositive tick-aligned exit'; break
                        else:
                            p['exit'] = exit_price + (-slip if buy else slip)
                        p['r_multiple'] = (p['exit']-p['entry'])/risk * (1 if buy else -1)
                        p['exit_time'] = ts + config.interval
                        state = 'closed'; break
                if calendar and now is not None and now >= calendar.valid_until and state in ('pending', 'open'):
                    state = 'unresolved'; p['exit_reason'] = 'Session calendar coverage expired before outcome'
                db.execute('UPDATE paper SET state=?,payload=? WHERE id=?', (state, json.dumps(p, allow_nan=False), key))

    def status(self):
        with self.db() as db:
            run = db.execute('SELECT id,created,status,config,role,error FROM scans ORDER BY created DESC LIMIT 1').fetchone()
            latest = [json.loads(row[0]) for row in db.execute('SELECT payload FROM latest ORDER BY symbol')]
        # Report restart interruption without implicitly restarting observation.
        if run and run[2] == 'running' and not (self.worker and self.worker.is_alive()):
            try:
                handle = self.acquire()
            except ValueError:
                pass
            else:
                with self.db() as db:
                    db.execute("UPDATE scans SET status='interrupted' WHERE id=?", (run[0],))
                    db.execute("UPDATE paper SET state='unresolved' WHERE run_id=? AND state IN ('pending','open')", (run[0],))
                handle.close()
                run = (*run[:2], 'interrupted', *run[3:])
        return {'run': dict(zip(('id','created','status','config','role','error'), run)) | {'config': json.loads(run[3])} if run else None,
                'latest': latest, 'execution_enabled': False}

    def ledger(self, limit=500):
        with self.db() as db:
            observations = [json.loads(row[0]) for row in db.execute('SELECT payload FROM observations ORDER BY observed DESC LIMIT ?', (limit,))]
            trades = [json.loads(row[1]) | {'state': row[0]} for row in db.execute('SELECT state,payload FROM paper ORDER BY rowid DESC LIMIT ?', (limit,))]
        return {'observations': observations, 'trades': trades}

    def records(self, kind='observations', limit=50, before=None, through=None):
        if kind not in ('observations', 'trades') or not 1 <= limit <= 200:
            raise ValueError('Choose observations or trades and a page size from 1 to 200')
        if any(v is not None and v < 0 for v in (before, through)):
            raise ValueError('Cursors must be nonnegative')
        table = 'observations' if kind == 'observations' else 'paper'
        with self.db() as db:
            db.execute('BEGIN')
            maximum = db.execute(f'SELECT COALESCE(MAX(rowid),0) FROM {table}').fetchone()[0]
            ceiling = min(through, maximum) if through is not None else maximum
            cursor = min(before, ceiling + 1) if before is not None else ceiling + 1
            columns = 'rowid,payload,id' if kind == 'observations' else 'rowid,payload,state,id'
            rows = db.execute(f'SELECT {columns} FROM {table} WHERE rowid<=? AND rowid<? ORDER BY rowid DESC LIMIT ?',
                              (ceiling, cursor, limit+1)).fetchall()
            total = db.execute(f'SELECT COUNT(*) FROM {table} WHERE rowid<=?', (ceiling,)).fetchone()[0]
        items = [json.loads(r[1]) | {'record_cursor': r[0], 'id': r[-1]} | ({'state': r[2]} if kind == 'trades' else {}) for r in rows[:limit]]
        return {'kind': kind, 'items': items, 'total': total, 'through': ceiling,
                'next_before': rows[limit-1][0] if len(rows)>limit else None}

    def export(self):
        # A WAL read transaction gives one consistent export while scanning continues.
        # Yield rows individually: do not materialize an unbounded journal in RAM.
        with self.db() as db:
            db.execute('BEGIN')
            db.execute('SELECT COUNT(*) FROM scans').fetchone()  # Establish snapshot.
            yield '{"schema_version":1,"execution_enabled":false,"exported_at":' + str(time.time())
            yield ',"runs":['
            separator = ''
            for row in db.execute('SELECT id,created,status,config,role,error FROM scans ORDER BY created,id'):
                value = dict(zip(('id','created','status','config','role','error'), row))
                value['config'] = json.loads(value['config'])
                yield separator + json.dumps(value, allow_nan=False)
                separator = ','
            for key, sql in [('observations', 'SELECT payload,id FROM observations ORDER BY rowid'),
                             ('trades', 'SELECT payload,state,id FROM paper ORDER BY rowid'),
                             ('mappings', 'SELECT payload,id FROM instrument_mappings ORDER BY rowid')]:
                yield '],"' + key + '":['
                separator = ''
                for row in db.execute(sql):
                    value = json.loads(row[0])
                    value['id'] = row[-1]
                    if key == 'trades':
                        value['state'] = row[1]
                    yield separator + json.dumps(value, allow_nan=False)
                    separator = ','
            yield ']}'

    def analytics(self):
        with self.db() as db:
            trades = [json.loads(row[1]) | {'state': row[0]} for row in db.execute('SELECT state,payload FROM paper')]
            signal_groups = db.execute('''
                SELECT COALESCE(json_extract(payload,'$.scope'),'legacy_unknown'),
                       symbol,
                       COALESCE(json_extract(payload,'$.timeframe'),'legacy_unknown'),
                       COALESCE(json_extract(payload,'$.policy_id'),'legacy_unknown'),
                       COUNT(*), MAX(observed), GROUP_CONCAT(DISTINCT run_id),
                       MAX(json_extract(payload,'$.policy.research_run_id'))
                FROM observations GROUP BY 1,2,3,4
            ''').fetchall()
            observations = db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
            counts = dict(db.execute('SELECT state,count(*) FROM paper GROUP BY state'))
        rows = [p for p in trades if p['state'] == 'closed']
        def summary(items):
            values = [p['r_multiple'] for p in items]
            return {'count': len(values), 'mean_r': sum(values)/len(values) if values else None,
                    'win_rate': sum(v>0 for v in values)/len(values) if values else None,
                    'sample': 'exploratory' if len(values)<300 else 'review_required'}
        groups = {}
        for field in ('symbol', 'scope', 'policy_id', 'regime', 'session', 'setup', 'volatility', 'news', 'score_bucket'):
            bucket = {}
            for p in rows:
                key = str(min(9, int(p['score'])//10)*10) + '-' + str(min(100, min(9, int(p['score'])//10)*10+10)) if field == 'score_bucket' else p.get(field, 'legacy_unknown')
                bucket.setdefault(key, []).append(p)
            groups[field] = {k: summary(v) for k,v in bucket.items()}
        def series_key(record):
            return (record.get('scope') or 'legacy_unknown', record.get('symbol') or 'legacy_unknown',
                    record.get('timeframe') or 'legacy_unknown', record.get('policy_id') or 'legacy_unknown')
        series = {}
        for scope, symbol, timeframe, policy_id, count, latest, run_ids, research_run_id in signal_groups:
            key = (scope, symbol, timeframe, policy_id)
            item = series.setdefault(key, {'trades': [], 'observations': 0, 'states': {}, 'run_ids': set(),
                                           'latest_observed': 0, 'research_run_id': None})
            item['observations'] = count
            item['latest_observed'] = latest or 0
            item['run_ids'].update(run_ids.split(',') if run_ids else [])
            item['research_run_id'] = research_run_id
        for record in trades:
            key = series_key(record)
            item = series.setdefault(key, {'trades': [], 'observations': 0, 'states': {}, 'run_ids': set(),
                                           'latest_observed': 0, 'research_run_id': None})
            item['trades'].append(record)
            state = record['state']
            item['states'][state] = item['states'].get(state, 0) + 1
            item['latest_observed'] = max(item['latest_observed'], record.get('observed') or 0)
            if record.get('run_id'):
                item['run_ids'].add(record['run_id'])
            item['research_run_id'] = (record.get('policy') or {}).get('research_run_id') or item['research_run_id']
        per_pair = [dict(scope=scope, symbol=symbol, timeframe=timeframe, policy_id=policy_id,
                         research_run_id=item['research_run_id'], run_ids=sorted(item['run_ids']),
                         latest_observed=item['latest_observed'], observations=item['observations'],
                         states=item['states'], **summary([p for p in item['trades'] if p['state'] == 'closed']))
                    for (scope, symbol, timeframe, policy_id), item in series.items()]
        per_pair.sort(key=lambda item: (-item['latest_observed'], item['scope'], item['symbol'], item['policy_id']))
        return {'overall': summary(rows), 'groups': groups, 'per_pair_policy': per_pair,
                'states': counts, 'observations': observations,
                'model': 'Spread follows each pinned policy: fixed observed quote or historical candle proxy (never executable ask history). Configured ATR slippage; new tick_grid_v2 records round fills adversely to the captured broker tick, with outward stops and 2R targets. R uses rounded stop distance. Older policies retain their original model. No commission/financing. R units, not account-currency P&L. News unknown. No execution authorization.'}
