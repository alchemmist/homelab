"""Run inside the exact Canvas image, with no worker started and source mounted read-only."""
import asyncio
from collections import Counter
from datetime import datetime, timezone, date
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import ssl
import sys
import uuid

import asyncpg
from sqlalchemy import event, text
from sqlalchemy.engine import Engine, make_url
from alembic.config import Config
from alembic import command
from openhands.automation import migrations


def ident(name):
    if not re.fullmatch(r'[a-z][a-z0-9_]*', name): raise ValueError('Unexpected identifier')
    return '"'+name+'"'


def schema(url):
    # Native Alembic environment uses pg8000; install a validating SSLContext
    # instead of its limited string-mode adapter. No service/scheduler is run.
    parsed=make_url(url); assert parsed.query.get('ssl')=='verify-full'
    os.environ['AUTOMATION_DB_URL']=parsed.difference_update_query(['ssl']).render_as_string(hide_password=False)
    os.environ['AUTOMATION_CREATE_DATABASE_IF_MISSING']='false'
    ctx=ssl.create_default_context(cafile=os.environ['PGSSLROOTCERT'])
    def tls(dialect, rec, args, kwargs):
        assert dialect.driver=='pg8000' and kwargs['host']==parsed.host
        kwargs['ssl_context']=ctx
    event.listen(Engine,'do_connect',tls)
    try:
        cfg=Config(); cfg.set_main_option('script_location',str(next(iter(migrations.__path__))));command.upgrade(cfg,'head')
    finally:
        event.remove(Engine,'do_connect',tls);os.environ['AUTOMATION_DB_URL']=url


def cv(v, typ):
    if v is None:return None
    if typ=='uuid':return uuid.UUID(str(v))
    if typ in ('json','jsonb'):return json.dumps(json.loads(v),sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    if typ in ('timestamp','timestamptz'):
        d=datetime.fromisoformat(v) if isinstance(v,str) else v
        if typ=='timestamptz':return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        return d
    if typ=='bool':
        if v not in (0,1):raise ValueError('Unexpected boolean')
        return bool(v)
    return v


async def transfer(url, source_path):
    conn=await asyncpg.connect(make_url(url).difference_update_query(['ssl']).set(drivername='postgresql').render_as_string(hide_password=False),ssl='verify-full',timeout=8)
    dst=conn;src=sqlite3.connect(source_path.as_uri()+'?mode=ro',uri=True);src.execute('BEGIN')
    try:
        if src.execute('pragma integrity_check').fetchall()!=[('ok',)] or src.execute('pragma foreign_key_check').fetchone():raise ValueError('Source integrity check failed')
        tables={n for n, in src.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
        async with dst.transaction():
            await dst.execute("SET LOCAL TIME ZONE 'UTC'")
            target={r[0] for r in await dst.fetch("select tablename from pg_tables where schemaname='public'")}
            if tables!=target:raise ValueError(('Table mismatch',tables^target))
            if src.execute('select version_num from alembic_version').fetchall()!=[('037',)] or await dst.fetchval('select version_num from alembic_version')!='037':raise ValueError('Revision mismatch')
            fk=await dst.fetch("select t.relname,p.relname from pg_constraint c join pg_class t on t.oid=c.conrelid join pg_class p on p.oid=c.confrelid where c.contype='f' and t.relnamespace='public'::regnamespace")
            done={'alembic_version'}
            while tables-done:
                batch=[t for t in sorted(tables-done) if all(r[1] in done or r[1]==t for r in fk if r[0]==t)]
                if not batch:raise ValueError('Dependency cycle')
                for t in batch:
                    q=ident(t);meta=await dst.fetch('select column_name,udt_name from information_schema.columns where table_schema=\'public\' and table_name=$1 order by ordinal_position',t);names=[r[0] for r in meta];types=[r[1] for r in meta]; sn={r[1] for r in src.execute('pragma table_info('+q+')')};
                    if set(names)!=sn:raise ValueError(('Column mismatch',t,sn^set(names)))
                    cols=','.join(map(ident,names));sel='SELECT '+cols+' FROM '+q
                    normalize=lambda row:tuple(cv(v,k) for v,k in zip(row,types,strict=True))
                    expected=[normalize(r) for r in src.execute(sel)];before=await dst.fetch(sel)
                    if before:raise ValueError(('Nonempty target',t,len(before)))
                    if expected:await dst.executemany('INSERT INTO '+q+' ('+cols+') VALUES ('+','.join('$'+str(i+1) for i in range(len(names)))+')',expected)
                    if Counter(expected)!=Counter(normalize(r) for r in await dst.fetch(sel)):raise ValueError(('Row mismatch',t))
                    print(t,len(expected));done.add(t)
            seq=await dst.fetch("select sequencename from pg_sequences where schemaname='public'");
            if seq:raise ValueError('Reseed identities before cutover')
    finally:src.close();await dst.close()

if __name__=='__main__':
    url=os.environ['AUTOMATION_DB_URL'];trial=sys.argv[1]=='trial';assert sys.argv[1] in ('trial','final');url=url.replace('/openhands_automations?', '/oh_automation_trial?') if trial else url
    assert make_url(url).database==('oh_automation_trial' if trial else 'openhands_automations');schema(url)
    source=Path('/src/automations.db')
    if trial:
        asyncio.run(transfer(url,source))
    else:
        # The writer must already be stopped. A read-only WAL volume may not
        # permit SQLite to create its shared memory file. Recover privately.
        import shutil,tempfile
        with tempfile.TemporaryDirectory() as work:
            cold=Path(work)/source.name
            for suffix in ('','-wal','-journal'):
                f=Path(str(source)+suffix)
                if f.exists():shutil.copyfile(f,str(cold)+suffix)
            asyncio.run(transfer(url,cold))
