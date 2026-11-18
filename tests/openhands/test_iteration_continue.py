import importlib.util,pathlib,unittest
p=pathlib.Path(__file__).resolve().parents[2]/'charts/openhands/files/continue_iterations.py';s=importlib.util.spec_from_file_location('resume',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Resume(unittest.TestCase):
 def test_exact_boundary(self):
  e=dict(kind='ConversationErrorEvent',source='environment',code='MaxIterationsReached',id='one');self.assertTrue(m.eligible('error',e))
  for k,v in [('kind','MessageEvent'),('source','agent'),('code','MaxBudgetReached'),('code','LLMError'),('id','')]:self.assertFalse(m.eligible('error',{**e,k:v}))
  for st in ['finished','paused','running','waiting_for_confirmation','idle']:self.assertFalse(m.eligible(st,e))
