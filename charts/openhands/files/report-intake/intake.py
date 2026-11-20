"""Authenticated report admission only. No GitHub/model/cluster credential or egress."""
import base64, hashlib, hmac, json, re, sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SECTIONS = {'Survivors by area', 'No coverage by area', 'Timeouts'}

def families(body):
    section = None
    for line in body.splitlines():
        if line.startswith('#'):
            section = line.removeprefix('### ').split(' (')[0]
        if section not in SECTIONS:
            continue
        hit = re.fullmatch(r'(?:(\d{1,6}) )?([\wǁ]+(?:\.[\wǁ]+)+)', line.strip())
        if hit and (hit[1] or section == 'Timeouts' and re.search(r'__mutmut_\d+$', hit[2])):
            yield section, hit[2], int(hit[1] or 1)

def ingest(envelope, registry, secret, db):
    raw = base64.b64decode(envelope['raw'], validate=True)
    sig = 'sha256=' + hmac.new(secret, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, envelope['signature']):
        raise PermissionError
    e = json.loads(raw); r = e['repository']; config = registry.get(str(r['id']))
    if not config or r['full_name'] != config['name']:
        raise PermissionError
    i = e.get('issue', {}); label = config['label']
    if not i or e.get('action') not in ('opened','labeled') or i['state'] != 'open' or 'pull_request' in i or label not in {l['name'] for l in i['labels']} or (e['action']=='labeled' and e['label']['name']!=label):
        return {'status':'ignored'}
    if i['user']['id'] not in config['reporters'] or (e['action']=='labeled' and e['sender']['id'] not in config['reporters']):
        return {'status':'ignored_sender'}
    rid, num, body = r['id'], i['number'], i['body'] or ''; digest=hashlib.sha256(body.encode()).hexdigest()
    rows=list(families(body)) if config['adapter']=='mutmut-families-v1' else []
    with closing(sqlite3.connect(db)) as c,c:
        c.execute('create table if not exists reports(repo integer,issue integer,digest text,state text, primary key(repo,issue))');c.execute('create table if not exists cards(repo integer,issue integer,section text,target text,reported integer,state text, primary key(repo,issue,section,target))');prior=c.execute('select digest from reports where repo=? and issue=?',(rid,num)).fetchone()
        if prior:return {'status':'duplicate' if prior==(digest,) else 'changed_report_requires_review'}
        status='queued' if rows else 'unsupported_report';c.execute('insert into reports values(?,?,?,?)',(rid,num,digest,status));c.executemany('insert into cards values(?,?,?,?,?,\'queued\')',[(rid,num,*row) for row in rows]);return {'status':status,'cards':len(rows),'issue':num}

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            n=int(self.headers.get('Content-Length',0));assert self.path=='/intake' and 0<n<300000 and not self.headers.get('Transfer-Encoding');out=ingest(json.loads(self.rfile.read(n)),json.loads(Path('/code/repos.json').read_text()),Path('/auth/key').read_bytes(),'/state/reports.db');code=200
        except PermissionError:code,out=403,{}
        except (ValueError,KeyError,TypeError,AssertionError):code,out=400,{}
        except Exception:code,out=503,{}
        self.send_response(code);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(out).encode())
    def log_message(self,*args):pass
if __name__=='__main__': HTTPServer(('',8091),Handler).serve_forever()
