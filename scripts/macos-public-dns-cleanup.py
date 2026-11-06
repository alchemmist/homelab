#!/usr/bin/env python3
"""Retire exact owned per-domain resolvers/wiki restorer; never modify global DNS/VPN."""
import argparse,datetime,hashlib,json,os,plistlib,shutil,subprocess
from pathlib import Path
LABEL='xyz.alchemmist.wiki-resolver';STATE=Path('/var/db/homelab-public-dns-cleanup')
PRIVATE='nameserver 10.250.0.2\nnameserver 10.250.0.3\nnameserver 10.250.0.1\ntimeout {timeout}\noptions attempts:1\n'
PUBLIC='nameserver 1.1.1.1\nnameserver 9.9.9.9\ntimeout 2\noptions attempts:2\n'
DOMAINS=['socrat.alchemmist.xyz','0.socrat.alchemmist.xyz','1.socrat.alchemmist.xyz','2.socrat.alchemmist.xyz','grafana.socrat.alchemmist.xyz','llm.socrat.alchemmist.xyz','litellm.socrat.alchemmist.xyz','auth.socrat.alchemmist.xyz','netbird.socrat.alchemmist.xyz','netbird-relay-vps.socrat.alchemmist.xyz','n8n.socrat.alchemmist.xyz','wiki.alchemmist.xyz']
PLIST=Path('/Library/LaunchDaemons')/(LABEL+'.plist');SCRIPT=Path('/usr/local/libexec/socrat-wiki-resolver');MARKER=Path('/var/db/socrat-wiki-resolver-owned')
def need(ok,message):
    if not ok:raise RuntimeError(message)
def run(argv,**kwargs):return subprocess.run(argv,capture_output=True,check=False,**kwargs)
def loaded():
    r=run(['/bin/launchctl','print','system/'+LABEL]);need(r.returncode==0 or b'Could not find service' in r.stderr,'Cannot establish owned job status');return r.returncode==0

def baseline(expected_pid):
    r=run(['/usr/sbin/scutil'],input=b'show State:/Network/Global/DNS\nquit\n');need(r.returncode==0,'Cannot read global DNS baseline')
    p=run(['/bin/ps','-axo','pid=,comm=']);need(p.returncode==0,'Cannot inspect VPN process identity')
    vpns=[line.strip().decode() for line in p.stdout.splitlines() if b'Tunnelblick.app/' in line and b'/openvpn' in line]
    need(any(x.split()[0]==str(expected_pid) for x in vpns),'Original mandatory Tunnelblick process is not present; stop')
    return {'global_dns_sha256':hashlib.sha256(r.stdout).hexdigest(),'tunnelblick_processes':vpns}

def fingerprint(path):
    need(path.is_file() and not path.is_symlink(),'Unsafe owned-file type')
    s=path.stat();need(s.st_uid==0 and not s.st_mode&0o022,'Unsafe owned-file permissions')
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'mode':s.st_mode&0o777,'uid':s.st_uid,'gid':s.st_gid}

