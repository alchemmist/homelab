#!/usr/bin/env python3
"""Explicit isolated real S3 fixture gate; no incidents, publishing or root keys.
Never invoked by tests/deploy. Requires local operator port-forward and private
machine-only credentials JSON. Leaves fixture intentionally (no Delete grants).
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def main():
    p=argparse.ArgumentParser();p.add_argument('--machine-credentials',type=Path,required=True)
    p.add_argument('--apply-fixture',action='store_true');a=p.parse_args()
    root=Path(__file__).resolve().parents[2]
    b=load(Path(__file__).with_name('bootstrap.py'),'bootstrap');b.private_directory(a.machine_credentials.parent);b.private(a.machine_credentials)
    c=json.loads(a.machine_credentials.read_text())
    if set(c)!={'reader','writer'} or c['reader']['access']==c['writer']['access']:
        raise ValueError('separate machine-only credentials required, no root')
    g=load(root/'services/rustfs_gateway/gateway.py','gateway');http=g.opener()
    if not a.apply_fixture:
        print('No requests: pass --apply-fixture only after foundation approval.');return
    origin='http://127.0.0.1:19000'
    def request(role,method,path,payload=b''):
        url=origin+path;headers=g.sign(method,url,c[role]['access'],c[role]['secret'],payload=payload)
        req=urllib.request.Request(url,method=method,headers=headers,data=payload if method=='PUT' else None)
        try:
            with http.open(req,timeout=15) as response:
                data=response.read(g.MAX_BYTES+1)
                if len(data)>g.MAX_BYTES:raise ValueError('oversized response')
                return response.status,data
        except urllib.error.HTTPError as error:
            try:return error.code,error.read(16384)
            finally:error.close()
    event=hashlib.sha256(b'RustFS foundation isolated fixture v1, not an incident').hexdigest()
    body=b'{"foundation_fixture":true,"incident":false}\n'
    manifest=json.dumps({'format':'socrat-evidence-v2','event_key':event,'artifacts':[
        {'id':'E001','name':'fixture.json','stored_chars':len(body),'sha256':hashlib.sha256(body).hexdigest()}]},sort_keys=True).encode('ascii')
    prefix='/spi-evidence/spi/v1/'+event+'/'+hashlib.sha256(manifest).hexdigest()+'/'
    for filename,content in [('E001-fixture.json',body),('manifest.json',manifest)]:
        path=prefix+filename
        status,old=request('writer','GET',path)
        if status==200:
            if old!=content:raise ValueError('existing deterministic fixture mismatch; no overwrite')
        elif status==404:
            if request('writer','PUT',path,content)[0]!=200:raise ValueError('fixture PUT failed; inspect privately, no blind retry')
        else:raise ValueError('cannot verify fixture absence; no PUT')
        status,received=request('reader','GET',path)
        if status!=200 or received!=content:raise ValueError('reader bytes mismatch')
    cases=[('reader','PUT',prefix+'E001-fixture.json'),('reader','DELETE',prefix+'E001-fixture.json'),
           ('writer','DELETE',prefix+'E001-fixture.json'),('reader','GET','/spi-evidence/not-spi/fixture'),
           ('writer','PUT','/spi-evidence/not-spi/fixture'),('reader','GET','/spi-evidence/'),
           ('writer','GET','/rustfs/admin/v3/info'),('reader','GET','/rustfs/admin/v3/info')]
    for role,method,path in cases:
        status,data=request(role,method,path)
        if status!=403:raise ValueError('negative IAM gate failed; require explicit deny, not 404 or transport failure')
        # XML parsing only, no remote entities/external fetch and no body logging.
        doc=ET.fromstring(data)
        code=next((e.text for e in doc.iter() if e.tag.rsplit('}',1)[-1]=='Code'),None)
        if code not in ('AccessDenied','AllAccessDisabled'):raise ValueError('unexpected denial response')
    print('S3 fixture byte checks and eight explicit denial gates passed. Human SSO/download gates remain separate.')
    print('Fixture browser path: '+prefix.removeprefix('/spi-evidence')+'manifest.json')

if __name__=='__main__':
    try: main()
    except Exception:raise SystemExit('Runtime gate failed; no secret/response body printed. Inspect private state; do not activate SPI.')
