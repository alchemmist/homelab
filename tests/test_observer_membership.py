import copy
import importlib.util
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'deploy/platform/rancher/public-entry/files/observer_membership.py'
spec = importlib.util.spec_from_file_location('observer_membership', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture(subject='fixture-uuid'):
    principal=m.PREFIX+subject
    user={'metadata':{'name':'u-fixture'},'principalIds':[principal]}
    attr={'metadata':{'name':'u-fixture','uid':'owned','resourceVersion':'17'},
          'ExtraByProvider':{'genericoidc':{'principalid':[principal]}},
          'GroupPrincipals':{'genericoidc':{'Items':[{'metadata':{'name':m.PRINCIPAL}}]}}}
    return [user],[attr],{'allowedPrincipalIds':[m.PREFIX+m.OWNER,m.PRINCIPAL]}


class MembershipTests(unittest.TestCase):
    def test_removal_is_only_cas_native_cache_update(self):
        users,attrs,auth=fixture();before=copy.deepcopy(attrs)
        operations=m.rancher_plan(users,attrs,auth,lambda *a:False)
        self.assertEqual(attrs,before)
        name,ops=operations[0]
        self.assertEqual(name,'u-fixture')
        self.assertEqual([o['op'] for o in ops],['test','test','test','test','replace'])
        self.assertEqual(ops[-1],{'op':'replace','path':'/GroupPrincipals/genericoidc/Items','value':[]})

    def test_owner_and_reviewed_direct_principals_are_never_changed(self):
        for subject in [m.OWNER,'legacy-owner']:
            users,attrs,auth=fixture(subject)
            auth['allowedPrincipalIds'].append(m.PREFIX+subject)
            self.assertEqual(m.rancher_plan(users,attrs,auth,lambda *a:False),[])

    def test_only_observer_group_changes_and_other_groups_survive(self):
        users,attrs,auth=fixture()
        other={'metadata':{'name':'genericoidc_group://other-reviewed-group'}}
        attrs[0]['GroupPrincipals']['genericoidc']['Items'].append(other)
        ops=m.rancher_plan(users,attrs,auth,lambda *a:False)[0][1]
        self.assertEqual(ops[-1]['value'],[other])
        attrs[0]['GroupPrincipals']['genericoidc']['Items']=[other]
        ops=m.rancher_plan(users,attrs,auth,lambda *a:True)[0][1]
        self.assertEqual(ops[-1]['value'][0],other)
        self.assertEqual(ops[-1]['value'][1]['metadata']['name'],m.PRINCIPAL)

    def test_closed_rancher_admission_never_restores_observer_cache(self):
        users,attrs,auth=fixture()
        auth['allowedPrincipalIds'].remove(m.PRINCIPAL)
        self.assertEqual(m.rancher_plan(users,attrs,auth,lambda *a:True)[0][1][-1]['value'],[])

    def test_no_native_user_provisioning_and_noop_when_converged(self):
        users,attrs,auth=fixture()
        self.assertEqual(m.rancher_plan(users,attrs,auth,lambda *a:True),[])
        self.assertEqual(m.rancher_plan([],attrs,auth,lambda *a:True),[])

    def test_wrong_subject_duplicate_and_malformed_cache_stop(self):
        for change in [lambda a:a['ExtraByProvider']['genericoidc'].update(principalid=['wrong']),
                       lambda a:a['GroupPrincipals']['genericoidc']['Items'].append(copy.deepcopy(a['GroupPrincipals']['genericoidc']['Items'][0])),
                       lambda a:a['GroupPrincipals']['genericoidc'].update(Items='wrong')]:
            users,attrs,auth=fixture();change(attrs[0])
            with self.assertRaises(RuntimeError):m.rancher_plan(users,attrs,auth,lambda *a:False)

    def test_unrelated_legacy_orphan_is_preserved_and_does_not_block_current_viewer(self):
        users,attrs,auth=fixture()
        legacy_user={'metadata':{'name':'u-old'},'principalIds':[m.PREFIX+'old-subject']}
        legacy_attr={'metadata':{'name':'u-old'},'ExtraByProvider':{},'GroupPrincipals':{}}
        before=copy.deepcopy(legacy_attr)
        ops=m.rancher_plan([legacy_user]+users,[legacy_attr]+attrs,auth,lambda *a:False)
        self.assertEqual(len(ops),1)
        self.assertEqual(ops[0][0],'u-fixture')
        self.assertEqual(legacy_attr,before)

    def test_idp_failure_cannot_produce_partial_mutations(self):
        users,attrs,auth=fixture()
        def failed(*args):raise RuntimeError('IdP unavailable')
        with self.assertRaises(RuntimeError):m.rancher_plan(users,attrs,auth,failed)

    def test_wiki_module_matches_single_reviewed_controller_source(self):
        self.assertEqual(SOURCE.read_bytes(),(ROOT/'deploy/wiki-runtime/chart/files/observer_membership.py').read_bytes())

    def test_reader_gate_applies_to_cookie_and_api_tokens_not_privileged_or_unlinked_accounts(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE oidc_accounts(issuer TEXT,subject TEXT,user_id TEXT)')
        db.execute('INSERT INTO oidc_accounts VALUES (?,?,?)',('https://issuer/','subject','reader'));db.commit()
        class Store:
            oidc_enabled=True
            local_owners={'owner'}
            def connect(self):return db
            def session(self,token):return {'user':{'id':token,'role':'admin' if token=='owner' else 'editor' if token=='editor' else 'reader'}}
            token_session=session
        reader=Mock();reader.admitted.return_value=False
        with patch.dict(os.environ,{'OBSERVER_IDP_READ_TOKEN_FILE':'/private/token','WIKI_OIDC_GROUP_ROLES':'{"homelab-observer":"reader"}','WIKI_OIDC_ISSUER':'https://issuer/'}),patch.object(m,'MembershipReader',return_value=reader):
            store=Store();m.install_wiki_guard(store)
            self.assertIsNone(store.session('reader'));self.assertIsNone(store.token_session('reader'))
            self.assertIsNotNone(store.session('owner'));self.assertIsNotNone(store.session('editor'));self.assertIsNotNone(store.token_session('unlinked-machine'))
            reader.admitted.return_value=True
            self.assertIsNotNone(store.session('reader'))
            reader.admitted.side_effect=RuntimeError('API unavailable')
            self.assertIsNone(store.session('reader'));self.assertIsNone(store.token_session('reader'))
        db.close()

    def test_group_snapshot_checks_active_status_and_membership(self):
        reader=m.MembershipReader('/unused')
        reader.rows=Mock(side_effect=[[{'pk':'g','name':'homelab-observer'}],[{'uuid':'subject','is_active':True,'groups':['g']} ]])
        self.assertTrue(reader.admitted('subject',{'homelab-observer'}))
        self.assertFalse(reader.admitted('missing',{'homelab-observer'}))
        reader.users['subject']['is_active']=False
        self.assertFalse(reader.admitted('subject',{'homelab-observer'}))
        self.assertEqual(reader.rows.call_count,2)

    def test_argo_unknown_groups_have_no_default_reader_grant_machine_reader_is_explicit(self):
        for path in ['deploy/platform/argo-cd/values.yaml','deploy/argocd/values.yaml']:
            text=(ROOT/path).read_text()
            self.assertIn('policy.default: role:unassigned',text)
            self.assertIn('g, mcp, role:readonly',text)


if __name__=='__main__':unittest.main()
