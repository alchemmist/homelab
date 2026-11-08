import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

inventory = load('inventory_test', 'vpn-hardening-inventory.py')
audit = load('counter_test', 'vpn-backend-audit.py')


class HardeningTests(unittest.TestCase):
    def fixture(self, path):
        con = sqlite3.connect(path)
        con.executescript('''
        CREATE TABLE inbounds(id INTEGER, port INTEGER, protocol TEXT, enable INTEGER,
          stream_settings TEXT, settings TEXT, up INTEGER, down INTEGER, last_traffic_reset_time INTEGER);
        CREATE TABLE clients(id INTEGER, secret TEXT);
        CREATE TABLE client_inbounds(client_id INTEGER, inbound_id INTEGER);
        CREATE TABLE hosts(id INTEGER, address TEXT);
        INSERT INTO clients VALUES(1,'PRIVATE_TEST_SENTINEL');
        INSERT INTO client_inbounds VALUES(1,1);
        INSERT INTO hosts VALUES(1,'192.0.2.1');
        ''')
        stream = json.dumps({'network':'xhttp','security':'reality','realitySettings':{'target':'www.yahoo.com:443','serverNames':['www.yahoo.com'],'privateKey':'PRIVATE_TEST_SENTINEL'}})
        con.execute('INSERT INTO inbounds VALUES(1,32053,\'vless\',1,?,?,0,0,0)',(stream,'{"clients":[]}'))
        con.commit()
        return con

    def test_summary_contains_no_client_or_key_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve()/'vpn.db'
            con=self.fixture(path)
            result=inventory.inspect(path)
            con.close()
            self.assertNotIn('PRIVATE_TEST_SENTINEL',json.dumps(result))
            self.assertEqual(result['identities'],1)
            self.assertEqual(result['client_links'],1)
            self.assertEqual(result['production_configuration_writes'],0)

    def test_counters_do_not_change_hash_but_config_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp).resolve()/'vpn.db';con=self.fixture(path)
            before=inventory.inspect(path)['configuration_sha256']
            con.execute('UPDATE inbounds SET up=100, down=200,last_traffic_reset_time=300');con.commit()
            self.assertEqual(before,inventory.inspect(path)['configuration_sha256'])
            con.execute("UPDATE hosts SET address='192.0.2.2'");con.commit()
            self.assertNotEqual(before,inventory.inspect(path)['configuration_sha256']);con.close()

    def test_online_backup_includes_wal_and_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();path=root/'vpn.db';con=self.fixture(path)
            con.execute('PRAGMA journal_mode=WAL');con.execute('PRAGMA wal_autocheckpoint=0')
            con.execute("INSERT INTO clients VALUES(2,'PRIVATE_WAL_SENTINEL')");con.commit()
            state=root/'state';result=inventory.inspect(path,state)
            self.assertEqual(result['identities'],2)
            self.assertEqual((state/'x-ui-before.sqlite3').stat().st_mode & 0o777,0o600)
            self.assertEqual(state.stat().st_mode & 0o777,0o700)
            with contextlib.closing(sqlite3.connect(state/'x-ui-before.sqlite3')) as backup:
                self.assertEqual(backup.execute('SELECT COUNT(*) FROM clients').fetchone()[0],2)
            with self.assertRaises(ValueError):inventory.inspect(path,state)
            con.close()

    def test_symlink_db_and_public_state_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();path=root/'vpn.db';self.fixture(path).close()
            link=root/'link';link.symlink_to(path)
            with self.assertRaises(ValueError):inventory.inspect(link)
            state=root/'state';state.mkdir(mode=0o755);state.chmod(0o755)
            with self.assertRaises(ValueError):inventory.inspect(path,state)

    def test_rules_only_count_two_ports(self):
        rules=audit.rules()
        self.assertIn('policy accept',rules)
        for forbidden in (' drop',' reject','flush','masquerade','dnat','snat','log ','18082','32063','32085','32086','2222','443'):
            self.assertNotIn(forbidden,rules)
        self.assertEqual(rules.count(' counter comment '),12)
        self.assertIn('iifname "lo"',rules)
        self.assertIn('12096:other',rules)
        self.assertIn('32087:other',rules)

    def test_counter_and_handle_changes_do_not_invalidate_hash(self):
        left=[{'rule':{'handle':1,'expr':[{'counter':{'packets':1,'bytes':20}}]}}]
        right=[{'rule':{'handle':2,'expr':[{'counter':{'packets':7,'bytes':80}}]}}]
        self.assertEqual(audit.plan(left),audit.plan(right))
        right[0]['rule']['expr'].append({'drop':None})
        self.assertNotEqual(audit.plan(left),audit.plan(right))

    def test_unowned_table_refused(self):
        payload={'nftables':[{'table':{'family':'inet','name':audit.TABLE,'comment':'someone else'}}]}
        with patch.object(audit,'run',return_value=json.dumps(payload)):
            with self.assertRaises(ValueError):audit.read_table()

    def test_nft_106_missing_comment_requires_exact_policy(self):
        objects=audit.expected_objects()
        # nft 1.0.6 JSON has no table comment, and may reorder anonymous sets.
        objects[-1]['rule']['expr'][0]['match']['right']['set'].reverse()
        objects[-1]['rule']['expr'][-1]['counter']={'packets':5,'bytes':100}
        audit.validate_objects(objects)
        objects[-1]['rule']['expr'].append({'drop':None})
        with self.assertRaises(ValueError):audit.validate_objects(objects)

    def test_readback_finalizes_without_any_remote_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp).resolve();(state/'lock').touch()
            approval=audit.helpers.digest(audit.plan(None))
            (state/'before.json').write_text('null')
            (state/'uncertain.json').write_text(json.dumps({'plan_sha256':approval}))
            with patch.object(audit.socket,'gethostname',return_value='socrat-2'),patch.object(audit.os,'geteuid',return_value=0),patch.object(audit.helpers,'private_directory',return_value=state),patch.object(audit,'read_table',return_value=audit.expected_objects()),patch.object(audit,'run') as run:
                receipt=audit.finalize_readback(approval,state)
                run.assert_not_called();self.assertEqual(receipt['remote_writes'],0)
                self.assertFalse((state/'uncertain.json').exists())

    def test_apply_refuses_wrong_host_and_bad_hash(self):
        with patch.object(audit.socket,'gethostname',return_value='socrat-0'):
            with self.assertRaises(ValueError):audit.apply('bad',None)
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp).resolve()/'state'
            with patch.object(audit.socket,'gethostname',return_value='socrat-2'),patch.object(audit.os,'geteuid',return_value=os.geteuid()),patch.object(audit,'read_table',return_value=None),patch.object(audit,'run') as run:
                # Root is checked independently of the current CI uid.
                with patch.object(audit.os,'geteuid',return_value=0),patch.object(audit.helpers,'private_directory',side_effect=lambda _:state):
                    state.mkdir(mode=0o700)
                    with self.assertRaises(ValueError):audit.apply('wrong',state)
                    run.assert_not_called()

    def test_default_is_preview_and_render_is_offline(self):
        with patch('sys.argv',['audit','--render']),patch.object(audit,'run') as run,contextlib.redirect_stdout(io.StringIO()) as output:
            audit.main();run.assert_not_called();self.assertIn('policy accept',output.getvalue())
        with patch('sys.argv',['audit']),patch.object(audit,'read_table',return_value=None),patch.object(audit,'apply') as apply,contextlib.redirect_stdout(io.StringIO()) as output:
            audit.main();apply.assert_not_called();self.assertFalse(json.loads(output.getvalue())['enforcement'])


