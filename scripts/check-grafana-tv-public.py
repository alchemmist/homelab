#!/usr/bin/env python3
"""Focused public TV acceptance at both entrances; no user/admin credentials."""
import argparse, hashlib, json, subprocess
from pathlib import Path
from urllib.parse import urlsplit

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url-file',required=True,help='Private fetched fully-url.json; token is not logged')
    a=p.parse_args();url=json.loads(Path(a.url_file).read_text())['startURL'];u=urlsplit(url)
    assert u.scheme=='https' and u.hostname=='grafana.socrat.alchemmist.xyz' and u.path.startswith('/public-dashboards/')
    token=u.path.split('/')[2];assert len(token)==32 and all(c in '0123456789abcdef' for c in token)
    expected_js=hashlib.sha256((Path(__file__).resolve().parents[1]/'deploy/platform/grafana/public-entry/files/traffic-light-inset.js').read_bytes()).hexdigest()
    passed=0
    for ip in ['109.173.40.247','109.120.141.60']:
        def check(name,path,status,body=None,headers=(),predicate=None):
            nonlocal passed
            cmd=['curl','--silent','--show-error','--max-time','25','--resolve',f'grafana.socrat.alchemmist.xyz:443:{ip}',f'https://grafana.socrat.alchemmist.xyz{path}','--write-out','\n%{http_code}']
            if body is not None:cmd+=['-H','Content-Type: application/json','--data',json.dumps(body)]
            for h in headers:cmd+=['-H',h]
            r=subprocess.run(cmd,capture_output=True,check=True);data,code=r.stdout.rsplit(b'\n',1)
            assert int(code)==status and (predicate is None or predicate(data)),f'{ip}: {name} failed ({code.decode()}); URL/body intentionally not logged'
            print(f'PASS {ip}: {name} ({status})');passed+=1
        check('shared dashboard HTML',u.path+'?'+u.query,200,headers=['Accept: text/html'],predicate=lambda b:b'/_socrat/traffic-light-inset.js' in b)
        check('exact served TV presentation asset','/_socrat/traffic-light-inset.js',200,predicate=lambda b:hashlib.sha256(b).hexdigest()==expected_js)
        check('only approved dashboard metadata','/api/public/dashboards/'+token,200,predicate=lambda b:json.loads(b)['dashboard']['uid']=='socrat-traffic-light' and not json.loads(b)['meta'].get('canEdit',False))
        for name,path in [('search','/api/search'),('admin settings','/api/admin/settings'),('ordinary dashboard API','/api/dashboards/uid/socrat-traffic-light')]:check('anonymous '+name+' denied',path,401)
        check('arbitrary datasource API denied','/api/ds/query',401,body={})
        check('local password login blocked','/login',403,body={'user':'invalid','password':'invalid'})
        check('Basic auth blocked','/api/search',403,headers=['Authorization: Basic aW52YWxpZDppbnZhbGlk'])
        check('metrics not published','/metrics',404)
        check('normal dashboard still gated','/d/socrat-traffic-light',302)
        check('unknown public share denied','/api/public/dashboards/'+'0'*32,404)
    print(json.dumps({'passed':passed,'scope':'focused two-IP forced-routing, not independent external provider'}))
if __name__=='__main__':main()
