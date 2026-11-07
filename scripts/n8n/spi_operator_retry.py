#!/usr/bin/env python3
"""Offline-reviewed, private operator CLI. Default dry-run; never a public API.
No allowance reset: one subsequent unsafe failure can kill a selected job again.
"""
import argparse
import datetime
import hashlib
import json
import re
import sqlite3
import time

TARGETS = {
 '08ba1f0938dd3bf6d8a03b9383b5d852255bbd16fa6c24ba6ece198c0a503af9': 'LLM_CONTEXT_METADATA_TOO_LARGE',
 '998bcead172052e72c281f3cd1d312c4f82412002ecf40232da6c6631b45e362': 'UPSTREAM_TIMEOUT',
}
NONCE = 'spi-two-target-retry-08ba-998b-20261107-v1'
AUDIT = 'operator_retry_audit'

def packed(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=True)

def digest(x):
    return hashlib.sha256(packed(x).encode()).hexdigest()

def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def ordered_table_scan(c, name):
    """Transaction-local physical order, not a VACUUM-independent logical hash.

    Never sort complete rows: require the native rowid/primary btree order and
    check the actual planner before streaming. Unsupported schemas fail closed.
    """
    tables = list(c.execute('PRAGMA main.table_list'))
    matches = [r for r in tables if r[1] == name]
    if len(matches) != 1 or matches[0][2] != 'table':
        raise ValueError('unsupported table kind')
    q = quoted(name)
    info = list(c.execute('PRAGMA main.table_xinfo(' + q + ')'))
    if not info:
        raise ValueError('unsupported table columns')
    if matches[0][4]:  # WITHOUT ROWID: declared primary key is the table btree.
        keys = sorted((r for r in info if r[5]), key=lambda r: r[5])
        if not keys:
            raise ValueError('missing WITHOUT ROWID primary key')
        order = ','.join(quoted(r[1]) for r in keys)
    else:
        names = {r[1].lower() for r in info}
        alias = next((a for a in ('rowid', '_rowid_', 'oid') if a not in names), None)
        if alias is None:
            # Refuse rather than risk an index sort or a nullable/nonunique key.
            raise ValueError('all rowid aliases shadowed: unsupported schema')
        order = quoted(alias)
    sql = 'SELECT * FROM main.' + q + ' ORDER BY ' + order
    plan = list(c.execute('EXPLAIN QUERY PLAN ' + sql))
    if not plan or any('TEMP B-TREE' in r[3].upper() for r in plan):
        raise ValueError('table scan requires temporary sort')
    return c.execute(sql)


def table_hashes(c, original_jobs=None):
    result = {}
    for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        if name == AUDIT:
            continue
        # Whole rows, streamed in stable btree order within BEGIN IMMEDIATE.
        # Memory is bounded by a row and its serialized representation.
        h = hashlib.sha256()
        for row in ordered_table_scan(c, name):
            if name == 'jobs' and original_jobs and row['id'] in original_jobs:
                row = [original_jobs[row['id']][k] for k in row.keys()]
            h.update(packed([{'blob':v.hex()} if isinstance(v, bytes) else v for v in row]).encode()+b'\n')
        result[name] = h.hexdigest()
    return result

def manifest_digest(manifest):
    if (not isinstance(manifest, dict) or manifest.get('version') != 1
        or manifest.get('nonce') != NONCE
        or not re.fullmatch(r'[0-9a-f]{64}', manifest.get('original_target_file_sha256', ''))):
        raise ValueError('invalid target manifest')
    rows = manifest.get('rows')
    if (not isinstance(rows, list) or len(rows) != 2
        or any(not isinstance(r, dict) for r in rows)
        or {r.get('id') for r in rows} != set(TARGETS)):
        raise ValueError('invalid manifest IDs')
    return digest(manifest)

def authorize(a):
    if (a.get('authorization_text') != 'Да, все рзрешаю' or a.get('nonce') != NONCE
        or set(a.get('job_ids', [])) != set(TARGETS) or len(a['job_ids']) != 2
        or not a.get('reason') or not a.get('recorded_at')
        or a.get('supervisor_run_id') != '497906c9-c254-4586-9762-e1aa195b8f24'):
        raise ValueError('authorization mismatch')
    datetime.datetime.fromisoformat(a['recorded_at'].replace('Z','+00:00'))