class PathCheckTests(unittest.TestCase):
    def test_rejects_credentials_queries_and_unapproved_hosts(self):
        probe=load('path_check_test','vpn-path-check.py')
        for url in ('http://wiki.socrat.alchemmist.xyz/', 'https://user:secret@wiki.socrat.alchemmist.xyz/',
                    'https://wiki.socrat.alchemmist.xyz/?token=secret', 'https://example.com/',
                    'https://vpn.alchemmist.xyz/sub/secret', 'https://wiki.socrat.alchemmist.xyz:444/'):
            with self.assertRaises(ValueError):probe.endpoint(url)

    def test_address_control_cannot_scan_arbitrary_destinations(self):
        probe=load('path_check_address','vpn-path-check.py')
        with self.assertRaises(ValueError):probe.check('https://wiki.socrat.alchemmist.xyz/','control',control_address='192.0.2.1')
        with self.assertRaises(ValueError):probe.check('https://wiki.socrat.alchemmist.xyz/','control',family=6,control_address='109.120.141.97')

    def test_records_dns_failure_without_claiming_tunnel_or_recovery(self):
        probe=load('path_check_failure','vpn-path-check.py')
        with patch.object(probe.socket,'getaddrinfo',side_effect=OSError('PRIVATE_TEST_SENTINEL')):
            result=probe.check('https://wiki.socrat.alchemmist.xyz/','external-control')
        self.assertEqual(result['first_failed_stage'],'dns')
        self.assertFalse(result['native_tunnel_test']);self.assertFalse(result['automatic_recovery'])
        self.assertNotIn('PRIVATE_TEST_SENTINEL',json.dumps(result))

    def test_complete_large_transfer_and_incomplete_transfer_are_distinct(self):
        from unittest.mock import MagicMock
        probe=load('path_check_body','vpn-path-check.py')
        for declared,expected in ((40000,True),(90000,False)):
            tls=MagicMock();tls.makefile.return_value=io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: '+str(declared).encode()+b'\r\n\r\n'+b'x'*40000)
            tls.version.return_value='TLSv1.3';tls.selected_alpn_protocol.return_value='http/1.1'
            ctx=MagicMock();ctx.wrap_socket.return_value.__enter__.return_value=tls
            address=(probe.socket.AF_INET,probe.socket.SOCK_STREAM,6,'',('192.0.2.1',443))
            with patch.object(probe.socket,'getaddrinfo',return_value=[address]),patch.object(probe.socket,'socket'),patch.object(probe.ssl,'create_default_context',return_value=ctx):
                result=probe.check('https://wiki.socrat.alchemmist.xyz/','test-network')
            self.assertEqual(result.get('complete_success_above_32k',False),expected)
            self.assertEqual(result['received_bytes'],40000)
            self.assertFalse(result['native_tunnel_test'])


