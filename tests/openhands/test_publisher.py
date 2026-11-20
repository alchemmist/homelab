import importlib.util,pathlib,unittest
from unittest.mock import patch
p=pathlib.Path(__file__).resolve().parents[2]/'charts/openhands/files/steward/publisher.py';s=importlib.util.spec_from_file_location('publisher',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Publisher(unittest.TestCase):
 def test_no_generic_or_merge(self):
  with patch.object(m,'api') as api:
   for a in ['merge','push','delete','request','approve','resolve','workflow_dispatch']:
    with self.assertRaises(ValueError):m.dispatch({'action':a})
   api.assert_not_called()
 def test_path(self):
  for p in ['server/tests/../a.py','.github/workflows/a.yml','server/tests/x.sh','server/app/.git/a.py']:
   with self.assertRaises(ValueError):m.changes({p:'x'})
 def test_other_branch(self):
  sha='a'*40
  with patch.object(m,'api',return_value={'state':'open','base':{'ref':'main'},'head':{'repo':{'full_name':m.REPO},'ref':'main','sha':sha},'user':{'login':'alchemmist'}}) as api:
   with self.assertRaises(ValueError):m.owned_pr(1,sha)
   self.assertEqual(api.call_count,1)
 def test_qa_create_rejects_unowned_issue(self):
  with patch.object(m,'api',return_value={'state':'open','user':{'login':'alchemmist'},'body':'ordinary issue'}) as api:
   with self.assertRaises(ValueError):m.dispatch(dict(action='qa_create',issue=509,head='a'*40,title='Scoped test',files={'web/src/test.ts':'x'}))
   self.assertEqual(api.call_count,1)
 def test_qa_files_and_credential_filter(self):
  self.assertEqual(len(m.changes({'web/e2e/filter.spec.ts':'abc'},True)),1)
  for v in ['Bearer token','github_pat_fake','https://host']:
   with self.assertRaises(ValueError):m.clean_text(v,1,90)
 def test_campaign_ci_test_path_requires_proof(self):
  f={'ci/tests/test_mutation_123456abcdef.py':'# regression'}
  with self.assertRaises(ValueError):m.changes(f)
  self.assertEqual(len(m.changes(f,pi_ci=True)),1)
  for p in ('ci/tests/conftest.py','ci/lib/mutation_gate.py','ci/tests/test_mutation_123456abcdef.sh'):
   with self.assertRaises(ValueError):m.changes({p:'bad'},pi_ci=True)
