#!/usr/bin/env python3
"""Explicit ephemeral loopback-only path test; no production credential changes."""
import argparse,base64,hashlib,json,secrets,shlex,subprocess
NS='syncthing'
def k(*args):return subprocess.check_output(['kubectl','-n',NS,*args],text=True)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true');a=p.parse_args()
 if not a.run:print('Audit only: --run starts a temporary loopback-only nginx clone and removes it afterward');return
 before=k('get','secret','syncthing-basic-auth','-o','json');old=json.loads(before)['data']
 pods=json.loads(k('get','pods','-l','app=public-web-syncthing-proxy','-o','json'))['items']
 if len(pods)!=1:raise RuntimeError('Ambiguous policy pod')
 pod=pods[0]['metadata']['name'];config=k('exec',pod,'--','cat','/etc/nginx/nginx.conf')
 for marker in ['pid /tmp/nginx.pid;','listen 8080;','listen 8081;','/etc/nginx/basic/users']:
  if marker not in config:raise RuntimeError('Unexpected policy configuration')
 test=config.replace('pid /tmp/nginx.pid;','pid /tmp/nginx-acceptance.pid;').replace('listen 8080;','listen 127.0.0.1:18080;').replace('listen 8081;','listen 127.0.0.1:18081;').replace('/etc/nginx/basic/users','/tmp/nginx-acceptance.users')
 password=secrets.token_urlsafe(32);auth=base64.b64encode(('acceptance:'+password).encode()).decode()
 script="""set -eu
 test ! -e /tmp/nginx-acceptance.pid
 umask 077
 trap 'nginx -s quit -c /tmp/nginx-acceptance.conf >/dev/null 2>&1 || true; rm -f /tmp/nginx-acceptance.conf /tmp/nginx-acceptance.users /tmp/nginx-acceptance.body /tmp/nginx-acceptance.health' EXIT
"""
 script+='printf %s '+shlex.quote(test)+' > /tmp/nginx-acceptance.conf\n'
 script+='printf "%s\\n" '+shlex.quote('acceptance:{PLAIN}'+password)+' > /tmp/nginx-acceptance.users\n'
 script+='nginx -t -c /tmp/nginx-acceptance.conf >/dev/null 2>&1\nnginx -c /tmp/nginx-acceptance.conf\n'
 script+='tries=0; until wget -q -T 3 --header '+shlex.quote('Authorization: Basic '+auth)+' -O /dev/null http://127.0.0.1:18080/sync/rest/noauth/health 2>/dev/null; do tries=$((tries+1)); test $tries -lt 6; sleep 1; done\n'
 script+='wget -q --header '+shlex.quote('Authorization: Basic '+auth)+' -O /tmp/nginx-acceptance.body http://127.0.0.1:18080/sync/\n'
 script+="grep -qi syncthing /tmp/nginx-acceptance.body\n"
 script+='wget -q --header '+shlex.quote('Authorization: Basic '+auth)+' -O /tmp/nginx-acceptance.health http://127.0.0.1:18080/sync/rest/noauth/health\n'
 script+="grep -q OK /tmp/nginx-acceptance.health\n"
 script+='printf "Legacy /sync/ HTML and native health through prefix rewrite: passed\\n"\n'
 subprocess.run(['kubectl','-n',NS,'exec','-i',pod,'--','sh'],input=script,text=True,check=True)
 after=json.loads(k('get','secret','syncthing-basic-auth','-o','json'))['data']
 if old!=after:raise RuntimeError('Existing BasicAuth credential changed; stop')
 print('Existing production BasicAuth bytes unchanged; test credential was loopback-only')
if __name__=='__main__':main()
