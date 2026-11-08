import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('panel_session',ROOT/'scripts/vpn-panel-session.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class SessionTests(unittest.TestCase):
    def test_unsafe_name_rejected(self):
        for name in ('install','cli-fallback','vpn83-../x','vpn83-a'):
            with self.assertRaises(ValueError):m.NativeSession('/tmp/'+name)

    def test_collision_refuses_even_preview(self):
        s=m.NativeSession('/tmp/vpn83-20261108-test')
        with patch.object(m,'token_rows',return_value=[{'name':s.names['worker']}]),patch.object(m,'pod_identity') as pod:
            with self.assertRaises(ValueError):s.preview()
            pod.assert_not_called()

    def test_api_paths_and_redirects_are_restricted(self):
        for path in ('/setting/reset','/inbounds/update/1?x=y','/../secret'):
            with self.assertRaises(ValueError):m.request('http://127.0.0.1:18082/base','A'*48,'POST',path,{})
        with self.assertRaises(ValueError):m.NoRedirect().redirect_request(None,None,None,None,None,None)

    def test_wrong_host_refuses_before_token_creation(self):
        s=m.NativeSession('/tmp/vpn83-20261108-host')
        with patch.object(m.socket,'gethostname',return_value='socrat-0'),patch.object(m.subprocess,'run') as run:
            with self.assertRaises(ValueError):s.open('bad')
            run.assert_not_called()

    def test_native_success_and_cleanup_preserve_original_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp).resolve()/'vpn83-20261108-success';s=m.NativeSession(state)
            original={'id':1,'name':'existing','scope':'admin','enabled':1,'token':'untouched-hash','created_at':1,'expires_at':0}
            rows=[original.copy()];calls=[]
            values={'bootstrap':'B'*48,'cleanup':'C'*48,'worker':'W'*48}
            def insert(kind,scope,expires=0):
                row={'id':max([x['id'] for x in rows]+[0])+1,'name':s.names[kind],
                     'scope':scope,'enabled':1,'expires_at':expires,'created_at':2,
                     'token':hashlib.sha256(values[kind].encode()).hexdigest()}
                rows.append(row)
                return {'id':row['id'],'name':row['name'],'scope':scope,'expiresAt':expires,'token':values[kind]}
            def cli(args,**kwargs):
                self.assertIn('-tokenName',args);self.assertIn(s.names['bootstrap'],args)
                self.assertNotIn('existing',args);insert('bootstrap','admin')
                kwargs['stdout'].write('apiToken: '+values['bootstrap']+'\n')
                return type('Result',(),{'returncode':0})()
            def api(base,token,method,path,body=None):
                calls.append((token,method,path,body))
                if path.endswith('/create'):
                    kind=next(k for k in values if s.names[k]==body['name'])
                    self.assertGreater(body['expiresAt'],0)
                    return insert(kind,body['scope'],body['expiresAt'])
                if '/delete/' in path:
                    target=int(path.rsplit('/',1)[1]);row=next(r for r in rows if r['id']==target)
                    self.assertEqual(row['scope'],body['expectedScope']);rows.remove(row);return None
                self.assertEqual(token,values['worker']);return []
            def directory(path):path.mkdir(mode=0o700);return path
            with patch.object(m.socket,'gethostname',return_value='socrat-2'),patch.object(m.os,'geteuid',return_value=0),patch.object(m,'token_rows',side_effect=lambda *args:[x.copy() for x in rows]),patch.object(m,'pod_identity',return_value={'name':'pod','uid':'pinned','image':m.IMAGE}),patch.object(m.h,'inspect',return_value={'configuration_sha256':'cfg'}),patch.object(m.h,'private_directory',side_effect=directory),patch.object(m,'api_path',return_value='http://127.0.0.1:18082/base/panel/api'),patch.object(m.subprocess,'run',side_effect=cli),patch.object(m,'request',side_effect=api):
                approval=m.h.digest(s.preview());s.open(approval)
                self.assertFalse(any(r['name']==s.names['bootstrap'] for r in rows))
                self.assertEqual(s.credentials['worker']['scope'],'node-sync')
                s.call('GET','/inbounds/list')
                with self.assertRaises(ValueError):s.call('POST','/setting/apiTokens/create',{})
                # Ownership mismatch must never delete a credential.
                worker=next(r for r in rows if r['name']==s.names['worker']);old=worker['token'];worker['token']='foreign'
                with self.assertRaises(ValueError):s._owned('worker')
                worker['token']=old
                s.cleanup();s.cleanup()
            self.assertEqual(rows,[original])
            self.assertTrue(json.loads((state/'credential-cleanup.json').read_text())['existing_tokens_unchanged'])
            self.assertFalse((state/'uncertain.json').exists())
            for filename in ('bootstrap.stdout','bootstrap.json','cleanup.json','worker.json'):
                self.assertFalse((state/filename).exists())
            self.assertNotIn('B'*48,json.dumps(json.loads((state/'credential-cleanup.json').read_text())))

    def test_wrong_approval_does_not_invoke_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp).resolve()/'vpn83-20261108-approval';s=m.NativeSession(state)
            def directory(path):path.mkdir(mode=0o700);return path
            with patch.object(m.socket,'gethostname',return_value='socrat-2'),patch.object(m.os,'geteuid',return_value=0),patch.object(m.h,'private_directory',side_effect=directory),patch.object(s,'preview',return_value={'x':1}),patch.object(m.subprocess,'run') as run:
                with self.assertRaises(ValueError):s.open('wrong')
                run.assert_not_called()
            if s.lock:s.lock.close()


