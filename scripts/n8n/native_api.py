"""Same-instance native API via approved private SSH; key only stdin/in memory."""
import json
from pathlib import Path
import re
import shlex
import subprocess

JS = r"""let b='';process.stdin.on('data',x=>b+=x);process.stdin.on('end',async()=>{try{
const x=JSON.parse(b);const r=await fetch('http://127.0.0.1:5678/api/v1/'+x.path,
 {method:x.method,redirect:'error',headers:{'X-N8N-API-KEY':x.key,'Content-Type':'application/json'},
 body:x.body===null?undefined:JSON.stringify(x.body),signal:AbortSignal.timeout(20000)});
if(!r.ok)throw Error('HTTP_'+r.status);const t=await r.text();if(t.length>4194304)throw Error('SIZE_BOUND');
console.log(t||'{}');}catch(e){console.error(/^HTTP_[0-9]+$|^SIZE_BOUND$/.test(e.message)?e.message:'NATIVE_API_FAILED');process.exitCode=1;}});"""

def api(method, path, body=None):
    if method not in {'GET','POST','PUT'} or not re.fullmatch(r'workflows(?:/[A-Za-z0-9_-]+(?:/activate)?)?(?:\?limit=250)?',path):
        raise ValueError('Unsupported API operation')
    payload={'method':method,'path':path,'body':body,'key':(Path.home()/'.config/n8n/api-key').read_text().strip()}
    p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','socrat-0',
      'kubectl -n automation exec -i deployment/n8n -- node -e '+shlex.quote(JS)],
      input=json.dumps(payload).encode(),capture_output=True,timeout=35)
    if p.returncode or len(p.stdout)>4194304:
        raise RuntimeError('Native n8n API failed; stop and inspect private receipts, no automatic retry')
    return json.loads(p.stdout)
