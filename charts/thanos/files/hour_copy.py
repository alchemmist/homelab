"""Copy confirmed hourly S3 blocks to the local 1h shelf. Never mutate the source."""
import datetime
import hashlib
import hmac
import http.client
import json
import os
import re
import shutil
import ssl
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, urlencode
from xml.etree import ElementTree as ET

ULID = re.compile(r'[0-9A-HJKMNP-TV-Z]{26}')
HOUR = 3600000

class Bucket:
    def __init__(self, cfg):
        self.cfg = cfg
        self.ctx = ssl.create_default_context(cafile=cfg['http_config']['tls_config']['ca_file'])

    def read(self, key='', query=None, *, sink=None, method='GET', absent=False):
        c=self.cfg; now=datetime.datetime.now(datetime.timezone.utc); stamp=now.strftime('%Y%m%dT%H%M%SZ'); day=stamp[:8]
        host=c['endpoint']; path='/'+c['bucket']+'/'+quote(key,safe='/'); q=urlencode(sorted((query or {}).items()),quote_via=quote)
        digest=hashlib.sha256(b'').hexdigest(); hdrs={'host':host,'x-amz-content-sha256':digest,'x-amz-date':stamp}; names=';'.join(hdrs)
        canon='\n'.join([method,path,q,''.join(f'{k}:{v}\n' for k,v in hdrs.items()),names,digest]); scope=day+'/us-east-1/s3/aws4_request'
        sig=('AWS4'+c['secret_key']).encode()
        for part in (day,'us-east-1','s3','aws4_request'): sig=hmac.digest(sig,part.encode(),'sha256')
        message='\n'.join(['AWS4-HMAC-SHA256',stamp,scope,hashlib.sha256(canon.encode()).hexdigest()]); signature=hmac.digest(sig,message.encode(),'sha256').hex()
        hdrs['Authorization']=f'AWS4-HMAC-SHA256 Credential={c["access_key"]}/{scope}, SignedHeaders={names}, Signature={signature}'
        conn=http.client.HTTPSConnection(host,context=self.ctx,timeout=120)
        try:
            conn.request(method,path+('?' + q if q else ''),headers=hdrs);res=conn.getresponse()
            if absent and res.status==404:return None
            if res.status!=200: raise IOError(f'{method} {key}: status {res.status}')
            if sink is None:
                body=res.read(16*1024**2+1)
                if len(body)>16*1024**2: raise ValueError('unexpected metadata size')
                return body
            h=hashlib.sha256();n=0
            while chunk:=res.read(1024**2): sink.write(chunk);h.update(chunk);n+=len(chunk)
            return n,h.hexdigest()
        finally:conn.close()

    def listing(self,prefix='',groups=False):
        q={'list-type':'2','prefix':prefix}; result={}
        if groups:q['delimiter']='/'
        while True:
            root=ET.fromstring(self.read(query=q))
            for item in root.findall('{*}CommonPrefixes' if groups else '{*}Contents'):
                k=item.findtext('{*}Prefix' if groups else '{*}Key');result[k]=0 if groups else int(item.findtext('{*}Size'))
            if root.findtext('{*}IsTruncated')=='false':return result
            tok=root.findtext('{*}NextContinuationToken')
            if not tok or tok==q.get('continuation-token'):raise ValueError('bad continuation')
            q['continuation-token']=tok


def covers(target, source):
    a,b=target['thanos'],source['thanos']; src=set(source['compaction']['sources'])
    return (bool(src) and a.get('labels')==b.get('labels') and a.get('downsample')==b.get('downsample') and target['minTime']<=source['minTime'] and target['maxTime']>=source['maxTime'] and src<=set(target['compaction']['sources']))


def hashes(root):
    out={}
    for f in root.rglob('*'):
        if f.is_symlink():raise ValueError('unexpected symlink')
        if f.is_file():
            with f.open('rb') as r:out[str(f.relative_to(root))]=(f.stat().st_size,hashlib.file_digest(r,'sha256').hexdigest())
    return out


def run(bucket,dest):
    if not dest.is_dir(): raise ValueError('destination not mounted')
    confirmed=0
    for prefix in sorted(bucket.listing(groups=True)):
        uid=prefix.rstrip('/')
        if not ULID.fullmatch(uid):continue
        meta=bucket.read(prefix+'meta.json',absent=True)
        if meta is None:continue  # unfinished upload
        m=json.loads(meta)
        if m['ulid']!=uid:raise ValueError('ULID mismatch')
        if m['thanos']['downsample']['resolution']!=HOUR or m['maxTime']<(time.time()-730*86400)*1000:continue
        if bucket.read(prefix+'deletion-mark.json',method='HEAD',absent=True) is not None:continue
        target=dest/uid
        if (target/'deletion-mark.json').exists():continue
        # Don't recreate an input already compacted into a larger local block.
        if not target.exists() and any(covers(json.loads(f.read_bytes()),m) for f in dest.glob('*/meta.json') if ULID.fullmatch(f.parent.name) and not (f.parent/'deletion-mark.json').exists()):continue
        keys=bucket.listing(prefix); rel={k[len(prefix):]:n for k,n in keys.items()}
        if 'deletion-mark.json' in rel:continue
        if not {'meta.json','index'}<=rel.keys() or not any(k.startswith('chunks/') for k in rel) or any(not re.fullmatch(r'index|meta\.json|chunks/[0-9]+',k) for k in rel):raise ValueError('unexpected block inventory: '+uid)
        if shutil.disk_usage(dest).free<sum(rel.values())+10*2**30:raise IOError('hour shelf headroom too low')
        with tempfile.TemporaryDirectory(prefix='.warm-copy-',dir=dest) as temp:
            stage=Path(temp)/uid;stage.mkdir();expected={}
            for k in sorted(rel,key=lambda k:(k=='meta.json',k)):
                f=stage/k;f.parent.mkdir(exist_ok=True)
                with f.open('xb') as w:
                    expected[k]=bucket.read(prefix+k,sink=w);w.flush();os.fsync(w.fileno())
                if expected[k][0]!=rel[k]:raise IOError('object size mismatch')
            if hashes(stage)!=expected or (stage/'meta.json').read_bytes()!=meta or bucket.listing(prefix)!=keys:raise IOError('block changed during copy')
            if target.exists():
                if hashes(target)!=expected:raise IOError('existing block differs; refusing replacement')
            else:
                # Linux renameat2(RENAME_NOREPLACE): atomic publication, never overwrite.
                import ctypes
                libc=ctypes.CDLL(None,use_errno=True)
                if libc.renameat2(-100,os.fsencode(stage),-100,os.fsencode(target),1)!=0:raise OSError(ctypes.get_errno(),'publication refused')
                fd=os.open(dest,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
            confirmed+=1;print('confirmed hour',uid,'files',len(rel),flush=True)
    print('hourly blocks confirmed',confirmed,'no source mutation',flush=True)

if __name__=='__main__':
    run(Bucket(json.loads(Path('/s3/objstore.yml').read_text())['config']),Path(os.environ['HOUR_DIRECTORY']))