class TargetHelperTests(unittest.TestCase):
    def module(self):
        spec=importlib.util.spec_from_file_location('target_apply',ROOT/'scripts/vpn-reality-apply.py')
        result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

    def inbound(self):
        stream={'network':'xhttp','security':'reality','xhttpSettings':{'path':'/','mode':'auto'},
          'realitySettings':{'target':'www.intel.com:443','serverNames':['www.yahoo.com'],
            'privateKey':'PRIVATE_SENTINEL','shortIds':['short-private'], 'settings':{'publicKey':'public-only'}}}
        return {'id':1,'port':32053,'protocol':'vless','enable':True,'streamSettings':json.dumps(stream),
                'settings':'{"clients":[{"id":"client-private","flow":""}]}','clientStats':[{'secret':'sentinel'}]}

    def test_only_target_is_patched_and_stats_not_posted(self):
        module=self.module();before=self.inbound();after=module.api_payload(before)
        self.assertNotIn('clientStats',after)
        self.assertEqual(after['settings'],before['settings'])
        a=json.loads(after['streamSettings']);b=json.loads(before['streamSettings'])
        self.assertEqual(a['realitySettings']['target'],'www.yahoo.com:443')
        b['realitySettings']['target']='www.yahoo.com:443';self.assertEqual(a,b)
        self.assertEqual(json.loads(before['streamSettings'])['realitySettings']['target'],'www.intel.com:443')

    def test_unexpected_sni_or_security_stops(self):
        module=self.module();before=self.inbound();s=json.loads(before['streamSettings']);s['security']='none';before['streamSettings']=json.dumps(s)
        with self.assertRaises(ValueError):module.api_payload(before)

    def test_probe_is_loopback_and_only_allows_public_test_destination(self):
        module=self.module();cfg=module.vless_client(json.loads(self.inbound()['streamSettings']),'new-owned-id',12345)
        self.assertEqual(cfg['inbounds'][0]['listen'],'127.0.0.1')
        self.assertEqual(cfg['outbounds'][0]['protocol'],'blackhole')
        self.assertEqual(cfg['routing']['rules'][0]['domain'],['full:speed.cloudflare.com'])
        self.assertNotIn('PRIVATE_SENTINEL',json.dumps(cfg))
        self.assertEqual(cfg['outbounds'][1]['settings']['vnext'][0]['users'][0]['flow'],'')

    def test_json_formatting_is_not_a_semantic_change(self):
        module=self.module()
        a={'inbounds':[{'id':1,'stream_settings':'{"b":2,"a":1}'}]}
        b={'inbounds':[{'id':1,'stream_settings':'{ "a": 1, "b": 2 }'}]}
        self.assertEqual(module.semantic(a),module.semantic(b))

    def test_modern_nested_json_dto_is_supported_without_legacy_reencoding(self):
        module=self.module();before=self.inbound()
        before['streamSettings']=json.loads(before['streamSettings'])
        before['settings']=json.loads(before['settings'])
        before['sniffing']=None
        after=module.api_payload(before)
        self.assertIsInstance(after['streamSettings'],dict)
        self.assertEqual(after['streamSettings']['realitySettings']['target'],'www.yahoo.com:443')
        self.assertEqual(after['settings'],before['settings'])
        self.assertEqual(before['streamSettings']['realitySettings']['target'],'www.intel.com:443')
        self.assertIsNone(module.json_field(None));self.assertIsNone(module.json_field(''))


