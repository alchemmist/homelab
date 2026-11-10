import importlib.util,json,pathlib,hashlib,tarfile,io
import pytest,yaml
ROOT=pathlib.Path(__file__).resolve().parents[1]
def module(name):
 s=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
@pytest.fixture
def ctl(tmp_path,monkeypatch):
 m=module('vpn-transit-failover');monkeypatch.setattr(m,'ROOT',tmp_path)
 p=tmp_path/'config.json';p.write_text(json.dumps({'ws_path':'/test'}));monkeypatch.setattr(m,'CONFIG',p)
 return m,m.Controller()
def test_no_api_only_failover_and_failure_threshold(ctl,monkeypatch):
 m,c=ctl;monkeypatch.setattr(m,'boot_id',lambda:'test-boot');c.save(mode='kubernetes',boot_id='test-boot',grace_until=0)
 calls=[];monkeypatch.setattr(c,'healthy',lambda:False);monkeypatch.setattr(c,'activate',lambda why:calls.append(why))
 for _ in range(3):c.tick()
 assert calls==[];c.tick();assert len(calls)==1
 monkeypatch.setattr(c,'healthy',lambda:True);c.tick();assert c.state['failures']==0

def test_prepared_and_native_are_sticky(ctl,monkeypatch):
 m,c=ctl;calls=[];monkeypatch.setattr(c,'activate',lambda why:calls.append(why));c.tick();assert calls==[]
 m.atomic(c.marker,{'native':True});c.save(mode='native');monkeypatch.setattr(m,'active',lambda _:True);monkeypatch.setattr(c,'healthy',lambda:True)
 c.tick();assert c.state['mode']=='native' and c.state['healthy'];assert calls==[]

def test_uncertain_transition_never_replays(ctl):
 m,c=ctl;c.save(mode='transition-to-kubernetes')
 with pytest.raises(RuntimeError,match='Uncertain'):c.tick()

def test_unknown_port_owner_blocks_native_start(ctl,monkeypatch):
 m,c=ctl;calls=[];monkeypatch.setattr(c,'prerequisites',lambda:None);monkeypatch.setattr(m,'pod_processes',lambda:[])
 monkeypatch.setattr(m,'active',lambda _:False);monkeypatch.setattr(m,'run',lambda a,**kw:calls.append(a))
 monkeypatch.setattr(m.time,'sleep',lambda _:None)
 def occupied():raise OSError('occupied')
 monkeypatch.setattr(m,'free_ports',occupied)
 with pytest.raises(OSError):c.activate('test')
 assert c.marker.exists();assert ['systemctl','stop',m.AGENT] in calls;assert ['systemctl','start',m.NATIVE] not in calls

def test_image_determinism_and_binary_integrity(tmp_path,monkeypatch):
 m=module('vpn-transit-image');binary=tmp_path/'binary';binary.write_bytes(b'fixture static binary');monkeypatch.setattr(m,'SHA',hashlib.sha256(binary.read_bytes()).hexdigest())
 a=tmp_path/'a.tar';b=tmp_path/'b.tar';assert m.build(binary,a)==m.build(binary,b);assert a.read_bytes()==b.read_bytes()
 with tarfile.open(a) as t:
  manifest=json.loads(t.extractfile('manifest.json').read());cfg=json.loads(t.extractfile(manifest[0]['Config']).read());assert cfg['config']['User']=='65532:65532'
 binary.write_bytes(b'changed')
 with pytest.raises(AssertionError):m.build(binary,a)

def test_deployment_single_host_no_api_token_and_native_boot_fence():
 s=(ROOT/'charts/vpn-transit/templates/deployment.yaml').read_text()
 assert 'type: Recreate' in s and 'hostNetwork: true' in s and 'automountServiceAccountToken: false' in s
 assert 'imagePullPolicy: Never' in s and 'homelab.io/bootstrap' in s and 'NET_BIND_SERVICE' in s
 play=(ROOT/'ansible/playbooks/vpn-transit-mesh-runtime.yml').read_text()
 assert 'ExecCondition=/usr/bin/test ! -e' in play and 'ExecCondition=+/usr/bin/test -e' in play
 assert 'state: started' not in play # prepare never steals live ports
 controller=(ROOT/'scripts/vpn-transit-failover.py').read_text()
 assert "AGENT='k3s-agent.service'" in controller and "'k3s.service'" not in controller
 assert 'flock' in controller and 'fsync' in controller and 'free_ports()' in controller
