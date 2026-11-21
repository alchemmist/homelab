#!/usr/bin/env python3
"""Provision only a new dedicated OpenHands Redis credential; never rotate/adopt.
Default GET-only. --apply creates the missing Secret via stdin, never argv/Git.
Does not read or modify Authentik, existing OIDC credentials or Canvas secrets.
"""
import argparse
import base64
import json
import secrets
import subprocess

NAME='openhands-oidc-sessions'
LABELS={'app':NAME,'app.kubernetes.io/managed-by':'homelab-openhands'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    raw=subprocess.check_output(['kubectl','-n','identity','get','secret',NAME,'--ignore-not-found','-o','json'])
    if raw:
        obj=json.loads(raw)
        assert all(obj['metadata'].get('labels',{}).get(k)==v for k,v in LABELS.items()), 'Secret ownership drift; stop'
        data=obj['data'];password=base64.b64decode(data['password']).decode();config=base64.b64decode(data['redis.conf']).decode()
        assert len(password)==64 and all(c in '0123456789abcdef' for c in password), 'Unexpected credential; stop'
        assert config==redis_config(password), 'Redis config drift; stop'
        print('Dedicated session Secret already provisioned; unchanged');return
    if not args.apply:
        print('Would create only identity/'+NAME+'; no existing credential changes');return
    password=secrets.token_hex(32)
    obj={'apiVersion':'v1','kind':'Secret','metadata':{'name':NAME,'namespace':'identity','labels':LABELS},'type':'Opaque','stringData':{'password':password,'redis.conf':redis_config(password)}}
    subprocess.run(['kubectl','create','-f','-'],input=json.dumps(obj),text=True,check=True)


def redis_config(password) -> str:
    return ('bind 0.0.0.0\nport 6379\nprotected-mode yes\nrequirepass '+str(password)+
            '\nsave ""\nappendonly no\nmaxmemory 64mb\nmaxmemory-policy noeviction\ndir /data\nloglevel warning\n')


if __name__=='__main__':main()