class RealityPlanTests(unittest.TestCase):
    def setup_plan(self):
        planner=load('reality_plan','vpn-reality-plan.py')
        policy=json.loads((ROOT/'deploy/vpn-hardening/policy.json').read_text())
        config={'inbounds':[{'id':1,'port':32053,'protocol':'vless','enable':1,
          'stream_settings':json.dumps({'network':'xhttp','security':'reality','realitySettings':{'target':'www.intel.com:443','serverNames':['www.yahoo.com'],'privateKey':'PRIVATE_TEST_SENTINEL','shortIds':['PRIVATE_TEST_SENTINEL']}})}],
          'clients':[{'id':1,'secret':'PRIVATE_TEST_SENTINEL'}],'client_inbounds':[],'hosts':[]}
        return planner,policy,config

    def test_preview_preserves_input_and_hides_client_material(self):
        planner,policy,config=self.setup_plan();before=json.dumps(config,sort_keys=True)
        result=planner.build(config,policy)
        self.assertEqual(json.dumps(config,sort_keys=True),before)
        self.assertEqual(len(result['operations']),1)
        self.assertEqual(result['operations'][0]['new'],'www.yahoo.com:443')
        self.assertNotIn('PRIVATE_TEST_SENTINEL',json.dumps(result))
        self.assertEqual(result['production_writes'],0)

    def test_already_correct_target_is_noop(self):
        planner,policy,config=self.setup_plan()
        stream=json.loads(config['inbounds'][0]['stream_settings']);stream['realitySettings']['target']='www.yahoo.com:443'
        config['inbounds'][0]['stream_settings']=json.dumps(stream)
        result=planner.build(config,policy);self.assertEqual(result['operations'],[])
        self.assertEqual(result['before_configuration_sha256'],result['planned_configuration_sha256'])

    def test_sni_and_security_drift_stop(self):
        planner,policy,config=self.setup_plan()
        for field,value in (('security','none'),('network','grpc')):
            changed=json.loads(json.dumps(config));stream=json.loads(changed['inbounds'][0]['stream_settings']);stream[field]=value
            changed['inbounds'][0]['stream_settings']=json.dumps(stream)
            with self.assertRaises(ValueError):planner.build(changed,policy)
        stream=json.loads(config['inbounds'][0]['stream_settings']);stream['realitySettings']['serverNames']=['www.sony.com']
        config['inbounds'][0]['stream_settings']=json.dumps(stream)
        with self.assertRaises(ValueError):planner.build(config,policy)

    def test_ambiguous_target_and_scope_changes_stop(self):
        planner,policy,config=self.setup_plan()
        stream=json.loads(config['inbounds'][0]['stream_settings']);stream['realitySettings']['dest']='www.intel.com:443'
        config['inbounds'][0]['stream_settings']=json.dumps(stream)
        with self.assertRaises(ValueError):planner.build(config,policy)
        policy['newVpsOrPublicIp']=True
        with self.assertRaises(ValueError):planner.build(config,policy)
