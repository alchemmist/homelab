#!/usr/bin/env python3
"""Create one schema-only Kuma service account; leave all existing DB passwords untouched."""
import argparse,base64,fcntl,hashlib,json,os,secrets,subprocess
from pathlib import Path
USER='homelab_kuma_app';SCHEMA='uptime_kuma';STATE=Path('/var/lib/homelab-kuma-account-recovery')
def need(ok,message):
    if not ok:raise RuntimeError(message)
def k(*args,input=None):return subprocess.check_output(['kubectl','-n','uptime-kuma',*args],input=input,text=True,stderr=subprocess.DEVNULL)
def sql(statement):return k('exec','-i','deploy/uptime-kuma-db','--','sh','-c','MYSQL_PWD="$MARIADB_ROOT_PASSWORD" mariadb -h 127.0.0.1 -u root -N --raw',input=statement+'\n').strip()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--approve-plan-hash');a=p.parse_args();os.umask(0o077)
    need(not STATE.is_symlink(),'Unsafe state path');STATE.mkdir(mode=0o700,exist_ok=True);need(STATE.stat().st_uid==0 and not STATE.stat().st_mode&0o077,'Unsafe state ownership')
    with (STATE/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);need(not (STATE/'uncertain.json').exists(),'Uncertain prior write; inspect privately')
        candidate=STATE/'candidate.json'
        if not candidate.exists():candidate.write_text(json.dumps({'password':secrets.token_hex(24)}))
        password=json.loads(candidate.read_text())['password'];need(len(password)==48 and all(x in '0123456789abcdef' for x in password),'Invalid recovery credential')
        secret=json.loads(k('get','secret','uptime-kuma-db','-o','json'));need(set(secret['data'])=={'password','root-password'},'Unknown secret shape')
        db=json.loads(k('get','pods','-l','app=uptime-kuma-db','-o','json'))['items'];need(len(db)==1 and all(x['ready'] for x in db[0]['status']['containerStatuses']),'DB must remain healthy')
        original=sql("SHOW GRANTS FOR 'uptime_kuma'@'%';")
        rows=original.splitlines();need(len(rows)==2 and any('GRANT USAGE ON *.*' in x for x in rows) and any(x == 'GRANT ALL PRIVILEGES ON `uptime\\_kuma`.* TO `uptime_kuma`@`%`' for x in rows) and 'WITH GRANT OPTION' not in original,'Unreviewed original schema privileges')
        exists=sql("SELECT COUNT(*) FROM mysql.user WHERE User='"+USER+"';")=='1'
        root_password=k('exec','deploy/uptime-kuma-db','--','sh','-c','printf %s "$MARIADB_ROOT_PASSWORD"')
        desired={'password':base64.b64encode(password.encode()).decode(),'root-password':base64.b64encode(root_password.encode()).decode()}
        if exists:
            need((STATE/'after.json').exists() and secret['data']==desired,'Foreign/partial service account; stop')
            need((STATE/'before-grants.private').read_text()==original,'Original account drift; stop')
            expected=next(x for x in rows if x.startswith('GRANT ALL PRIVILEGES ON ')).replace(' TO `uptime_kuma`@`%`',' TO `'+USER+'`@`%`')
            own=sql("SHOW GRANTS FOR '"+USER+"'@'%';").splitlines()
            need(len(own)==2 and expected in own and any(x.startswith('GRANT USAGE ON *.*') for x in own) and not any('WITH GRANT OPTION' in x for x in own),'Recovery service-account privilege drift')
            verifier=sql("SELECT authentication_string FROM mysql.user WHERE User='"+USER+"' AND Host='%';")
            need(verifier.upper()=='*'+hashlib.sha1(hashlib.sha1(password.encode()).digest()).hexdigest().upper(),'Recovery account credential drift')
            print(json.dumps({'operations':0,'applied':False,'existing_db_passwords_unchanged':True}));return
        context={'secret_uid':secret['metadata']['uid'],'secret_rv':secret['metadata']['resourceVersion'],'db_uid':db[0]['metadata']['uid'],'original_grants_hash':hashlib.sha256(original.encode()).hexdigest(),'candidate_hash':hashlib.sha256(password.encode()).hexdigest(),'account':USER,'schema':SCHEMA,'tool':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        digest=hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest()
        if a.apply:
            need(a.approve_plan_hash==digest,'Fresh hash approval required');(STATE/'before-secret.json').write_text(json.dumps(secret));(STATE/'before-grants.private').write_text(original);(STATE/'uncertain.json').write_text(json.dumps(context))
            schema_grant=next(x for x in rows if x.startswith("GRANT ALL PRIVILEGES ON "));schema_grant=schema_grant.replace(" TO `uptime_kuma`@`%`", " TO `"+USER+"`@`%`")
            sql("CREATE USER '"+USER+"'@'%' IDENTIFIED BY '"+password+"'; "+schema_grant+";")
            patch=[{'op':'test','path':'/metadata/uid','value':context['secret_uid']},{'op':'test','path':'/metadata/resourceVersion','value':context['secret_rv']},{'op':'replace','path':'/data','value':desired}]
            k('patch','secret','uptime-kuma-db','--type=json','--patch-file=/dev/stdin',input=json.dumps(patch))
            # Validate the NEW account independently without exposing its password in argv.
            k('exec','-i','deploy/uptime-kuma-db','--','sh','-c','IFS= read -r pw; MYSQL_PWD="$pw" mariadb -h 127.0.0.1 -u '+USER+' -D '+SCHEMA+' -Nse "SELECT 1"',input=password+'\n')
            need(sql("SHOW GRANTS FOR 'uptime_kuma'@'%';")==original,'Original account unexpectedly changed')
            after=json.loads(k('get','secret','uptime-kuma-db','-o','json'));need(after['data']==desired and after['metadata']['uid']==context['secret_uid'],'Secret recovery not confirmed')
            now=json.loads(k('get','pod',db[0]['metadata']['name'],'-o','json'));need(now['metadata']['uid']==context['db_uid'] and now['status']['containerStatuses']==db[0]['status']['containerStatuses'],'Unexpected DB lifecycle change')
            (STATE/'after.json').write_text(json.dumps({'account':USER,'schema':SCHEMA,'original_account_unchanged':True,'db_pod_unchanged':True,'secret_uid':context['secret_uid']}));(STATE/'uncertain.json').unlink()
        print(json.dumps({'operations':1,'plan_hash':digest,'applied':a.apply,'new_schema_only_account':USER,'existing_db_passwords_unchanged':True}))
if __name__=='__main__':main()
