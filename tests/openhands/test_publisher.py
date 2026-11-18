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
