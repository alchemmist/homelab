"""Durable SPI jobs and deliberately small, English-only publication contracts."""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import time
import math
import random
from contextlib import contextmanager, closing
from datetime import datetime, timezone

class Failure(Exception):
    """Only fixed, non-sensitive codes may cross the worker API boundary."""
    def __init__(self, code, retry_after=None, rate_metadata=None):
        self.retry_after = min(86400,max(0,float(retry_after))) if type(retry_after) in (int,float) and math.isfinite(retry_after) else None
        self.rate_metadata={k:v for k,v in (rate_metadata or {}).items() if k in {'tokens_remaining','tokens_reset','requests_remaining','requests_reset','retry_after'} and type(v) in (int,float) and math.isfinite(v) and 0<=v<=1e12}
        self.code = code
        super().__init__(code)

# Only explicitly classified safe-to-repeat failures escape the terminal budget.
# GitHub publication ambiguity must NEVER acquire this classification.
LLM_TRANSIENT = {'LLM_'+code for code in (
    'HTTP_408','HTTP_425','HTTP_429','HTTP_500','HTTP_502','HTTP_503','HTTP_504',
    'UPSTREAM_TIMEOUT','UPSTREAM_NETWORK_ERROR','REQUEST_BUDGET_EXCEEDED',
    'MODEL_STAGE_BUDGET_EXCEEDED','ADMISSION_DEFERRED')}

PATIENT_TRANSIENT = LLM_TRANSIENT | {'STORAGE_TRANSIENT'}

SECRET_KEY = re.compile(r'authorization|cookie|password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|x[_-]?token|private[_-]?key', re.I)
SECRET_VALUE = re.compile(r'(?i)(?:bearer\s+\S+|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|-----BEGIN[^\n]*PRIVATE KEY-----[\s\S]*?-----END[^\n]*PRIVATE KEY-----)')
ASSIGNMENT = re.compile(r'(?i)((?:password|passwd|secret|token|api[_-]?key|cookie|authorization)\s*[=:]\s*)[^\s,;&]+')

def clean(value):
    if isinstance(value, dict):
        return {str(k)[:128]: '[REDACTED]' if SECRET_KEY.search(str(k)) else clean(v) for k, v in list(value.items())[:100]}
    if isinstance(value, list):
        return [clean(v) for v in value[:500]]
    if isinstance(value, str):
        return ASSIGNMENT.sub(r'\1[REDACTED]', SECRET_VALUE.sub('[REDACTED]', value))[:12000]
    return value

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def timestamp(text):
    try:
        d = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if not d.tzinfo:
            raise ValueError()
        return d.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except (ValueError, TypeError, AttributeError):
        raise Failure('INVALID_ALERT_TIMESTAMP') from None

def normalize(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('alert'), dict):
        raise Failure('INVALID_ALERT')
    raw = payload['alert']
    if raw.get('status') not in ('firing', 'resolved'):
        raise Failure('INVALID_ALERT_STATUS')
    labels = raw.get('labels', {})
    if not isinstance(labels, dict) or not labels.get('alertname') or len(labels) > 64:
        raise Failure('INVALID_ALERT_LABELS')
    if any(not isinstance(k, str) or not isinstance(v, str) or len(v) > 1024 for k,v in labels.items()):
        raise Failure('INVALID_ALERT_LABELS')
    annotations=raw.get('annotations',{})
    if not isinstance(annotations,dict) or len(annotations)>64 or any(not isinstance(v,str) or len(v)>16000 for v in annotations.values()):
        raise Failure('INVALID_ALERT_ANNOTATIONS')
    if not isinstance(raw.get('fingerprint',''),str) or len(raw.get('fingerprint',''))>256:
        raise Failure('INVALID_ALERT_FINGERPRINT')
    started = timestamp(raw.get('startsAt'))
    source = str(payload.get('source', 'socrat-alerts'))[:256]
    episode = digest([source, raw.get('fingerprint') or digest(labels), started])
    result = clean({'source': source, 'status': raw['status'], 'labels': labels,
                    'annotations': raw.get('annotations', {}), 'startsAt': started,
                    'endsAt': timestamp(raw['endsAt']) if raw.get('endsAt') and not raw['endsAt'].startswith('0001-') else None,
                    'generatorURL': raw.get('generatorURL', '')})
    # Episode identity is computed before redaction, but contains no reversible payload.
    result['episode'] = episode
    result['event_key'] = digest([episode, raw['status']])
    return result