def files():
    selected=[]
    directory=Path('/etc/resolver');need(not directory.is_symlink(),'Unsafe resolver directory')
    for name in DOMAINS:
        path=directory/name
        if not path.exists() and not path.is_symlink():continue
        item=fingerprint(path);text=path.read_text()
        if name=='wiki.alchemmist.xyz':
            need(text in ['nameserver '+ip+'\ntimeout 1\noptions attempts:1\n' for ip in ['10.250.0.1','10.250.0.3','10.250.0.2']] and MARKER.exists(),'Foreign wiki resolver')
        elif name in ['auth.socrat.alchemmist.xyz','netbird.socrat.alchemmist.xyz','netbird-relay-vps.socrat.alchemmist.xyz']:
            need(text=='# NetBird/Auth bootstrap must not depend on the private VPN DNS path.\n'+PUBLIC,'Foreign bootstrap resolver')
        elif name=='n8n.socrat.alchemmist.xyz':need(text=='# Public n8n HTTPS must not depend on private VPN DNS. Authentik remains required.\n'+PUBLIC,'Foreign n8n resolver')
        else:need(text==PRIVATE.format(timeout=1 if name.startswith('grafana.') else 6),'Foreign private resolver')
        selected.append(item)
    if PLIST.exists():
        expected={'Label':LABEL,'ProgramArguments':[str(SCRIPT)],'RunAtLoad':True,'StartInterval':10,'ProcessType':'Background'}
        need(plistlib.loads(PLIST.read_bytes())==expected,'Foreign launch daemon')
        selected.append(fingerprint(PLIST))
    if SCRIPT.exists():
        repo=Path(__file__).resolve().parents[1]/'ansible/roles/wiki_editor_client/files/wiki-editor-resolver.sh'
        expected=repo.read_text().replace('wiki.socrat.alchemmist.xyz','wiki.alchemmist.xyz')
        need(SCRIPT.read_text()==expected,'Foreign restorer script')
        selected.append(fingerprint(SCRIPT))
    if MARKER.exists():need(MARKER.read_bytes()==b'','Foreign ownership marker');selected.append(fingerprint(MARKER))
    return selected

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--expected-tunnelblick-pid',type=int,required=True);p.add_argument('--apply',action='store_true');p.add_argument('--approve-plan-hash');a=p.parse_args();os.umask(0o077)
    before=baseline(a.expected_tunnelblick_pid);owned=files();active=loaded();need(not active or (PLIST.exists() and SCRIPT.exists()),'Orphan owned job; stop')
    context={'files':owned,'loaded':active,'vpn':before,'tool':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()};digest=hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest()
    if a.apply and (owned or active):
        need(os.geteuid()==0,'macOS administrator approval required');need(a.approve_plan_hash==digest,'Fresh exact plan approval required')
        need(not STATE.is_symlink(),'Unsafe backup state');STATE.mkdir(mode=0o700,exist_ok=True);need(STATE.stat().st_uid==0 and not STATE.stat().st_mode&0o077,'Unsafe backup permissions')
        need(not list(STATE.glob('*/uncertain.json')),'Prior incomplete cleanup; inspect private receipts')
        receipt=STATE/datetime.datetime.now(datetime.UTC).strftime('%Y%m%dT%H%M%S.%fZ');receipt.mkdir(mode=0o700)
        (receipt/'before.json').write_text(json.dumps(context));(receipt/'uncertain.json').write_text(json.dumps({'plan_hash':digest}))
        for item in owned:
            path=Path(item['path']);dest=receipt/'files'/path.relative_to('/');dest.parent.mkdir(mode=0o700,parents=True,exist_ok=True);shutil.copy2(path,dest)
            need(hashlib.sha256(dest.read_bytes()).hexdigest()==item['sha256'],'Backup verification failed')
        if active:
            r=run(['/bin/launchctl','bootout','system/'+LABEL]);need(r.returncode==0 and not loaded(),'Owned job not stopped; do not delete its files')
        need(baseline(a.expected_tunnelblick_pid)==before,'VPN/global DNS changed; stop')
        for item in owned:
            path=Path(item['path']);need(fingerprint(path)==item,'Owned file changed during approval; stop');path.unlink()
        need(baseline(a.expected_tunnelblick_pid)==before and not loaded(),'VPN/global DNS invariant failed')
        (receipt/'after.json').write_text(json.dumps({'removed':[x['path'] for x in owned],'global_dns_unchanged':True,'tunnelblick_processes_unchanged':True,'no_cache_flush':True}));(receipt/'uncertain.json').unlink()
    print(json.dumps({'operations':len(owned)+int(active),'plan_hash':digest,'applied':bool(a.apply and (owned or active)),'resolver_files':sum(x['path'].startswith('/etc/resolver/') for x in owned),'owned_daemon_loaded':active,'global_dns_and_vpn_changes':False}))
if __name__=='__main__':main()
