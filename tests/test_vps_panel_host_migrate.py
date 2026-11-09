"""Offline contracts only; no network or real credentials."""
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('host_migrate', Path(__file__).resolve().parents[1] / 'scripts/vps-panel-host-migrate.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
OLD, NEW = '1.1.1.1', '8.8.8.8'


class HostMigrationTests(unittest.TestCase):
    def test_only_exact_address_and_its_port_change(self):
        group = {'groupId': 'group-1', 'inboundIds': [1], 'hosts': [OLD, OLD+':443', '11.1.1.1'],
                 'remark': 'preserve', 'isDisabled': True, 'sni': 'keep.example', 'path': '/keep'}
        expected = copy.deepcopy(group)
        expected['hosts'] = [NEW, NEW+':443', '11.1.1.1']
        self.assertEqual(m.payload(group, OLD, NEW), expected)
        self.assertEqual(group['hosts'][0], OLD)

    def test_bad_group_and_port_refuse_before_network(self):
        for group in [dict(groupId='../bad', inboundIds=[1], hosts=[OLD]),
                      dict(groupId='good', inboundIds=[1], hosts=[OLD+':bad']),
                      dict(groupId='good', inboundIds=[], hosts=[OLD]),
                      dict(groupId='good', inboundIds=[1], hosts=['11.1.1.1'])]:
            with self.subTest(group=group), self.assertRaises(ValueError):
                m.payload(group, OLD, NEW)

    def test_id_binding_credentials_and_retirement_preserved(self):
        before = {'hosts':[{'id':1,'group_id':'one','address':OLD,'is_disabled':0},
                           {'id':2,'group_id':'two','address':OLD,'is_disabled':1}],
                  'inbounds':[{'id':9,'port':32063,'enable':0}],
                  'clients':[{'id':1,'uuid':'sentinel','quota':123}],
                  'client_inbounds':[{'client_id':1,'inbound_id':9}]}
        after = m.expected_configuration(before, OLD, NEW, 'one')
        self.assertEqual(after['hosts'][0]['id'],1)
        self.assertEqual(after['hosts'][0]['address'],NEW)
        self.assertEqual(after['hosts'][1],before['hosts'][1])
        for k in ['inbounds','clients','client_inbounds']:self.assertEqual(after[k],before[k])

    def test_only_known_array_encoding_is_normalized(self):
        a = {'hosts':[{'id':1,'tags':'[]','snis':None,'path':'/keep','sni':'keep'}]}
        b = {'hosts':[{'id':1,'tags':[],'snis':[],'path':'/keep','sni':'keep'}]}
        self.assertEqual(m.canonical_projection(a),m.canonical_projection(b))
        b['hosts'][0]['path']='/changed'
        self.assertNotEqual(m.canonical_projection(a),m.canonical_projection(b))

    def test_admin_scope_must_be_explicit_and_bound_to_preview(self):
        self.assertEqual(m.native.NativeSession('/tmp/vpn83-20261109-default').worker_scope,'node-sync')
        self.assertEqual(m.native.NativeSession('/tmp/vpn83-20261109-migrate',worker_scope='admin').worker_scope,'admin')
        with self.assertRaises(ValueError):m.native.NativeSession('/tmp/vpn83-20261109-deny',worker_scope='unknown')

    def test_host_methods_and_other_mutations_refused(self):
        for method,path in [('GET','/hosts/update/one'),('POST','/hosts/list'),
                            ('POST','/hosts/del/one'),('POST','/hosts/add'),('POST','/hosts/update/../bad')]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                m.native.request('http://127.0.0.1:18082/panel/api','A'*48,method,path,{})

    def test_wrong_approval_refuses_session_open(self):
        session=unittest.mock.Mock()
        with patch.object(m,'preview',return_value=(session,{}, {'bound':'plan'})):
            with self.assertRaises(ValueError):m.apply('/tmp/unneeded',OLD,NEW,'wrong')
        session.open.assert_not_called()

    def test_native_null_false_and_current_updated_at_only(self):
        import time
        before={'hosts':[{'id':1,'group_id':'g','address':OLD,'sni_shared_random':None,'updated_at':0}], 'clients':[{'uuid':'preserve'}]}
        after=copy.deepcopy(before);after['hosts'][0].update(address=NEW,sni_shared_random=0,updated_at=int(time.time()*1000))
        self.assertTrue(m.verify_transition(before,after,OLD,NEW,'g'))
        after['hosts'][0]['sni_shared_random']=1
        self.assertFalse(m.verify_transition(before,after,OLD,NEW,'g'))
        after['hosts'][0]['sni_shared_random']=0;after['hosts'][0]['updated_at']=1
        self.assertFalse(m.verify_transition(before,after,OLD,NEW,'g'))

    def test_single_sni_fallback_native_pool_is_semantically_equal(self):
        a={'hosts':[{'sni':'keep.example','snis':None,'sni_shared_random':None}]}
        b={'hosts':[{'sni':'keep.example','snis':'["keep.example"]','sni_shared_random':0}]}
        self.assertEqual(m.canonical_projection(a),m.canonical_projection(b))
        b['hosts'][0]['snis']='["different.example"]'
        self.assertNotEqual(m.canonical_projection(a),m.canonical_projection(b))
