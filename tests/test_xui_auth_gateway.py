"""Retired IdP gateway must not reappear or alter VPN transports."""
from pathlib import Path
import subprocess
import yaml
import pytest
ROOT=Path(__file__).resolve().parents[1]

def render(*args):
    return [d for d in yaml.safe_load_all(subprocess.check_output(['helm','template','traefik-edge',str(ROOT/'charts/traefik-edge'),'-n','traefik-edge',*args],text=True)) if d]

def test_native_panel_and_vpn_transports_keep_exact_backends():
    objects=render();route=next(o for o in objects if o['kind']=='Ingress' and o['metadata']['name']=='traefik-edge-vpn')
    values=yaml.safe_load((ROOT/'charts/traefik-edge/values.yaml').read_text())
    paths=route['spec']['rules'][0]['http']['paths']
    assert len(paths)==len(values['routes'])
    for p,v in zip(paths,values['routes']):
        assert p['path']==v['path'] and p['pathType']==v['pathType']
        assert p['backend']['service']=={'name':'traefik-edge-'+v['name'],'port':{'number':v['port']}}
    assert not any(o['metadata']['name']=='traefik-edge-panel-auth' for o in objects)

def test_retired_auth_override_is_rejected():
    with pytest.raises(subprocess.CalledProcessError):render('--set','panelGateway.enabled=true')

def test_retired_controller_cannot_provision_or_apply():
    source=ROOT/'ansible/roles/identity_integrations/files/xui_gateway.py'
    p=subprocess.run(['python3',str(source)],capture_output=True,text=True)
    assert p.returncode!=0 and 'retired' in p.stderr
    assert not (ROOT/'deploy/xui-auth-gateway').exists()
    assert not (ROOT/'deploy/identity/xui-panel.json').exists()

def test_private_backend_firewall_is_not_removed_with_auth_proxy():
    rules=(ROOT/'deploy/xui-auth-gateway-host/rules.nft').read_text()
    assert 'tcp dport 18082 reject with tcp reset' in rules
    assert 'flush ruleset' not in rules and 'hook forward' not in rules
