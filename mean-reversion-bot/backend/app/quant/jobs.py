"""Durable local research jobs. One worker; never invokes execution controls."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from app.quant.schemas import (InstrumentIdentity, RiskConfiguration, ResearchConfiguration,
                               StrategyDefinition)
from app.quant.sources import load_asset
from app.quant.statistics import audit, market_behavior, relationships
from app.quant.validation import validate_strategy
from app.quant.instruments import configuration_fingerprint, timeframe_seconds
from app.quant.strategy_identity import EXECUTION_STRATEGY_NAME, EXECUTION_STRATEGY_VERSION


class ResearchCancelled(Exception):
    pass


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


class AnalysisJobs:
    def __init__(self, path=None, loader=load_asset, validator=validate_strategy):
        self.path = Path(path or Path(__file__).resolve().parents[2] / 'data' / 'analysis.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.loader, self.validator = loader, validator
        self.lock = threading.RLock()
        self.worker = None
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, created REAL, updated REAL, status TEXT, stage TEXT, progress REAL, input TEXT, report TEXT, artifacts TEXT, cancel INTEGER DEFAULT 0)')

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=15)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def process_lock(self):
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
            raise ValueError('An analysis is already running; wait or cancel it first')

    def recover(self):
        # A process lock proves no other worker owns the pending jobs.
        try:
            handle = self.process_lock()
        except ValueError:
            return
        try:
            with self.db() as db:
                db.execute("UPDATE analyses SET status='interrupted', stage='Backend stopped before completion; create a new analysis', updated=? WHERE status='running'", (time.time(),))
        finally:
            handle.close()

    def create(self, body, runner=None):
        with self.lock:
            handle = self.process_lock()
            run_id = str(uuid.uuid4())
            try:
                with self.db() as db:
                    db.execute("UPDATE analyses SET status='interrupted', stage='Backend stopped before completion' WHERE status='running'")
                    db.execute('INSERT INTO analyses(id,created,updated,status,stage,progress,input,report,artifacts) VALUES(?,?,?,?,?,?,?,?,?)',
                               (run_id,time.time(),time.time(),'running','Queued',0,body.model_dump_json(),'{}','{}'))
                self.worker = threading.Thread(target=self._run, args=(run_id,body,runner,handle), daemon=True, name='offline-analysis')
                self.worker.start()
            except BaseException:
                handle.close()
                raise
            return self.get(run_id)

    def update(self, run_id, stage, progress, report=None, artifacts=None, status='running'):
        with self.db() as db:
            row = db.execute('SELECT cancel FROM analyses WHERE id=?', (run_id,)).fetchone()
            if status == 'running' and row and row[0]:
                raise ResearchCancelled()
            db.execute('UPDATE analyses SET updated=?,status=?,stage=?,progress=? WHERE id=?',
                       (time.time(),status,stage,progress,run_id))
            if report is not None:
                db.execute('UPDATE analyses SET report=? WHERE id=?', (json.dumps(report, allow_nan=False),run_id))
            if artifacts is not None:
                db.execute('UPDATE analyses SET artifacts=? WHERE id=?', (json.dumps(artifacts, allow_nan=False),run_id))

    def _run(self, run_id, request, runner, handle):
        report = {'assets': {}, 'relationships': None, 'candidates': [], 'live_authorized': False,
                  'method_version': 'quant-workflow-v1', 'source': request.source,
                  'timeframe': request.timeframe, 'days': request.days,
                  'strategy_name': request.strategy_name, 'strategy_version': request.strategy_version,
                  'implementation_hash': fingerprint({p.name: p.read_text(encoding='utf-8') for p in Path(__file__).parent.glob('*.py')})}
        artifacts, series, exposures, timeframes = {}, {}, dict(request.exposures), {}
        try:
            for index, asset in enumerate(request.assets):
                symbol = asset.symbol
                try:
                    timeframe = asset.timeframe or request.timeframe
                    strategy = request.strategy.model_copy(update={'symbol': symbol, 'timeframe': timeframe})
                    asset_request = request.model_copy(update={
                        'assets': [asset], 'timeframe': timeframe, 'strategy': strategy})
                    interval = asset_request.interval
                    end = int(time.time() // interval) * interval
                    start = end - request.days * 86400
                    self.update(run_id, f'{symbol}: ingest and audit', index/len(request.assets)*.85, report)
                    bars, profile, snapshot, exposure = self.loader(asset, asset_request, runner, start, end)
                    if not bars or len(bars)>10000:
                        raise ValueError('Supply 100–10,000 candles per asset')
                    audit_start = (bars[0].timestamp if request.source == 'import'
                                   else snapshot.get('history_start', start))
                    audit_end = (bars[-1].timestamp+interval if request.source == 'import'
                                 else snapshot.get('history_end', end))
                    quality = audit(bars, interval, profile.session, audit_start, audit_end)
                    behavior = market_behavior(bars, interval, profile.annualization)
                    series[symbol] = bars
                    timeframes[symbol] = timeframe
                    if request.source == 'mt5':
                        exposures[symbol] = exposure
                    artifacts[symbol] = {'bars': [b.model_dump() for b in bars], 'profile': profile.model_dump(mode='json'), 'snapshot': snapshot}
                    data_hash = fingerprint(artifacts[symbol])
                    row = {'status': 'analyzing', 'timeframe': timeframe,
                           'asset_class': profile.asset_class, 'quality': quality,
                           'market_behavior': behavior, 'snapshot': snapshot,
                           'data_hash': data_hash, 'costs_confirmed': profile.costs_confirmed,
                           'specification_confirmed': profile.specification_confirmed,
                           'slippage_confirmed': profile.slippage_confirmed}
                    report['assets'][symbol] = row
                    # Correlation survives cost/contract failures; execution candidates cannot.
                    if not profile.specification_confirmed:
                        raise ValueError('Confirm the linear contract specification before costed validation')
                    def progress(stage):
                        self.update(run_id, f'{symbol}: {stage}', (index+.4)/len(request.assets)*.85, report, artifacts)
                    validation = self.validator(bars, asset_request, profile, symbol, progress)
                    row.update(status='complete', validation=validation)
                    eligible = (request.source == 'mt5' and request.research_scope.setup == 'strategy_signals'
                                and request.strategy_name == EXECUTION_STRATEGY_NAME
                                and request.strategy_version == EXECUTION_STRATEGY_VERSION
                                and profile.market_impact_ticks_per_lot == 0
                                and quality['passed'] and not quality['stale_close_warning']
                                and profile.costs_confirmed and profile.slippage_confirmed
                                and profile.session.confirmed
                                and validation['passed'] and not snapshot.get('warnings'))
                    reasons = []
                    if request.source != 'mt5':
                        reasons.append('Only connected MT5 research can produce a demo candidate')
                    if request.research_scope.setup == 'opening_range_breakout':
                        reasons.append('Opening-range breakout results are research-only; the demo scanner does not execute this setup')
                    if (request.strategy_name != EXECUTION_STRATEGY_NAME
                            or request.strategy_version != EXECUTION_STRATEGY_VERSION):
                        reasons.append('This strategy name/version is not implemented by the MT5 execution engine')
                    if profile.market_impact_ticks_per_lot > 0:
                        reasons.append('Size-based market-impact scenario is research-only; the demo scanner does not apply this impact model')
                    if not quality['passed']:
                        reasons.append('Data quality or confirmed session calendar did not pass')
                    if quality['stale_close_warning']:
                        reasons.append(f"Stale close run reached {quality['stale_close_run_bars']} bars")
                    if not profile.costs_confirmed:
                        reasons.append('Broker costs were not confirmed')
                    if not profile.slippage_confirmed:
                        reasons.append('Instrument slippage scenario was not confirmed')
                    if not profile.specification_confirmed:
                        reasons.append('Linear contract specification was not confirmed')
                    reasons.extend(f'{name.replace("_", " ")} was not met'
                                   for name, passed in validation['checks'].items() if not passed)
                    reasons.extend(f'Broker warning: {warning}' for warning in snapshot.get('warnings', []))
                    row['demo_candidate'] = eligible
                    row['decision'] = 'demo_candidate' if eligible else 'no_trade'
                    row['no_trade_reasons'] = [] if eligible else reasons
                    if eligible:
                        selected_strategy = validation['selected_strategy']
                        parameters = {key: value for key, value in selected_strategy.items()
                                      if key not in {'symbol', 'timeframe', 'risk_pct', 'daily_loss_pct'}}
                        configuration = ResearchConfiguration(
                            instrument=InstrumentIdentity(
                                symbol=symbol, broker_server=snapshot['server'],
                                asset_class=profile.asset_class,
                                broker_group=profile.broker_group),
                            timeframe=timeframe,
                            strategy=StrategyDefinition(
                                name=request.strategy_name, version=request.strategy_version,
                                parameters=parameters),
                            risk=RiskConfiguration(
                                risk_pct=selected_strategy['risk_pct'],
                                daily_loss_pct=selected_strategy['daily_loss_pct']),
                            specification_fingerprint=snapshot['specification_fingerprint'],
                            profile_fingerprint=configuration_fingerprint(
                                profile.model_dump(mode='json')),
                            cost_model_fingerprint=configuration_fingerprint({
                                key: profile.model_dump(mode='json')[key]
                                for key in ('commission_per_lot', 'financing_long', 'financing_short',
                                            'rollover_timezone', 'rollover_minute', 'rollover_weights',
                                            'spread_price', 'slippage_ticks', 'market_impact_ticks_per_lot',
                                            'price_basis', 'fx_rates', 'fx_max_age_seconds',
                                            'costs_confirmed', 'cost_source', 'rollover_confirmed',
                                            'rollover_source', 'slippage_confirmed', 'slippage_source')}),
                            session_calendar=profile.session)
                        configuration_data = configuration.model_dump(mode='json')
                        report['candidates'].append({
                                                     'symbol':symbol, 'timeframe': timeframe,
                                                     'strategy':selected_strategy,
                                                     'configuration': configuration_data,
                                                     'configuration_fingerprint': configuration_fingerprint(configuration_data),
                                                     'instrument_profile': profile.model_dump(mode='json'),
                                                     'data_hash':data_hash, 'snapshot':snapshot,
                                                     'research_scope': request.research_scope.model_dump(),
                                                     'research_baseline': {'holdout': validation['holdout'],
                                                                           'oos_trades': validation['oos_trades'],
                                                                           'oos_pnl': validation['oos_pnl'],
                                                                           'validated_at': time.time()}})
                except ResearchCancelled:
                    raise
                except Exception as exc:
                    row = report['assets'].setdefault(symbol, {})
                    row.update(status='failed', error=str(exc)[:2000], demo_candidate=False,
                               decision='no_trade', no_trade_reasons=[str(exc)[:2000]])
                self.update(run_id,f'{symbol}: saved', (index+1)/len(request.assets)*.85,report,artifacts)
            self.update(run_id,'Correlation, cointegration and exposure analysis',.9,report,artifacts)
            grouped = {}
            for symbol, bars in series.items():
                grouped.setdefault(timeframes[symbol], {})[symbol] = bars
            relationship_reports = {
                timeframe: relationships(
                    grouped[timeframe], timeframe_seconds(timeframe),
                    request.minimum_overlap, request.rolling_window, exposures)
                for timeframe in sorted(grouped)
            }
            symbols = sorted(series)
            matrix = {a: {b: None for b in symbols} for a in symbols}
            for symbol in symbols:
                matrix[symbol][symbol] = relationship_reports[timeframes[symbol]]['matrix'][symbol][symbol]
            pairs, exposure_warnings, positive, negative = [], [], [], []
            for timeframe, result in relationship_reports.items():
                for pair in result['pairs']:
                    pairs.append({**pair, 'timeframe': timeframe})
                exposure_warnings.extend({**warning, 'timeframe': timeframe}
                                         for warning in result['exposure_warnings'])
                positive.extend({**row, 'timeframe': timeframe} for row in result['positive'])
                negative.extend({**row, 'timeframe': timeframe} for row in result['negative'])
                for a in result['symbols']:
                    for b in result['symbols']:
                        matrix[a][b] = result['matrix'][a][b]
            report['relationships'] = {
                'symbols': symbols, 'matrix': matrix, 'pairs': pairs,
                'exposure_warnings': exposure_warnings,
                'positive': positive, 'negative': negative,
                'by_timeframe': relationship_reports,
                'method': 'Returns are aligned and compared only within the same timeframe.',
                'cointegration_method': 'Cointegration tests run independently within each timeframe.',
                'note': 'Cross-timeframe correlations are not inferred. Individual research capital is independent; this is not a shared-portfolio simulation.'}
            decisions = list(report['assets'].values())
            report['decision_summary'] = {
                'assets': len(decisions),
                'demo_candidates': sum(item.get('decision') == 'demo_candidate' for item in decisions),
                'no_trade': sum(item.get('decision') == 'no_trade' for item in decisions),
                'failed': sum(item.get('status') == 'failed' for item in decisions),
                'overall_decision': 'candidate_available' if report['candidates'] else 'no_trade',
            }
            # Candidate checks are evidence, never permission to place orders.
            partial = any(a['status'] == 'failed' for a in report['assets'].values())
            self.update(run_id,'Finished with asset errors' if partial else 'Analysis complete',1,report,artifacts,'partial' if partial else 'complete')
        except ResearchCancelled:
            report['candidates'] = []
            self.update(run_id,'Cancelled; partial results retained',0,report,artifacts,'cancelled')
        except Exception as exc:
            report['candidates'] = []
            self.update(run_id,str(exc)[:2000],0,report,artifacts,'failed')
        finally:
            handle.close()

    def get(self, run_id, artifacts=False):
        with self.db() as db:
            row = db.execute('SELECT id,created,updated,status,stage,progress,input,report,artifacts FROM analyses WHERE id=?',(run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        result = dict(zip(('id','created','updated','status','stage','progress','input','report','artifacts'),row))
        for key in ('input','report','artifacts'):
            if key == 'artifacts' and not artifacts:
                result.pop(key)
            else:
                result[key] = json.loads(result[key])
        if not artifacts:
            for asset in result['input']['assets']:
                asset.pop('bars',None)
                asset.get('profile',{}).pop('fx_rates',None)
        return result

    def history(self):
        self.recover()
        with self.db() as db:
            return [dict(zip(('id','created','status','stage','progress'),row)) for row in db.execute('SELECT id,created,status,stage,progress FROM analyses ORDER BY created DESC LIMIT 100')]

    def cancel(self, run_id):
        with self.db() as db:
            db.execute("UPDATE analyses SET cancel=1 WHERE id=? AND status='running'",(run_id,))
        return self.get(run_id)

    def candidate(self, run_id, symbol):
        row = self.get(run_id)
        if row['status'] not in ('complete','partial') or time.time()-row['created'] > 7*86400:
            raise ValueError('A completed research report from the last seven days is required')
        candidate = next((c for c in row['report'].get('candidates',[]) if c['symbol']==symbol),None)
        if candidate is None:
            raise ValueError('This asset did not pass all data, cost and out-of-sample checks')
        return {**candidate,'run_id':run_id,'validated_at':row['created']}