def retry(path, authorization, execute=False, manifest=None):
    authorize(authorization)
    bound = manifest_digest(manifest)
    if authorization.get('target_manifest_digest') != bound:
        raise ValueError('authorization manifest mismatch')
    c = sqlite3.connect('file:'+str(path)+'?mode=rw', uri=True, isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute('BEGIN IMMEDIATE')
        before = table_hashes(c)
        rows = []
        for key, error in TARGETS.items():
            matches = list(c.execute('SELECT * FROM jobs WHERE id=?', (key,)))
            if len(matches) != 1:
                raise ValueError('missing exact full ID')
            row = dict(matches[0])
            if row != next(r for r in manifest['rows'] if r['id'] == key):
                raise ValueError('reviewed full row drift')
            if row['state']=='complete' and row['stage']==2:
                raise ValueError('already complete: skip, never rerun')
            if (row['state']!='dead' or row['stage']!=2 or row['lease']!=0
                or row['error']!=error or row['intent'] is not None):
                raise ValueError('unexpected state/stage/lease/error/intent')
            if c.execute("SELECT 1 FROM jobs WHERE episode=? AND (intent IS NOT NULL OR state='complete') LIMIT 1", (row['episode'],)).fetchone():
                raise ValueError('episode publication or active intent')
            rows.append(row)
        if AUDIT in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            if c.execute('SELECT 1 FROM operator_retry_audit WHERE nonce=? LIMIT 1',(NONCE,)).fetchone():
                raise ValueError('authorization nonce already consumed')
        if not execute:
            c.rollback()
            return {'mode':'DRY_RUN','eligible':2,'row_hashes':{r['id']:digest(r) for r in rows}}
        c.execute('CREATE TABLE IF NOT EXISTS operator_retry_audit (nonce TEXT NOT NULL, job_id TEXT NOT NULL, authorization_hash TEXT NOT NULL, pre_row_hash TEXT NOT NULL, executed_at REAL NOT NULL, reason TEXT NOT NULL, explicit_change TEXT NOT NULL, manifest_digest TEXT NOT NULL, post_row_hash TEXT NOT NULL, PRIMARY KEY(nonce,job_id))')
        for action in ('UPDATE','DELETE'):
            name='operator_retry_audit_no_'+action.lower()
            sql='CREATE TRIGGER '+name+' BEFORE '+action+' ON operator_retry_audit BEGIN SELECT RAISE(ABORT,\'immutable audit\'); END'
            existing=c.execute("SELECT sql FROM sqlite_master WHERE name=?",(name,)).fetchone()
            if existing is None:
                c.execute(sql)
            elif existing[0] != sql:
                raise ValueError('audit immutability schema mismatch')
        if c.execute('SELECT count(*) FROM operator_retry_audit').fetchone()[0] + 2 > 2:
            raise ValueError('bounded audit full')
        audit_schema = list(c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"))
        audit_before = [tuple(r) for r in c.execute('SELECT * FROM operator_retry_audit ORDER BY nonce,job_id')]
        expected_audit = list(audit_before)
        now=time.time()
        for row in rows:
            change={'state':'retry','available':now,'updated':now}
            c.execute('UPDATE jobs SET state=?,available=?,updated=? WHERE id=?',('retry',now,now,row['id']))
            entry=(NONCE,row['id'],digest(authorization),digest(row),now,authorization['reason'],packed(change),bound,digest(dict(row,**change)))
            c.execute('INSERT INTO operator_retry_audit VALUES(?,?,?,?,?,?,?,?,?)',entry)
            expected_audit.append(entry)
            actual=dict(c.execute('SELECT * FROM jobs WHERE id=?',(row['id'],)).fetchone())
            if actual != dict(row,**change):
                raise ValueError('unexpected selected row mutation')
        # Normalize only the two already-verified selected rows while hashing;
        # no compensating UPDATEs or history rewrites are performed.
        if table_hashes(c, {r['id']:r for r in rows}) != before:
            raise ValueError('non-authorized row/table mutation')
        expected={r['id']:dict(r,state='retry',available=now,updated=now) for r in rows}
        for key,row in expected.items():
            if dict(c.execute('SELECT * FROM jobs WHERE id=?',(key,)).fetchone())!=row:
                raise ValueError('final target mismatch')
        if ([tuple(r) for r in c.execute('SELECT * FROM operator_retry_audit ORDER BY nonce,job_id')]
            != sorted(expected_audit, key=lambda r:(r[0],r[1]))
            or list(c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")) != audit_schema):
            raise ValueError('audit content/schema mismatch')
        c.commit()
        return {'mode':'EXECUTED','changed':2,'authorization_hash':digest(authorization)}
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',required=True)
    p.add_argument('--authorization',required=True)
    p.add_argument('--target-manifest',required=True)
    p.add_argument('--execute',action='store_true')
    a=p.parse_args()
    with open(a.authorization) as f: auth=json.load(f)
    with open(a.target_manifest) as f: manifest=json.load(f)
    print(packed(retry(a.database,auth,a.execute,manifest)))

if __name__=='__main__':
    main()
