#!/usr/bin/env python3
"""Build deterministic offline scratch image from the exact already-trusted static relay."""
import hashlib,io,json,pathlib,tarfile,sys
SHA='a27e3f95ab6ce270956d0cecd32eda4686a811afc71c64a6a734a3dede14883e'
TAG='localhost/homelab/vpn-transit:'+SHA[:16]
def encode(v):return json.dumps(v,sort_keys=True,separators=(',',':')).encode()
def entry(t,name,data,mode=0o644):
 i=tarfile.TarInfo(name);i.size=len(data);i.mode=mode;i.mtime=0;t.addfile(i,io.BytesIO(data))
def build(binary,output):
 data=pathlib.Path(binary).read_bytes();assert hashlib.sha256(data).hexdigest()==SHA
 buf=io.BytesIO()
 with tarfile.open(fileobj=buf,mode='w') as t:entry(t,'usr/local/bin/xray',data,0o755)
 layer=buf.getvalue();digest=hashlib.sha256(layer).hexdigest();cfg=encode({'architecture':'amd64','os':'linux','config':{'Entrypoint':['/usr/local/bin/xray'],'User':'65532:65532'},'rootfs':{'type':'layers','diff_ids':['sha256:'+digest]}});name=hashlib.sha256(cfg).hexdigest()+'.json'
 with tarfile.open(output,'w') as t:
  entry(t,'layer.tar',layer);entry(t,name,cfg);entry(t,'manifest.json',encode([{'Config':name,'RepoTags':[TAG],'Layers':['layer.tar']}]))
 return {'tag':TAG,'binary_sha256':SHA,'archive_sha256':hashlib.sha256(pathlib.Path(output).read_bytes()).hexdigest()}
if __name__=='__main__':print(json.dumps(build(sys.argv[1],sys.argv[2])))
