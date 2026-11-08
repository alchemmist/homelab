#!/usr/bin/env python3
"""Withdraw only plaintext32063 from subscriptions; retain cached-client listener.
Owner coordinates end-device refresh. No client/key/binding deletion or listener retirement.
Default preview; explicit fresh session+configuration hashes required for native API write.
"""
import argparse
import copy
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.parse
import urllib.request
import base64


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

native=load('native_session','vpn-panel-session.py')
target=load('target_helpers','vpn-reality-apply.py')
h=native.h


def select(config):
    rows=[r for r in config['inbounds'] if r['port']==32063]
    if len(rows)!=1:raise ValueError('Expected one legacy inbound')
    row=rows[0];stream=json.loads(row['stream_settings'])
    if not row['enable'] or row['protocol']!='vless' or stream.get('network')!='xhttp' or stream.get('security') not in (None,'','none'):
        raise ValueError('Legacy transport drift')
    if row.get('exclude_from_sub'):raise ValueError('Already withdrawn; do not replay')
    return row


def desired(config):
    result=copy.deepcopy(config);row=select(result);row['exclude_from_sub']=True;return result


def payload(inbound,expected_id):
    obj=copy.deepcopy(inbound)
    stream=target.json_field(obj.get('streamSettings'))
    if (obj.get('id')!=expected_id or obj.get('port')!=32063 or obj.get('protocol')!='vless'
        or obj.get('enable') is not True or obj.get('excludeFromSub') or stream.get('network')!='xhttp'
        or stream.get('security') not in (None,'','none')):raise ValueError('API preimage drift')
    obj['excludeFromSub']=True;obj.pop('clientStats',None);return obj


def normalize(body):
    text=body.decode('utf-8').strip()
    if '://' not in text:text=base64.b64decode(text+'='*(-len(text)%4),validate=True).decode('utf-8')
    result=[]
    for line in text.splitlines():
        line=line.strip()
        if not line:continue
        parsed=urllib.parse.urlsplit(line)
        if not parsed.scheme or '://' not in line:raise ValueError('Unexpected subscription format')
        query=urllib.parse.parse_qsl(parsed.query,keep_blank_values=True)
        if ('security','reality') in query:query=[(k,v) for k,v in query if k!='sid']
        result.append(urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(sorted(query)))))
    if not result:raise ValueError('Empty subscription')
    return sorted(result)


def normalize_json(value):
    if isinstance(value,dict):
        out={k:normalize_json(v) for k,v in value.items()}
        if isinstance(out.get('realitySettings'),dict):out['realitySettings'].pop('shortId',None)
        return out
    if isinstance(value,list):return [normalize_json(v) for v in value]
    return value


def json_legacy(config):
    return any(o.get('protocol')=='vless' and any(v.get('port')==32063 for v in o.get('settings',{}).get('vnext',[]))
               for o in config.get('outbounds',[]))


def is_legacy(uri):
    p=urllib.parse.urlsplit(uri)
    return p.scheme=='vless' and p.port==32063


def snapshot(database,state,phase,json_format=False):
    directory=h.private_directory(state/phase)
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as c:
        settings=dict(c.execute('SELECT key,value FROM settings'))
        rows=c.execute('SELECT id,sub_id FROM clients WHERE enable=1 ORDER BY id').fetchall()
    if int(settings['subPort'])!=12096 or settings.get('subListen','') not in ('','127.0.0.1','0.0.0.0','::'):
        raise ValueError('Subscription listener drift')
    prefix=settings['subJsonPath' if json_format else 'subPath']
    if not prefix.startswith('/') or any(x in prefix for x in ('?','#','..','\\')):raise ValueError('Unsafe subscription path')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),native.NoRedirect())
    result={}
    for client_id,sub_id in rows:
        if not sub_id:raise ValueError('Missing enabled subscription')
        suffix='/'+prefix.strip('/')+'/'+urllib.parse.quote(sub_id,safe='')
        pair=[]
        for label,origin in [('backend','http://127.0.0.1:12096'),('public','https://vpn.alchemmist.xyz')]:
            req=urllib.request.Request(origin+suffix,headers={'Host':'vpn.alchemmist.xyz','User-Agent':'homelab-subscription-migration/1'})
            with opener.open(req,timeout=12) as r:
                body=r.read(262145)
                if r.status!=200 or len(body)>262144:raise ValueError('Subscription response refused')
            links=normalize_json(json.loads(body)) if json_format else normalize(body)
            if not isinstance(links,list) or not links:raise ValueError('Empty publication')
            h.save(directory/(str(client_id)+'-'+label+'-private.json'),links);pair.append(links)
        if pair[0]!=pair[1]:raise ValueError('Public/backend mismatch')
        result[str(client_id)]=pair[0]
    return result


