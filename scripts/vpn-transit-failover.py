#!/usr/bin/env python3
"""Node-local Moscow relay watchdog. Never manages control-plane or management relay.
The worker agent is fenced before native start; fallback marker fences its boot.
No API availability-only failover. Native mode is sticky until explicit failback.
"""
import argparse,fcntl,hashlib,json,os,pathlib,signal,socket,ssl,subprocess,time
ROOT=pathlib.Path('/var/lib/homelab-vpn-transit/relay-failover')
CONFIG=pathlib.Path('/etc/homelab-vpn-transit/failover.json')
AGENT='k3s-agent.service';NATIVE='homelab-vpn-transit-native.service'
TCP=(80,443,32053,32083,32084);UDP=(443,32085,32086)
def run(args,timeout=25,check=True):
 p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 if check and p.returncode:raise RuntimeError('Command failed: '+str(args[:3]))
 return p

def atomic(path,value):
 tmp=path.with_suffix('.tmp');data=json.dumps(value,sort_keys=True).encode()
 with tmp.open('wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 os.chmod(tmp,0o600);os.replace(tmp,path)
 fd=os.open(path.parent,os.O_DIRECTORY);os.fsync(fd);os.close(fd)

def boot_id():return pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()

def active(unit):return run(['systemctl','is-active','--quiet',unit],check=False).returncode==0

def free_ports():
 for typ,ports in [(socket.SOCK_STREAM,TCP),(socket.SOCK_DGRAM,UDP)]:
  for port in ports:
   with socket.socket(socket.AF_INET,typ) as s:
    # Match Go TCP listeners: TIME_WAIT is not a live port owner. Never reuse UDP.
    if typ==socket.SOCK_STREAM:s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    s.bind(('0.0.0.0',port))
    if typ==socket.SOCK_STREAM:s.listen(1)
 return True

def identity(pid,cid):
 p=pathlib.Path('/proc')/str(pid)
 if not p.exists():return None
 cg=(p/'cgroup').read_text();assert cid in cg and ('kubepods' in cg or 'cri-containerd' in cg)
 return {'pid':pid,'cid':cid,'start':(p/'stat').read_text().split()[21]}

def pod_processes():
 p=run(['k3s','crictl','--timeout=5s','ps','-o','json'],timeout=9)
 result=[]
 for c in json.loads(p.stdout)['containers']:
  labels=c.get('labels',{})
  if labels.get('io.kubernetes.pod.namespace')!='vpn-transit' or labels.get('io.kubernetes.container.name')!='relay':continue
  v=json.loads(run(['k3s','crictl','--timeout=5s','inspect',c['id']],timeout=9).stdout)
  i=identity(int(v['info']['pid']),c['id'])
  if i:result.append(i)
 return result

def terminate_owned(i):
 pid=i['pid'];now=identity(pid,i['cid'])
 if now is None:return
 assert now==i
 os.kill(pid,signal.SIGTERM)
 for _ in range(50):
  if not pathlib.Path('/proc',str(pid)).exists():return
  time.sleep(.1)
 now=identity(pid,i['cid'])
 if now==i:os.kill(pid,signal.SIGKILL)

def probe(config):
 # Actual TLS/WebSocket path through the relay to NL; no XFF and no credentials.
 for port in (32053,32083,32084):
  with socket.create_connection(('127.0.0.1',port),timeout=2):pass
 with socket.create_connection(('127.0.0.1',443),timeout=3) as s:
  with ssl.create_default_context().wrap_socket(s,server_hostname='vpn.alchemmist.xyz') as t:
   req=('GET '+config['ws_path']+' HTTP/1.1\r\nHost: vpn.alchemmist.xyz\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n')
   t.sendall(req.encode());line=t.recv(1024).split(b'\r\n')[0];assert b' 101 ' in line
 return True

class Controller:
 def __init__(self):
  self.config=json.loads(CONFIG.read_text());self.marker=ROOT/'fallback.active'
  self.state=json.loads((ROOT/'state.json').read_text()) if (ROOT/'state.json').exists() else {'mode':'prepared','failures':0}
 def save(self,**fields):
  self.state.update(fields);atomic(ROOT/'state.json',self.state)
 def receipt(self,action,**fields):
  v={'action':action,'at':time.time(),**fields};atomic(ROOT/(str(time.time_ns())+'-'+action+'.json'),v)
 def healthy(self):
  try:probe(self.config);return True
  except (OSError,AssertionError,ssl.SSLError):return False
 def prerequisites(self):
  assert hashlib.sha256(pathlib.Path('/usr/local/libexec/xray-transit').read_bytes()).hexdigest()==self.config['binary_sha256']
  assert active('homelab-vpn-management-relay.service')
  assert not active('homelab-vpn-transit.service') # retired combined service
  r=run(['ip','route','get','10.250.0.2']).stdout
  assert 'dev wg-socrat' in r and 'src 10.250.0.40' in r
 def activate(self,reason):
  self.prerequisites()
  processes=[]
  try:processes=pod_processes()
  except (RuntimeError,subprocess.TimeoutExpired):
   if active(AGENT):raise
  atomic(self.marker,{'reason':reason,'at':time.time()})
  self.save(mode='transition-to-native',healthy=False)
  run(['systemctl','stop',AGENT],timeout=75);assert not active(AGENT)
  try:processes+=pod_processes()
  except (RuntimeError,subprocess.TimeoutExpired):pass
  unique={i['pid']:i for i in processes}
  for i in unique.values():terminate_owned(i)
  # Unknown owner means STOP, never kill it or start a competing listener.
  for _ in range(30):
   try:free_ports();break
   except OSError:time.sleep(.2)
  free_ports()
  run(['systemctl','start',NATIVE]);assert active(NATIVE)
  for _ in range(15):
   if self.healthy():break
   time.sleep(1)
  assert self.healthy()
  self.save(mode='native',failures=0,healthy=True)
  self.receipt('native-accepted',reason=reason,owned_containers_fenced=len(unique))
 def failback(self):
  self.prerequisites();assert self.marker.exists() and self.state['mode']=='native'
  self.save(mode='transition-to-kubernetes',healthy=False)
  try:
   run(['systemctl','stop',NATIVE]);assert not active(NATIVE);free_ports()
   self.marker.unlink();fd=os.open(ROOT,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
   run(['systemctl','reset-failed',AGENT],check=False)
   run(['systemctl','start',AGENT],timeout=75)
   deadline=time.monotonic()+150
   while time.monotonic()<deadline:
    if self.healthy() and pod_processes():
     assert not active(NATIVE)
     self.save(mode='kubernetes',failures=0,healthy=True);self.receipt('kubernetes-accepted');return
    time.sleep(3)
   raise RuntimeError('Pod data-path recovery deadline exceeded')
  except Exception:
   self.activate('failback failed; native rollback');raise
 def tick(self):
  if self.state['mode']=='prepared':return
  if self.marker.exists():
   ok=active(NATIVE) and self.healthy()
   # A late healthy native relay may outlive activate()'s bounded probe window.
   # Reconcile bookkeeping only: never replay activation, remove the fence or
   # start an agent. Unknown states and unhealthy transitions remain fenced.
   if self.state['mode']=='transition-to-native' and ok:
    if active(AGENT):raise RuntimeError('Agent active during fenced native transition')
    self.prerequisites()
    self.receipt('native-reconciled',reason='native healthy after activation deadline')
    self.save(mode='native',failures=0,healthy=True)
   else:self.save(healthy=ok)
   return
  if self.state['mode']!='kubernetes':raise RuntimeError('Uncertain transition; inspect receipts, do not replay')
  boot=boot_id()
  if self.state.get('boot_id')!=boot:
   self.save(boot_id=boot,grace_until=time.time()+120)
  ok=self.healthy()
  if not ok and time.time()<self.state.get('grace_until',0):return
  if ok:self.save(grace_until=0)
  n=0 if ok else self.state.get('failures',0)+1
  self.save(healthy=ok,failures=n)
  if n>=4:self.activate('four consecutive actual data-path failures')
 def status(self):
  return {**self.state,'native_active':active(NATIVE),'agent_active':active(AGENT),'fallback_marker':self.marker.exists(),'data_path_healthy':self.healthy()}

def main():
 os.umask(0o077);ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
 p=argparse.ArgumentParser();p.add_argument('action',choices=['tick','status','activate','failback']);a=p.parse_args()
 with (ROOT/'lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX | (fcntl.LOCK_NB if a.action=='tick' else 0))
  except BlockingIOError:return
  c=Controller()
  if a.action=='status':print(json.dumps(c.status()))
  elif a.action=='activate':c.activate('explicit controlled activation')
  else:getattr(c,a.action)()
if __name__=='__main__':main()