MATCH_SCHEMA = {'type':'object','additionalProperties':False,'required':['issue_number','reason','confidence'],
 'properties':{'issue_number':{'type':'integer','minimum':0}, 'reason':{'type':'string'},
               'confidence':{'type':'string','enum':['high','medium','low']}}}
REPORT_SCHEMA = {'type':'object','additionalProperties':False,
 'properties':{
 'title':{'type':'string'}, 'summary':{'type':'string'},
 'severity':{'type':'string','enum':['critical','high','medium','low','unknown']},
 'confidence':{'type':'string','enum':['high','medium','low']},
 'issue_number':{'type':'integer','minimum':0}, 'match_reason':{'type':'string'},
 'impact':{'type':'string'}, 'facts':{'type':'array','items':{'type':'string'}},
 'hypotheses':{'type':'array','items':{'type':'string'}},
 'alert_quality':{'type':'string','enum':['actionable','likely_noisy','duplicate','insufficient_evidence']},
 'alert_assessment':{'type':'string'},
 'service_actions':{'type':'array','items':{'type':'string'}},
 'monitoring_actions':{'type':'array','items':{'type':'string'}},
 'missing_evidence':{'type':'array','items':{'type':'string'}}}}
REPORT_SCHEMA['required'] = list(REPORT_SCHEMA['properties'])

def validate(value, schema):
    """Small strict validator for the intentionally restricted schemas above."""
    typ = schema['type']
    if typ == 'object':
        if not isinstance(value, dict) or set(value) != set(schema['required']):
            raise Failure('INVALID_MODEL_SCHEMA')
        for k,s in schema['properties'].items(): validate(value[k], s)
    elif typ == 'array':
        if not isinstance(value, list) or len(value) > 30: raise Failure('INVALID_MODEL_SCHEMA')
        for v in value: validate(v, schema['items'])
    elif typ == 'string':
        if not isinstance(value,str) or not value.strip() or len(value)>8000: raise Failure('INVALID_MODEL_SCHEMA')
        # Fail closed on non-English scripts rather than publishing untranslated prose.
        if any(ord(c)>127 and c.isalpha() for c in value): raise Failure('NON_ENGLISH_MODEL_OUTPUT')
    elif typ == 'integer':
        if type(value) is not int or value < schema.get('minimum', 0): raise Failure('INVALID_MODEL_SCHEMA')
    if 'enum' in schema and value not in schema['enum']: raise Failure('INVALID_MODEL_SCHEMA')
    return value

def render(report, event):
    validate(report, REPORT_SCHEMA)
    title = report['title'].strip()
    if not title.startswith('[SPI] '): title = '[SPI] ' + title
    if len(title)>180 or '\n' in title: raise Failure('INVALID_ISSUE_TITLE')
    lines = [report['summary'], '', f"**Severity:** {report['severity']} · **Confidence:** {report['confidence']}",
             '', '## Observed impact', report['impact']]
    for heading, field in [('Verified facts','facts'),('Hypotheses (not established root cause)','hypotheses'),
                           ('Service recovery and prevention','service_actions'),('Monitoring improvements','monitoring_actions'),
                           ('Missing evidence','missing_evidence')]:
        lines += ['', '## '+heading] + ['- '+x for x in report[field]]
    lines += ['', '## Alert quality', '**Classification:** '+report['alert_quality'], report['alert_assessment'],
              '', '## Incident correlation', report['match_reason'], '', '## Provenance',
              '- Started: '+event['startsAt'], '- Analysis is automated and read-only; recommendations require review.',
              '- Bounded diagnostic artifacts, collection gaps and absolute-time Explore links accompany this episode when collected.',
              '- Missing series or zero matching errors do not establish service health or exclude an incident.',
              '- Deployed image IDs and OCI build claims are distinguished from verified source; repository-main references do not prove deployment.',
              '- Credentials are redacted; diagnostic artifacts may reveal internal topology.', '', '<!-- socrat-spi:'+event['event_key']+' -->']
    body = '\n'.join(lines)
    # Redaction changing model output is a contract failure, not silent publication.
    if clean(title) != title or clean(body) != body: raise Failure('UNSAFE_MODEL_OUTPUT')
    return title, body

