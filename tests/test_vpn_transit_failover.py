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
 monkeypatch.setattr(c,'healthy',lambda:True);c.tick();assert c.state['failures']==0 and c.state['grace_until']==0

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


def test_tcp_time_wait_reuse_never_allows_a_live_owner_or_udp_reuse():
    m=module('vpn-transit-failover')
    import socket
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as owner:
        owner.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        owner.bind(('0.0.0.0',0));owner.listen();port=owner.getsockname()[1]
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as challenger:
            challenger.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            with pytest.raises(OSError):
                challenger.bind(('0.0.0.0',port));challenger.listen(1)
    source=(ROOT/'scripts/vpn-transit-failover.py').read_text()
    assert 'if typ==socket.SOCK_STREAM:s.setsockopt' in source


def test_machine_https_exception_is_exact_not_a_human_acl_relaxation():
    host=yaml.safe_load((ROOT/'ansible/inventory/host_vars/socrat-2.yml').read_text())
    defaults=yaml.safe_load((ROOT/'ansible/roles/wireguard_private_web/defaults/main.yml').read_text())
    assert host['wireguard_private_web_passthrough_sources']==['10.250.0.40']
    assert defaults['wireguard_private_web_passthrough_sources']==[]
    assert host['public_dns_extra_listen']==['10.250.0.2@5354']


def test_late_native_health_reconciles_without_replaying_lifecycle(ctl, monkeypatch):
    m,c=ctl; m.atomic(c.marker,{'reason':'four failures'})
    c.save(mode='transition-to-native',failures=4,healthy=False)
    monkeypatch.setattr(m,'active',lambda unit:unit==m.NATIVE)
    monkeypatch.setattr(c,'healthy',lambda:True)
    calls=[];monkeypatch.setattr(c,'prerequisites',lambda:calls.append('verified'))
    monkeypatch.setattr(m,'run',lambda *a,**kw:pytest.fail('no lifecycle replay'))
    c.tick()
    assert c.state['mode']=='native' and c.state['failures']==0 and c.state['healthy']
    assert c.marker.exists() and calls==['verified']
    receipts=list(m.ROOT.glob('*-native-reconciled.json'));assert len(receipts)==1
    c.tick();assert len(list(m.ROOT.glob('*-native-reconciled.json')))==1


@pytest.mark.parametrize('native,healthy',[(False,True),(True,False),(False,False)])
def test_unhealthy_native_transition_stays_fenced(ctl,monkeypatch,native,healthy):
    m,c=ctl;m.atomic(c.marker,{});c.save(mode='transition-to-native',failures=4)
    monkeypatch.setattr(m,'active',lambda unit:native if unit==m.NATIVE else False)
    monkeypatch.setattr(c,'healthy',lambda:healthy)
    monkeypatch.setattr(c,'prerequisites',lambda:pytest.fail('no transition acceptance'))
    c.tick();assert c.state['mode']=='transition-to-native' and not c.state['healthy']
    assert c.marker.exists()


def test_late_native_acceptance_refuses_active_agent(ctl,monkeypatch):
    m,c=ctl;m.atomic(c.marker,{});c.save(mode='transition-to-native')
    monkeypatch.setattr(m,'active',lambda unit:True);monkeypatch.setattr(c,'healthy',lambda:True)
    with pytest.raises(RuntimeError,match='Agent active'):c.tick()
    assert c.state['mode']=='transition-to-native' and c.marker.exists()


def test_late_native_acceptance_requires_prerequisites(ctl,monkeypatch):
    m,c=ctl;m.atomic(c.marker,{});c.save(mode='transition-to-native')
    monkeypatch.setattr(m,'active',lambda unit:unit==m.NATIVE);monkeypatch.setattr(c,'healthy',lambda:True)
    def refuse():raise RuntimeError('prerequisite drift')
    monkeypatch.setattr(c,'prerequisites',refuse)
    with pytest.raises(RuntimeError,match='prerequisite drift'):c.tick()
    assert c.state['mode']=='transition-to-native' and c.marker.exists()


def test_native_primary_requires_healthy_fenced_native_and_is_sticky(ctl,monkeypatch):
 m,c=ctl;monkeypatch.setattr(c,'prerequisites',lambda:None)
 monkeypatch.setattr(m,'active',lambda unit:unit==m.NATIVE)
 monkeypatch.setattr(c,'healthy',lambda:True)
 with pytest.raises(AssertionError):c.promote()
 m.atomic(c.marker,{'native':True});c.save(mode='native');c.promote()
 assert c.state['mode']=='native-primary' and c.marker.exists()
 c.tick();assert c.state['mode']=='native-primary'
 with pytest.raises(AssertionError):c.failback()
 with pytest.raises(AssertionError):c.activate('accidental fallback replay')
 c.demote();assert c.state['mode']=='native' and c.marker.exists()


def test_unhealthy_primary_never_restarts_agent_or_releases_fence(ctl,monkeypatch):
 m,c=ctl;monkeypatch.setattr(c,'prerequisites',lambda:None)
 m.atomic(c.marker,{'native':True});c.save(mode='native-primary')
 monkeypatch.setattr(m,'active',lambda unit:unit==m.NATIVE)
 monkeypatch.setattr(c,'healthy',lambda:False)
 monkeypatch.setattr(m,'run',lambda *a,**k:pytest.fail('must not change lifecycle'))
 c.tick();assert not c.state['healthy'] and c.marker.exists()
 with pytest.raises(AssertionError):c.demote()
