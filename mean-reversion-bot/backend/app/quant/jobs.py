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

from app.quant.schemas import AnalysisRequest
from app.quant.sources import load_asset
from app.quant.statistics import audit, relationships
from app.quant.validation import validate_strategy


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
                  'implementation_hash': fingerprint({p.name: p.read_text(encoding='utf-8') for p in Path(__file__).parent.glob('*.py')})}
        artifacts, series, exposures = {}, {}, dict(request.exposures)
        end = int(time.time() // request.interval) * request.interval
        start = end - request.days*86400
        try:
            for index, asset in enumerate(request.assets):
                symbol = asset.symbol
                try:
                    self.update(run_id, f'{symbol}: ingest and audit', index/len(request.assets)*.85, report)
                    bars, profile, snapshot, exposure = self.loader(asset, request, runner, start, end)
                    if not bars or len(bars)>10000:
                        raise ValueError('Supply 100–10,000 candles per asset')
                    audit_start = bars[0].timestamp if request.source == 'import' else start
                    audit_end = bars[-1].timestamp+request.interval if request.source == 'import' else end
                    quality = audit(bars,request.interval,profile.session,audit_start,audit_end)
                    series[symbol] = bars
                    if request.source == 'mt5':
                        exposures[symbol] = exposure
                    artifacts[symbol] = {'bars': [b.model_dump() for b in bars], 'profile': profile.model_dump(mode='json'), 'snapshot': snapshot}
                    data_hash = fingerprint(artifacts[symbol])
                    row = {'status': 'analyzing', 'quality': quality, 'snapshot': snapshot,
                           'data_hash': data_hash, 'costs_confirmed': profile.costs_confirmed,
                           'specification_confirmed': profile.specification_confirmed}
                    report['assets'][symbol] = row
                    # Correlation survives cost/contract failures; execution candidates cannot.
                    if not profile.specification_confirmed:
                        raise ValueError('Confirm the linear contract specification before costed validation')
                    def progress(stage):
                        self.update(run_id, f'{symbol}: {stage}', (index+.4)/len(request.assets)*.85, report, artifacts)
                    validation = self.validator(bars,request,profile,symbol,progress)
                    row.update(status='complete', validation=validation)
                    eligible = (request.source == 'mt5' and quality['passed'] and profile.costs_confirmed
                                and validation['passed'] and not snapshot.get('warnings'))
                    row['demo_candidate'] = eligible
                    if eligible:
                        report['candidates'].append({'symbol':symbol, 'strategy':validation['selected_strategy'],
                                                     'data_hash':data_hash, 'snapshot':snapshot})
                except ResearchCancelled:
                    raise
                except Exception as exc:
                    row = report['assets'].setdefault(symbol, {})
                    row.update(status='failed', error=str(exc)[:2000], demo_candidate=False)
                self.update(run_id,f'{symbol}: saved', (index+1)/len(request.assets)*.85,report,artifacts)
            self.update(run_id,'Correlation, cointegration and exposure analysis',.9,report,artifacts)
            report['relationships'] = relationships(series,request.interval,request.minimum_overlap,request.rolling_window,exposures)
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