class Store:
    def __init__(self, path):
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('PRAGMA temp_store=MEMORY')
            c.execute('PRAGMA journal_mode=WAL')
        with self.db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, episode TEXT NOT NULL, event TEXT NOT NULL,
              stage INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'queued',
              created REAL NOT NULL, updated REAL NOT NULL, available REAL NOT NULL,
              lease REAL NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
              deliveries INTEGER NOT NULL DEFAULT 1, result TEXT NOT NULL DEFAULT '{}',
              issue INTEGER NOT NULL DEFAULT 0, intent TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS llm_rate_metadata (job_id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS llm_admission (id INTEGER PRIMARY KEY, tokens INTEGER NOT NULL, expires REAL NOT NULL, active INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS dispatch (singleton INTEGER PRIMARY KEY CHECK(singleton=1), token TEXT NOT NULL, deadline REAL NOT NULL, attempts INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS job_failure_budget (
              job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
              failures INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS runnable ON jobs(state,available,lease);
            CREATE INDEX IF NOT EXISTS episode ON jobs(episode);
            ''')
    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            c.execute('PRAGMA busy_timeout=15000'); c.execute('PRAGMA temp_store=MEMORY'); c.execute('BEGIN IMMEDIATE')
            yield c; c.commit()
        except BaseException:
            c.rollback(); raise
        finally: c.close()
    def reserve_llm(self, tokens, timeout=600, now=None):
        """One SPI-key ledger on the shared PVC. No credentials or payloads."""
        if type(tokens) is not int or not 0 < tokens <= 30000:
            raise Failure('LLM_REQUEST_TOO_LARGE')
        now=time.time() if now is None else now
        with self.db() as c:
            c.execute('DELETE FROM llm_admission WHERE expires<=?',(now,))
            rows=c.execute('SELECT * FROM llm_admission ORDER BY expires').fetchall()
            if any(r['active'] for r in rows) or len(rows)>=3 or sum(r['tokens'] for r in rows)+tokens>30000:
                # Earliest ledger change; retrying re-evaluates every constraint.
                raise Failure('LLM_ADMISSION_DEFERRED',retry_after=max(1,min(r['expires'] for r in rows)-now))
            return c.execute('INSERT INTO llm_admission(tokens,expires,active) VALUES(?,?,1)',
                             (tokens,now+timeout+61)).lastrowid

    def finish_llm(self, reservation, actual=None, now=None):
        now=time.time() if now is None else now
        with self.db() as c:
            # Never refund an estimate: proxy reservation semantics may differ.
            if type(actual) is int and actual>=0:
                c.execute('UPDATE llm_admission SET tokens=max(tokens,?) WHERE id=?',(actual,reservation))
            c.execute('UPDATE llm_admission SET active=0,expires=? WHERE id=?',(now+61,reservation))

    def recover_on_start(self):
        # Called only by the sole Recreate worker, never by ordinary connections.
        # The previous process cannot still publish once its replacement starts.
        now=time.time()
        with self.db() as c:
            return c.execute("UPDATE jobs SET state='retry',lease=0,available=?,updated=? WHERE state='processing'",(now,now)).rowcount
    def enqueue(self, event):
        return self.enqueue_many([event])[0]
    def enqueue_many(self, events):
        now=time.time();results=[]
        with self.db() as c:
            for event in events:
                results.append(self._enqueue(c,event,now))
        return results
    def _enqueue(self,c,event,now):
        key=event['event_key']
        cur=c.execute('INSERT OR IGNORE INTO jobs(id,episode,event,created,updated,available) VALUES(?,?,?,?,?,?)',
                      (key,event['episode'],json.dumps(event),now,now,now))
        if cur.rowcount == 0: c.execute('UPDATE jobs SET deliveries=deliveries+1,updated=? WHERE id=?',(now,key))
        return {'job_id':key,'duplicate':cur.rowcount == 0}
    def get(self, key):
        with self.db() as c: row=c.execute('SELECT * FROM jobs WHERE id=?',(key,)).fetchone()
        if row is None: raise Failure('JOB_NOT_FOUND')
        d=dict(row); d['event']=json.loads(d['event']); d['result']=json.loads(d['result']);return d
    def claim(self):
        now=time.time()
        with self.db() as c:
            c.execute('DELETE FROM dispatch WHERE singleton=1')
            if c.execute("SELECT 1 FROM jobs WHERE state='processing' AND lease>?",(now,)).fetchone(): return {'job_id':''}
            row=c.execute("SELECT id FROM jobs WHERE state IN ('queued','retry','processing') AND available<=? AND lease<=? ORDER BY created,id LIMIT 1",(now,now)).fetchone()
            if not row:return {'job_id':''}
            c.execute("UPDATE jobs SET state='processing',lease=?,attempts=attempts+1,updated=? WHERE id=?",(now+1500,now,row['id']))
            return {'job_id':row['id']}
    def save(self,key,stage,result,on_save=None,**fields):
        allowed={'state','issue','intent','error'}
        if not set(fields)<=allowed: raise ValueError('Invalid job fields')
        now=time.time()
        with self.db() as c:
            c.execute('UPDATE jobs SET stage=?,result=?,updated=?,lease=?'+''.join(','+k+'=?' for k in fields)+' WHERE id=?',
                      [stage,json.dumps(result),now,0 if fields.get('state') in ('complete','dry_run','dead') else now+1500,*fields.values(),key])
            if on_save is not None:on_save(c)
    def fail(self,key,code,retry_after=None,rate_metadata=None):
        job=self.get(key);now=time.time()
        with self.db() as c:
            # Total claims remain diagnostic. Busy LLM deferrals must not spend
            # the independent recovery allowance of later stages/publication.
            if rate_metadata:
                safe=Failure(code,rate_metadata=rate_metadata).rate_metadata
                c.execute('INSERT OR REPLACE INTO llm_rate_metadata VALUES(?,?)',(key,json.dumps(safe)))
            count=job['attempts']
            if code not in PATIENT_TRANSIENT:
                c.execute("INSERT INTO job_failure_budget VALUES(?,1) ON CONFLICT(job_id) DO UPDATE SET failures=failures+1",(key,))
                count=c.execute('SELECT failures FROM job_failure_budget WHERE job_id=?',(key,)).fetchone()[0]
            dead=(count>=8 and code not in PATIENT_TRANSIENT) or code=='WRITE_NEEDS_REVIEW'
            delay=min(3600,30*2**min(count,7)*random.uniform(.8,1.2))
            if code in PATIENT_TRANSIENT and retry_after is not None:delay=max(delay,Failure(code,retry_after).retry_after or 0)
            if code=='LLM_ADMISSION_DEFERRED' or (code=='LLM_HTTP_429' and retry_after is not None):
                delay=(Failure(code,retry_after).retry_after or 61)+random.uniform(1,3)
            c.execute('UPDATE jobs SET state=?,lease=0,available=?,updated=?,error=? WHERE id=?',
                      ('dead' if dead else 'retry',now+delay,now,code,key))
    def episode_issue(self,episode):
        with self.db() as c: row=c.execute("SELECT issue FROM jobs WHERE episode=? AND issue>0 ORDER BY created LIMIT 1",(episode,)).fetchone()
        return row['issue'] if row else 0
    def health(self):
        with self.db() as c:
            counts={r['state']:r['n'] for r in c.execute('SELECT state,count(*) n FROM jobs GROUP BY state')}
            oldest=c.execute("SELECT min(created) FROM jobs WHERE state IN ('queued','retry','processing')").fetchone()[0]
        return {'counts':counts,'oldest_pending_seconds':max(0,int(time.time()-oldest)) if oldest else 0}

    def reserve_dispatch(self, now=None):
        """Reserve one wake durably; return (reservation id, next deadline)."""
        now=time.time() if now is None else now
        with self.db() as c:
            active=c.execute("SELECT max(lease) FROM jobs WHERE state='processing' AND lease>?",(now,)).fetchone()[0]
            if active:return None,active
            due=c.execute("SELECT min(max(available,lease)) FROM jobs WHERE state IN ('queued','retry','processing')").fetchone()[0]
            if due is None:return None,None
            r=c.execute('SELECT * FROM dispatch WHERE singleton=1').fetchone()
            deadline=max(due,r['deadline'] if r else 0)
            if deadline>now:return None,deadline
            import uuid
            token=uuid.uuid4().hex
            attempts=(r['attempts'] if r else 0)+1
            # Both successful and ambiguous responses await callback acknowledgement.
            deadline=now+min(300,30*2**min(attempts-1,4))
            c.execute('INSERT OR REPLACE INTO dispatch VALUES(1,?,?,?)',(token,deadline,attempts))
            return token,deadline

    def dispatch_status(self):
        with self.db() as c:
            row=c.execute('SELECT deadline,attempts FROM dispatch WHERE singleton=1').fetchone()
            return dict(row) if row else {'deadline':0,'attempts':0}
