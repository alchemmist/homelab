import copy
import base64
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('netbird_access',ROOT/'scripts/netbird-access.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


def snapshot():
 return {'nb_accounts':[{'id':'account','settings':{'local_auth_disabled':True,'jwt_groups_enabled':True,'groups_propagation_enabled':True,'jwt_groups_claim_name':'groups','jwt_allow_groups':[M.LEGACY_LOGIN],'peer_login_expiration':28800,'extra':{'user_approval_required':True,'peer_approval_enabled':False}}}],
 'nb_groups':[{'id':'all','name':'All','issued':'api'},{'id':'admins','name':M.ADMIN,'issued':'jwt'}],
 'nb_dns':{'disabled_management_groups':[]},
 'nb_policies':[{'enabled':True,'rules':[{'enabled':True,'sources':['admins'],'destinations':['nodes']}]}],
 'ak_groups':[{'pk':'admins','name':M.ADMIN,'users':[1],'is_superuser':False,'parents':[],'roles':[]},{'pk':'login','name':M.LEGACY_LOGIN}],
 'ak_apps':[{'slug':M.APP,'pk':'app','provider':1,'policy_engine_mode':'any'}],
 'ak_providers':[{'pk':1,'sub_mode':'user_uuid','authentication_flow':'mfa','authorization_flow':'authorization','property_mappings':['openid','email','profile']}],
 'ak_mfa':[{'pk':'mfa','not_configured_action':'configure'}],
 'ak_flow_bindings':[{'stage':'mfa'}],
 'ak_scopes':[{'pk':'groups','name':M.PROFILE_MAPPING,'scope_name':'profile','expression':M.EXPRESSION}],
 'ak_bindings':[{'group':'login','enabled':True,'order':0}],
 'ak_users':[{'pk':2,'uuid':'exact-reviewed-uuid','username':'new-admin','is_active':True,'is_superuser':False,'type':'internal','groups':['unrelated']} ]}


class AdmissionTests(unittest.TestCase):
 def test_reconcile_is_additive_and_preserves_session_policy(self):
  s=snapshot();before=copy.deepcopy(s);plan=M.reconcile_plan(s)
  self.assertEqual(s,before)
  self.assertEqual(len(plan),4)
  self.assertEqual(plan[0]['body']['property_mappings'],['openid','email','profile','groups'])
  account=next(p for p in plan if p['purpose']=='trusted-group-sso-admission')
  self.assertEqual(account['body']['settings']['peer_login_expiration'],28800)
  self.assertEqual(account['body']['settings']['jwt_allow_groups'],[M.LEGACY_LOGIN,M.ADMIN])
  dns=next(p for p in plan if p['purpose']=='server-side-dns-management-off')
  self.assertEqual(dns['body']['disabled_management_groups'],['all'])

 def test_reconcile_noop_after_expected_readback(self):
  s=snapshot();s['ak_providers'][0]['property_mappings'].append('groups')
  s['ak_bindings'].append({'group':'admins','enabled':True,'order':1})
  s['nb_accounts'][0]['settings']['jwt_allow_groups'].append(M.ADMIN)
  s['nb_accounts'][0]['settings']['extra']['user_approval_required']=False
  s['nb_dns']['disabled_management_groups']=['all']
  self.assertEqual(M.reconcile_plan(s),[])

 def test_vendor_scope_gap_creates_profile_mapping_without_fake_groups(self):
  s=snapshot();s['ak_scopes']=[]
  plan=M.reconcile_plan(s)
  self.assertEqual(plan[0]['body']['scope_name'],'profile')
  self.assertEqual(plan[0]['body']['expression'],M.EXPRESSION)
  self.assertEqual(plan[1]['body']['property_mappings'][-1],'$profile_mapping')

 def test_auto_admission_remains_group_restricted_and_preserves_peer_policy(self):
  s=snapshot();plan=M.reconcile_plan(s)
  change=next(p for p in plan if p['purpose']=='trusted-group-sso-admission')
  self.assertFalse(change['body']['settings']['extra']['user_approval_required'])
  self.assertFalse(change['body']['settings']['extra']['peer_approval_enabled'])
  s['nb_accounts'][0]['settings']['jwt_allow_groups'].append('unreviewed-public-signup')
  with self.assertRaises(ValueError):M.reconcile_plan(s)

 def test_missing_or_skipping_mfa_blocks_admission(self):
  s=snapshot();s['ak_flow_bindings']=[]
  with self.assertRaises(ValueError):M.reconcile_plan(s)
  s=snapshot();s['ak_mfa'][0]['not_configured_action']='skip'
  with self.assertRaises(ValueError):M.reconcile_plan(s)

 def test_default_all_policy_blocks_onboarding(self):
  s=snapshot();s['nb_policies'][0]['rules'][0]['sources']=['all']
  with self.assertRaises(ValueError):M.reconcile_plan(s)
  s=snapshot();s['nb_policies'][0]['rules'][0]['destinations']=[{'id':'all'}]
  with self.assertRaises(ValueError):M.reconcile_plan(s)

 def test_fake_jwt_source_rejected(self):
  s=snapshot();s['nb_groups'][1]['issued']='api'
  with self.assertRaises(ValueError):M.reconcile_plan(s)

 def test_superuser_or_parent_group_rejected(self):
  for key,value in [('is_superuser',True),('parents',['owner']),('roles',['administrator'])]:
   with self.subTest(key=key):
    s=snapshot();s['ak_groups'][0][key]=value
    with self.assertRaises(ValueError):M.reconcile_plan(s)

 def test_unexpected_app_bypass_rejected(self):
  for binding in [{'group':'unknown','enabled':True},{'group':'login','enabled':True,'user':12},{'group':'login','enabled':True,'failure_result':True}]:
   s=snapshot();s['ak_bindings']=[binding]
   with self.assertRaises(ValueError):M.reconcile_plan(s)

 def test_membership_action_never_replaces_other_groups_or_grants_superuser(self):
  s=snapshot();plan=M.membership_plan(s,'new-admin','exact-reviewed-uuid')
  self.assertEqual(plan[0]['path'],'core/groups/admins/add_user/')
  self.assertEqual(plan[0]['body'],{'pk':2})
  self.assertEqual(s['ak_users'][0]['groups'],['unrelated'])
  self.assertEqual(len(plan),1)

 def test_no_email_fallback_or_ambiguous_adoption(self):
  s=snapshot()
  with self.assertRaises(ValueError):M.membership_plan(s,'new-admin','wrong-uuid')
  s['ak_users'].append(dict(s['ak_users'][0]))
  with self.assertRaises(ValueError):M.membership_plan(s,'new-admin','exact-reviewed-uuid')

 def test_nonhuman_inactive_superuser_rejected(self):
  for key,value in [('type','service_account'),('is_active',False),('is_superuser',True)]:
   s=snapshot();s['ak_users'][0][key]=value
   with self.assertRaises(ValueError):M.membership_plan(s,'new-admin','exact-reviewed-uuid')

 def test_membership_grant_revoke_idempotence(self):
  s=snapshot();self.assertEqual(M.membership_plan(s,'new-admin','exact-reviewed-uuid',True),[])
  s['ak_groups'][0]['users'].append(2)
  self.assertEqual(M.membership_plan(s,'new-admin','exact-reviewed-uuid'),[])
  self.assertIn('remove_user',M.membership_plan(s,'new-admin','exact-reviewed-uuid',True)[0]['path'])

 def test_prior_uncertain_receipt_blocks_rerun(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);root.chmod(0o700);p=root/'run';p.mkdir();M.atomic(p/'receipt.json',{'state':'uncertain-stop'})
   with self.assertRaises(ValueError):M.check_state_folder(root)

 def offboard_state(self):
  s=snapshot();s['ak_providers'][0]['client_id']='reviewed-client'
  s['nb_idps']=[{'id':'authentik-reviewed-connector','type':'authentik','issuer':'https://auth.socrat.alchemmist.xyz/application/o/'+M.APP+'/','client_id':'reviewed-client'}]
  uid=b'exact-reviewed-uuid';connector=b'authentik-reviewed-connector'
  subject=base64.b64encode(bytes([10,len(uid)])+uid+bytes([18,len(connector)])+connector).decode().rstrip('=')
  s['nb_users']=[{'id':subject,'idp_id':connector.decode(),'role':'user','is_service_user':False,'is_blocked':False,'auto_groups':['unrelated']}]
  s['nb_peers']=[{'id':'target-peer','user_id':subject},{'id':'untouched-machine','user_id':'service'}]
  s['ak_groups'][0]['users'].append(2)
  return s

 def test_offboarding_blocks_login_and_retires_only_exact_subject_devices(self):
  s=self.offboard_state();plan=M.offboard_plan(s,'new-admin','exact-reviewed-uuid')
  self.assertTrue(plan[0]['body']['is_blocked'])
  self.assertEqual(plan[1]['path'],'peers/target-peer')
  self.assertIn('remove_user',plan[2]['path'])
  self.assertNotIn('untouched-machine',str(plan))

 def test_owner_or_foreign_connector_offboarding_is_refused(self):
  s=self.offboard_state();s['nb_users'][0]['role']='owner'
  with self.assertRaises(ValueError):M.offboard_plan(s,'new-admin','exact-reviewed-uuid')
  s=self.offboard_state();s['nb_idps'][0]['client_id']='unexpected'
  with self.assertRaises(ValueError):M.offboard_plan(s,'new-admin','exact-reviewed-uuid')

 def test_already_disabled_authentik_user_can_still_be_offboarded(self):
  s=self.offboard_state();s['ak_users'][0]['is_active']=False
  self.assertTrue(M.offboard_plan(s,'new-admin','exact-reviewed-uuid'))

 def test_offboard_noop_after_readback(self):
  s=self.offboard_state();s['nb_users'][0]['is_blocked']=True;s['nb_peers']=[];s['ak_groups'][0]['users'].remove(2)
  self.assertEqual(M.offboard_plan(s,'new-admin','exact-reviewed-uuid'),[])

 def test_no_password_setup_key_or_kubernetes_mutations(self):
  actions=str(M.reconcile_plan(snapshot()))+str(M.membership_plan(snapshot(),'new-admin','exact-reviewed-uuid'))
  for forbidden in ['password','setup-key','cluster-admin','is_superuser','kubectl','users/invites']:
   self.assertNotIn(forbidden,actions)
