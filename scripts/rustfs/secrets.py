#!/usr/bin/env python3
"""Render dedicated Secret manifests into private files; never apply or print them."""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--private-dir',type=Path,required=True);a=p.parse_args();d=a.private_dir
    spec=importlib.util.spec_from_file_location('bootstrap',Path(__file__).with_name('bootstrap.py'))
    b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
    st=d.lstat()
    if not d.is_dir() or d.is_symlink() or st.st_uid!=os.getuid() or st.st_mode & 0o077: raise ValueError('private directory required')
    b.private(d/'storage.json'); b.private(d/'rustfs-client.json')
    storage=json.loads((d/'storage.json').read_text());client=json.loads((d/'rustfs-client.json').read_text())
    if any(len({storage[x][field] for x in ('root','reader','writer')})!=3 for field in ('access','secret')):
        raise ValueError('separate identities and secrets required')
    objects=[]
    for role in ('root','reader','writer'):
        # Writer is held separately for later SPI activation; never mount now.
        values={'access-key':storage[role]['access'],'secret-key':storage[role]['secret']}
        objects.append(('rustfs-'+role,values))
    objects.append(('rustfs-oidc',{'client-id':client['client_id'],'client-secret':client['client_secret']}))
    for name,values in objects:
        doc={'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':'rustfs'},'type':'Opaque',
             'data':{k:base64.b64encode(v.encode()).decode() for k,v in values.items()}}
        path=d/(name+'.secret.json')
        if path.exists():
            b.private(path)
            if json.loads(path.read_text())!=doc: raise ValueError('existing Secret output mismatch; rotate explicitly')
        else:
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as f: json.dump(doc,f)
    print('Private Secret files prepared. No API calls. Writer remains unmounted.')

if __name__=='__main__':
    try: main()
    except Exception: raise SystemExit('Secret preparation refused; inspect private inputs; nothing printed.')