class SubscriptionMigrationTests(unittest.TestCase):
    def module(self):
        spec=importlib.util.spec_from_file_location('sub_migrate',ROOT/'scripts/vpn-subscription-migrate.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

    def test_payload_only_excludes_publication(self):
        m=self.module();before={'id':7,'port':32063,'protocol':'vless','enable':True,
         'excludeFromSub':False,'streamSettings':{'network':'xhttp','security':'none'},
         'settings':{'clients':[{'id':'PRESERVE'}]},'clientStats':[]}
        after=m.payload(before,7)
        self.assertTrue(after['enable']);self.assertTrue(after['excludeFromSub'])
        expected=dict(before,excludeFromSub=True);expected.pop('clientStats');self.assertEqual(after,expected)
        self.assertFalse(before['excludeFromSub'])
        with self.assertRaises(ValueError):m.payload(after,7)

    def test_publication_delta_preserves_opaque_imports_and_credentials(self):
        m=self.module();secure='vless://preserved@192.0.2.1:32053?security=reality'
        legacy='vless://preserved@192.0.2.1:32063?security=none';opaque='vpn://opaque-private'
        before={str(i):sorted([secure,legacy,opaque]) for i in range(7)}
        after={k:sorted([secure,opaque]) for k in before}
        self.assertEqual(m.check_delta(before,after)['plaintext_links_removed'],7)
        after['0']=[secure]
        with self.assertRaises(ValueError):m.check_delta(before,after)

    def test_only_reality_random_id_is_normalized(self):
        m=self.module();before={'shortId':'preserve','streamSettings':{'realitySettings':{'shortId':'random','publicKey':'preserve-key'}}}
        after=m.normalize_json(before)
        self.assertEqual(after,{'shortId':'preserve','streamSettings':{'realitySettings':{'publicKey':'preserve-key'}}})
        self.assertEqual(before['streamSettings']['realitySettings']['shortId'],'random')
        self.assertTrue(m.json_legacy({'outbounds':[{'protocol':'vless','settings':{'vnext':[{'port':32063}]}}]}))
        self.assertFalse(m.json_legacy({'outbounds':[{'protocol':'trojan','settings':{'vnext':[{'port':32063}]}}]}))

    def test_native_flat_vless_json_settings_are_detected(self):
        m=self.module()
        self.assertTrue(m.json_legacy({'outbounds':[{'protocol':'vless','settings':{'address':'192.0.2.1','port':32063,'id':'PRESERVE'}}]}))
        self.assertFalse(m.json_legacy({'outbounds':[{'protocol':'vless','settings':{'port':32053}}]}))


class BackendGuardTests(unittest.TestCase):
    def module(self,filename):
        spec=importlib.util.spec_from_file_location('backend_test',ROOT/'scripts'/filename)
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

    def test_exact_owned_guard_and_missing_table_comment_supported(self):
        m=self.module('vpn-backend-guard.py');objects=m.expected();m.validate(objects)
        objects[0]['table']['comment']=m.OWNER;m.validate(objects)
        objects[-1]['rule']['expr'][1]['match']['right']['set'].append(443)
        with self.assertRaises(ValueError):m.validate(objects)

    def test_foreign_owner_and_extra_rule_refused(self):
        m=self.module('vpn-backend-guard.py');objects=m.expected();objects[0]['table']['comment']='foreign'
        with self.assertRaises(ValueError):m.validate(objects)
        objects=m.expected();objects.append({'rule':{'expr':[{'accept':None}]}})
        with self.assertRaises(ValueError):m.validate(objects)

    def test_guard_scope_and_boot_ensure(self):
        m=self.module('vpn-backend-guard.py');text=m.rules()
        self.assertIn('iifname "eth0"',text);self.assertIn('{ 12096, 32087 }',text)
        self.assertIn('ct state established',text);self.assertNotIn('flush',text)
        self.assertNotIn('forward',text);self.assertNotIn(' log ',text)
        self.assertIn('--ensure',m.UNIT);self.assertNotIn('ExecStop=',m.UNIT)

    def test_trojan_probe_uses_fresh_own_secret_and_verified_tls443(self):
        m=self.module('vpn-backend-enforce.py')
        cfg=m.client({'network':'ws','security':'none','wsSettings':{'path':'/owned-test'}},'OWN_FRESH_SECRET',12345)
        self.assertEqual(cfg['inbounds'][0]['listen'],'127.0.0.1')
        proxy=cfg['outbounds'][1];self.assertEqual(proxy['settings']['servers'][0]['port'],443)
        self.assertFalse(proxy['streamSettings']['tlsSettings']['allowInsecure'])
        self.assertEqual(cfg['outbounds'][0]['protocol'],'blackhole')
        self.assertEqual(cfg['routing']['rules'][0]['domain'],['full:speed.cloudflare.com'])

    def test_nft_106_conntrack_membership_uses_in_operator(self):
        m=self.module('vpn-backend-guard.py');expr=m.expected()[2]['rule']['expr'][2]
        self.assertEqual(expr['match']['op'],'in')
        self.assertEqual(expr['match']['right'],'established')


class HomeProbeTests(unittest.TestCase):
    def module(self):
        spec=importlib.util.spec_from_file_location('home_probe',ROOT/'scripts/vpn-home-probe.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

    def test_home_receipt_write_is_private_exclusive(self):
        m=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'proof.json';m.exclusive(p,{'own_fixture':True})
            self.assertEqual(p.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):m.exclusive(p,{'overwrite':True})

    def test_probe_limits_destination_and_avoids_global_network_writes(self):
        text=(ROOT/'scripts/vpn-home-probe.py').read_text()
        self.assertIn('65536',text);self.assertIn('socks5h://127.0.0.1:',text)
        for forbidden in ['ip route add','networksetup','resolvectl dns','sysctl -w']:
            self.assertNotIn(forbidden,text)


class LegacyRetirementTests(unittest.TestCase):
    def module(self):
        spec=importlib.util.spec_from_file_location('retire',ROOT/'scripts/vpn-legacy-retire.py')
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

    def test_watchdog_removes_only_legacy_dependencies(self):
        m=self.module();old={'state_dir':'/var/lib/homelab-vpn-failover','tcp_endpoints':[['127.0.0.1',32063],['127.0.0.1',32053]],
          'listen_ports':[{'protocol':'tcp','port':32063},{'protocol':'tcp','port':443}],
          'native_unit_ports':{'homelab-vpn-primary.service':[{'protocol':'tcp','port':32063},{'protocol':'udp','port':32085}]},
          'failure_threshold':4,'confirmation_checks':2}
        after=m.watchdog_after(old);self.assertEqual(after['tcp_endpoints'],[['127.0.0.1',32053]])
        self.assertEqual(after['listen_ports'],[{'protocol':'tcp','port':443}]);self.assertEqual(after['failure_threshold'],4)
        self.assertEqual(after['native_unit_ports']['homelab-vpn-primary.service'],[{'protocol':'udp','port':32085}])
        self.assertEqual(len(old['tcp_endpoints']),2)
        with self.assertRaises(ValueError):m.watchdog_after(after)

    def test_collector_rewrite_is_narrow_and_not_repeatable(self):
        m=self.module();before='ExecStart=python3 collector --ports 32087,32053,32083,32063 --state PRIVATEPATH'
        after=m.monitoring_after(before);self.assertEqual(after,'ExecStart=python3 collector --ports 32087,32053,32083 --state PRIVATEPATH')
        with self.assertRaises(ValueError):m.monitoring_after(after)

    def test_native_projection_only_disables_excluded_legacy(self):
        m=self.module();old={'inbounds':[{'id':7,'port':32063,'protocol':'vless','enable':1,'exclude_from_sub':1,
          'stream_settings':'{"network":"xhttp","security":"none"}','settings':'{"clients":[{"id":"PRESERVE"}]}'}],
          'clients':[{'id':1,'secret':'PRESERVE'}],'client_inbounds':[{'client_id':1,'inbound_id':7}],'hosts':[{'id':7}]}
        after=m.desired(old);self.assertFalse(after['inbounds'][0]['enable']);self.assertTrue(old['inbounds'][0]['enable'])
        after['inbounds'][0]['enable']=1;self.assertEqual(after,old)
        old['inbounds'][0]['exclude_from_sub']=0
        with self.assertRaises(ValueError):m.desired(old)

    def test_expected_sqlite_enable_flag_keeps_integer_sort_semantics(self):
        m=self.module();old={'inbounds':[{'id':7,'port':32063,'protocol':'vless','enable':1,'exclude_from_sub':1,
          'stream_settings':'{"network":"xhttp","security":"none"}'}]}
        result=m.desired(old);self.assertIs(type(result['inbounds'][0]['enable']),int)
        self.assertEqual(result['inbounds'][0]['enable'],0)
