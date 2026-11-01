"""Root-only effective access checks; emit metadata, never hashes or credentials."""
import json,os,pwd,re,shutil,subprocess,sys
name=sys.argv[1];user=pwd.getpwnam(name)
sshd=shutil.which('sshd') or '/usr/sbin/sshd'
result=subprocess.run([sshd,'-T','-C','user='+name+',host=socrat,addr=10.250.0.7'],text=True,capture_output=True,check=True)
settings={}
for key in ['pubkeyauthentication','usepam']:
    match=re.search(r'\b'+key+r'\s+(yes|no)\b',result.stdout.lower())
    settings[key]=match.group(1) if match else None
key_path=user.pw_dir+'/.ssh/authorized_keys'
with open(key_path) as f:keys=[line for line in f if line.strip() and not line.lstrip().startswith('#')]
policy=subprocess.run(['sudo','-n','-l','-U',name],text=True,capture_output=True,env={**os.environ,'LC_ALL':'C'})
if policy.returncode not in [0,1]:raise SystemExit('Cannot inspect effective sudo policy')
denied=('User '+name+' is not allowed to run sudo on ') in policy.stdout
if not denied and 'may run the following commands' not in policy.stdout:raise SystemExit('Unrecognized effective sudo policy output')
admin_read=subprocess.run(['runuser','-u',name,'--','test','-r','/etc/rancher/k3s/k3s.yaml']).returncode==0
print(json.dumps({'username':name,'pubkeyAuthentication':settings.get('pubkeyauthentication'),
 'usePAM':settings.get('usepam'),'keyCount':len(keys),'hasSudoGrant':not denied,
 'canReadAdminKubeconfig':admin_read,'shell':user.pw_shell}))