def check_delta(before,after):
    if set(before)!=set(after):raise ValueError('Identity set changed')
    affected=0;removed=0
    for key,links in before.items():
        expected=[uri for uri in links if not is_legacy(uri)]
        legacy=len(links)-len(expected)
        if legacy:
            affected+=1;removed+=legacy
            if not any(urllib.parse.urlsplit(u).scheme=='vless' and dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(u).query)).get('security')=='reality' for u in expected):
                raise ValueError('Missing published REALITY replacement')
        if after[key]!=expected:raise ValueError('Unexpected subscription change')
    if affected!=7 or removed!=7:raise ValueError('Affected population drift')
    return {'identities':len(before),'affected':affected,'plaintext_links_removed':removed,
            'remaining_published_entries':sum(len(v) for v in after.values()),'unrelated_profiles_preserved':True}


def apply(state,session_hash,config_hash):
    s=native.NativeSession(state);original=target.configuration(s.database);legacy=select(original)
    if h.digest(original)!=config_hash:raise ValueError('Fresh config approval required')
    # Population/enabled replacement gate before credentials.
    summary=h.summarize(original);row=next(r for r in summary['inbounds'] if r['port']==32063)
    if row['client_links']!=7 or row['links_with_existing_enabled_encrypted_alternative']!=7:raise ValueError('Replacement gate failed')
    s.open(session_hash)
    try:
        if target.semantic(target.configuration(s.database))!=target.semantic(original):raise ValueError('Config changed opening session')
        h.save(s.state/'proxy-before-private.json',original)
        before=snapshot(s.database,s.state,'subscriptions-before')
        json_before=snapshot(s.database,s.state,'json-before',True)
        if set(json_before)!=set(before):raise ValueError('JSON identity mismatch')
        if sum(sum(json_legacy(v) for v in rows) for rows in json_before.values())!=7:raise ValueError('JSON population drift')
        # Verify exact publication diff prospectively, before making any write.
        prospective={key:[u for u in links if not is_legacy(u)] for key,links in before.items()}
        check_delta(before,prospective)
        pre=target.configuration(s.database)
        rows=s.call('GET','/inbounds/list');matches=[r for r in rows if r['id']==legacy['id']]
        if len(matches)!=1:raise ValueError('Missing native inbound')
        dto=payload(matches[0],legacy['id'])
        if target.semantic(pre)!=target.semantic(original) or target.semantic(target.configuration(s.database))!=target.semantic(original):raise ValueError('Concurrent config change')
        for api_key,db_key in [('settings','settings'),('streamSettings','stream_settings'),('sniffing','sniffing')]:
            if target.json_field(matches[0][api_key])!=target.json_field(legacy[db_key]):raise ValueError('API/DB drift')
        h.save(s.state/'subscription-write-uncertain.json',{'field':'excludeFromSub','inbound_id':legacy['id'],'old':False,'new':True})
        s.call('POST','/inbounds/update/'+str(legacy['id']),dto)
        current=target.configuration(s.database)
        h.save(s.state/'proxy-after-private.json',current)
        if target.semantic(current)!=target.semantic(desired(original)):raise ValueError('Unexpected native write delta')
        after=snapshot(s.database,s.state,'subscriptions-after');proof=check_delta(before,after)
        json_after=snapshot(s.database,s.state,'json-after',True)
        if set(json_before)!=set(json_after):raise ValueError('JSON identity set changed')
        for key,rows in json_before.items():
            if json_after[key]!=[v for v in rows if not json_legacy(v)]:raise ValueError('Unexpected JSON publication delta')
        proof['json_subscriptions_verified']=True
        # Listener deliberately remains enabled; no artificial device acceptance.
        import socket
        for attempt in range(30):
            try:
                with socket.create_connection(('127.0.0.1',32063),timeout=1):break
            except OSError:
                if attempt==29:raise
                time.sleep(.5)
        proof.update({'only_exclude_from_sub_changed':True,'legacy_listener_retained':True,
          'client_credentials_and_bindings_preserved':True,'owner_coordinates_device_refresh':True,
          'end_device_acceptance_claimed':False,'audit_get_is_not_device_refresh':True})
        h.save(s.state/'publication-acceptance.json',proof)
        (s.state/'subscription-write-uncertain.json').unlink()
    finally:s.cleanup()
    proof['temporary_credentials_removed']=True
    h.save(s.state/'receipt.json',proof);return proof


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',type=Path,required=True)
    p.add_argument('--apply',action='store_true');p.add_argument('--approve-session-hash');p.add_argument('--approve-configuration-hash');a=p.parse_args()
    if a.apply:
        if not a.approve_session_hash or not a.approve_configuration_hash:p.error('Both fresh hashes required')
        print(h.canonical(apply(a.state,a.approve_session_hash,a.approve_configuration_hash)))
    else:
        s=native.NativeSession(a.state);plan=s.preview();config=target.configuration(s.database);select(config)
        print(h.canonical({'session_sha256':h.digest(plan),'configuration_sha256':h.digest(config),
          'only_change':'32063 excludeFromSub false->true','listener_retirement':False,'writes':0}))


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Subscription migration stopped; inspect private receipts, never blindly replay.') from None
