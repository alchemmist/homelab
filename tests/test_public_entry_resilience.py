import copy
import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch
import json
import ssl
import pytest

ROOT=Path(__file__).parents[1]
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/file)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
h=load('entry_health','public-entry-health.py');p=load('entry_plan','public-entry-failover-plan.py')
REQUIRED={'home':['external-a','external-b'],'vps':['home-isp','external-a']}


def batch(n,home=True,vps=True,now=None):
    return {'round':n,'observations':[{'entry':e,'vantage':v,'checked_at':now or n*30,'backend_ok':home if e=='home' else vps,'local_only':False} for e in p.ENTRIES for v in REQUIRED[e]]}


def test_three_failures_withdraw_and_three_passes_restore():
    s=p.initial(['home','vps'])
    for n in [1,2]:
        r=p.plan(s,batch(n,vps=False),REQUIRED,n*30);s=r['state'];assert s['published']==['home','vps']
    r=p.plan(s,batch(3,vps=False),REQUIRED,90);s=r['state'];assert s['published']==['home']
    for n in [4,5]:
        s=p.plan(s,batch(n),REQUIRED,n*30)['state'];assert s['published']==['home']
    r=p.plan(s,batch(6),REQUIRED,180);assert r['state']['published']==['home','vps']
    assert r['writes'] is False and r['ready_to_publish'] is False


def test_partition_never_silently_means_healthy_or_global_down():
    s=p.initial(['home','vps']);b=batch(1);b['observations'][-1]['backend_ok']=False
    r=p.plan(s,b,REQUIRED,30)
    assert r['decision']=='hold_review' and r['observations']['vps']=='partitioned'
    assert r['state']['published']==s['published'] and s==p.initial(['home','vps'])


@pytest.mark.parametrize('change',[lambda b:b['observations'].pop(),lambda b:b['observations'][0].update(local_only=True),lambda b:b['observations'][0].update(checked_at=-1000),lambda b:b['observations'][0].update(checked_at=9999)])
def test_missing_local_stale_future_hold(change):
    b=batch(1);change(b);r=p.plan(p.initial(['home','vps']),b,REQUIRED,30)
    assert r['decision']=='hold_review' and r['state']['published']==['home','vps']


def test_both_down_never_publish_empty():
    s=p.initial(['home','vps'])
    for n in [1,2,3]:r=p.plan(s,batch(n,False,False),REQUIRED,n*30);s=r['state']
    assert s['published']==['home','vps'] and r['observations']['publication']=='would_be_empty'


def test_duplicate_idempotence_and_no_reused_sample_streak():
    b=batch(1,vps=False);s=p.plan(p.initial(['home','vps']),b,REQUIRED,30)['state']
    assert p.plan(s,b,REQUIRED,30)['state']==s
    replay=copy.deepcopy(b);replay['round']=2
    result=p.plan(s,replay,REQUIRED,31)
    assert result['observations']['vps']=='reused_evidence'
    assert result['state']['streaks']['vps']['down']==0
    changed=copy.deepcopy(b);changed['observations'][0]['backend_ok']=False
    with pytest.raises(ValueError):p.plan(s,changed,REQUIRED,30)
    with pytest.raises(ValueError):p.plan(s,batch(0),REQUIRED,30)


def test_authorities_with_same_shared_evidence_cannot_disagree():
    s=p.initial(['home','vps']);b=batch(1)
    assert p.plan(s,b,REQUIRED,30)==p.plan(copy.deepcopy(s),copy.deepcopy(b),copy.deepcopy(REQUIRED),30)
    assert b==batch(1)


def test_single_vantage_and_duplicate_row_rejected():
    with pytest.raises(ValueError):p.plan(p.initial(['home']),batch(1),{'home':['one'],'vps':['one']},30)
    b=batch(1);b['observations'].append(copy.deepcopy(b['observations'][0]))
    with pytest.raises(ValueError):p.plan(p.initial(['home']),b,REQUIRED,30)


def discovery():
    return {'issuer':h.ISSUER,'authorization_endpoint':'https://'+h.HOST+'/authorize','token_endpoint':'https://'+h.HOST+'/token','jwks_uri':'https://'+h.HOST+'/jwks'}


def test_backend_discovery_not_just_listening_port():
    assert h.valid_discovery(discovery())
    assert not h.valid_discovery({'status':'ok'})
    for value in ['http://'+h.HOST+'/token','https://other/token','https://user:SECRET@'+h.HOST+'/token']:
        d=discovery();d['token_endpoint']=value;assert not h.valid_discovery(d)


def test_certificate_failure_never_counts_as_backend_up():
    with patch.object(h.socket,'create_connection',return_value=Mock()),patch.object(h.ssl,'create_default_context') as ctx:
        ctx.return_value.wrap_socket.side_effect=ssl.SSLCertVerificationError('SECRET')
        r=h.probe('vps','home')
    assert r['tcp_ok'] and not r['tls_ok'] and not r['backend_ok']
    assert 'SECRET' not in json.dumps(r) and r['failure_kind']=='tls_certificate'


def test_success_preserves_sni_host_and_marks_self_probe_local_only():
    response=Mock();response.status=200;response.read.return_value=json.dumps(discovery()).encode();tls=Mock()
    with patch.object(h.socket,'create_connection'),patch.object(h.ssl,'create_default_context') as ctx,patch.object(h.http.client,'HTTPResponse',return_value=response):
        ctx.return_value.wrap_socket.return_value=tls;r=h.probe('home','home')
        assert ctx.return_value.wrap_socket.call_args.kwargs['server_hostname']==h.HOST
    assert r['backend_ok'] and r['local_only']
    assert ('Host: '+h.HOST).encode() in tls.sendall.call_args.args[0]
    assert b'Authorization' not in tls.sendall.call_args.args[0]
    assert response.read.call_args.args==(65537,)
