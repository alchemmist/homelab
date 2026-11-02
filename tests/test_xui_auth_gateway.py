"""Offline boundary contracts. No cluster, VPN credentials, or live authentication."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]


class XuiGatewayTests(unittest.TestCase):
    def test_native_login_is_not_replaced(self):
        source=(ROOT/'ansible/roles/identity_integrations/files/xui_gateway.py').read_text()
        self.assertNotIn('core/users/',source)
        self.assertNotIn('set_password',source)
        self.assertNotIn('sqlite3',source)
        self.assertIn('Managed identity mismatch',source)
        config=json.loads((ROOT/'deploy/identity/xui-panel.json').read_text())
        self.assertEqual(config['mode'],'forward_single')
        self.assertEqual(config['ownerGroup'],'homelab-owner')

    def test_machine_path_is_not_an_unconditional_api_exception(self):
        conf=(ROOT/'deploy/xui-auth-gateway/nginx.conf').read_text()
        self.assertIn('map "$uri|$http_authorization" $machine_api',conf)
        self.assertIn('/panel/api/',conf)
        self.assertIn('Bearer',conf)
        machine=conf.split('location @machine {',1)[1].split('}',1)[0]
        self.assertIn('proxy_set_header Cookie "";',machine)
        self.assertIn('proxy_set_header Host vpn.alchemmist.xyz;',machine)
        self.assertIn('auth_request /__ak_auth;',conf)
        self.assertIn('location = /__ak_auth {\n   internal;',conf)
        self.assertIn('proxy_cookie_flags ~ secure;',conf)
        self.assertIn('access_log off;',conf)
        self.assertIn('return 302 https://vpn.alchemmist.xyz/outpost.goauthentik.io/start?',conf)

    def test_backend_manifest_is_tokenless_sandboxed_and_pinned(self):
        resources=list(yaml.safe_load_all((ROOT/'deploy/xui-auth-gateway/resources.yaml').read_text()))
        cm=next(r for r in resources if r['kind']=='ConfigMap')
        self.assertEqual(cm['data']['nginx.conf'],(ROOT/'deploy/xui-auth-gateway/nginx.conf').read_text())
        self.assertEqual(base64.b64decode(cm['binaryData']['xui-icon.png']),(ROOT/'deploy/xui-auth-gateway/xui-icon.png').read_bytes())
        dep=next(r for r in resources if r['kind']=='Deployment')
        pod=dep['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertEqual(pod['nodeSelector']['kubernetes.io/hostname'],'socrat-2')
        self.assertNotIn('hostNetwork',pod)
        self.assertTrue(pod['securityContext']['runAsNonRoot'])
        c=pod['containers'][0]
        self.assertIn('@sha256:',c['image'])
        self.assertTrue(c['securityContext']['readOnlyRootFilesystem'])
        self.assertEqual(c['securityContext']['capabilities']['drop'],['ALL'])
        self.assertEqual(dep['spec']['template']['metadata']['annotations']['checksum/config'],hashlib.sha256(cm['data']['nginx.conf'].encode()).hexdigest())
        self.assertEqual({r['kind'] for r in resources},{'ConfigMap','Deployment','Service'})

    def test_icon_is_unmodified_pinned_upstream(self):
        icon=(ROOT/'deploy/xui-auth-gateway/xui-icon.png').read_bytes()
        provenance=json.loads((ROOT/'deploy/xui-auth-gateway/icon-source.json').read_text())
        self.assertEqual(hashlib.sha256(icon).hexdigest(),provenance['sha256'])
        self.assertIn('MHSanaei/3x-ui/',provenance['url'])
        self.assertEqual(json.loads((ROOT/'deploy/identity/xui-panel.json').read_text())['iconSha256'],provenance['sha256'])

    def test_host_guard_is_panel_only_persistent_and_has_no_vpn_restart(self):
        nft=(ROOT/'deploy/xui-auth-gateway-host/rules.nft').read_text()
        self.assertNotIn('flush ruleset',nft)
        self.assertNotIn('hook forward',nft)
        self.assertNotIn('hook output',nft)
        self.assertIn('tcp dport 18082 reject with tcp reset',nft)
        self.assertIn('ip daddr { 127.0.0.1, 10.250.0.2 }',nft)
        unit=(ROOT/'deploy/xui-auth-gateway-host/homelab-xui-panel-auth.service').read_text()
        self.assertIn('Before=network-pre.target k3s.service',unit)
        self.assertIn('CapabilityBoundingSet=CAP_NET_ADMIN',unit)
        self.assertNotIn('ExecStop=',unit)
        job=json.loads(subprocess.check_output(['python3',str(ROOT/'scripts/xui-panel-firewall-job.py')]))
        pod=job['spec']['template']['spec'];self.assertFalse(pod['automountServiceAccountToken'])
        self.assertTrue(pod['hostPID'])
        self.assertEqual(pod['containers'][0]['securityContext']['capabilities']['add'],['SYS_CHROOT'])
        self.assertTrue(pod['containers'][0]['volumeMounts'][0]['readOnly'])
        self.assertNotIn('SYS_ADMIN',str(job))


if __name__=='__main__':unittest.main()


class XuiPublicRoutingTests(unittest.TestCase):
    def render(self, enabled):
        data=subprocess.check_output(['helm','template','traefik-edge',str(ROOT/'charts/traefik-edge'),'-n','traefik-edge','--set','panelGateway.enabled='+str(enabled).lower()],text=True)
        return [r for r in yaml.safe_load_all(data) if r]

    def test_public_vpn_routes_keep_exact_backends_and_do_not_use_gateway(self):
        resources=self.render(True)
        ingress=next(r for r in resources if r['kind']=='Ingress' and r['metadata']['name']=='traefik-edge-vpn')
        paths=ingress['spec']['rules'][0]['http']['paths']
        expected=[r for r in yaml.safe_load((ROOT/'charts/traefik-edge/values.yaml').read_text())['routes'] if r['name']!='panel']
        self.assertEqual(len(paths),len(expected))
        for actual,original in zip(paths,expected):
            self.assertEqual(actual['path'],original['path'])
            self.assertEqual(actual['pathType'],original['pathType'])
            self.assertEqual(actual['backend']['service'],{'name':'traefik-edge-'+original['name'],'port':{'number':original['port']}})
        self.assertEqual(ingress['metadata']['annotations']['traefik.ingress.kubernetes.io/router.priority'],'200')
        panel=next(r for r in resources if r['kind']=='Ingress' and r['metadata']['name']=='traefik-edge-panel-auth')
        self.assertEqual(panel['metadata']['annotations']['traefik.ingress.kubernetes.io/router.priority'],'100')
        self.assertEqual(panel['spec']['rules'][0]['http']['paths'][0]['backend']['service']['name'],'xui-auth-gateway')

    def test_activation_does_not_change_ingress_pod_template_or_listeners(self):
        before=next(r for r in self.render(False) if r['kind']=='Deployment')
        after=next(r for r in self.render(True) if r['kind']=='Deployment')
        self.assertEqual(before,after)
