import importlib.util,pathlib,unittest
p=pathlib.Path(__file__).resolve().parents[2]/'charts/openhands/files/continue_iterations.py';s=importlib.util.spec_from_file_location('resume',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Resume(unittest.TestCase):
 def test_exact_boundary(self):
  e=dict(kind='ConversationErrorEvent',source='environment',code='MaxIterationsReached',id='one');self.assertTrue(m.eligible('error',e))
  for k,v in [('kind','MessageEvent'),('source','agent'),('code','MaxBudgetReached'),('code','LLMError'),('id','')]:self.assertFalse(m.eligible('error',{**e,k:v}))
  for st in ['finished','paused','running','waiting_for_confirmation','idle']:self.assertFalse(m.eligible(st,e))
 def test_only_explicit_parallel_limit(self):
  e=dict(kind='ConversationErrorEvent',source='environment',detail='RateLimitError Limit type: max_parallel_requests. Limit resets at: 2026-11-19 06:45:01 UTC');self.assertIsNotNone(m.retry_parallel(e));self.assertIsNone(m.retry_parallel({**e,'source':'agent'}));self.assertIsNone(m.retry_parallel({**e,'detail':'401 invalid grant'}))
 def test_final_gate(self):
  def ev(source,text):return {'id':'x','kind':'MessageEvent','source':source,'llm_message':{'content':[{'text':text}]}}
  self.assertEqual(m.final_message([{'kind':'ConversationStateUpdateEvent','key':'execution_status'},ev('agent','Next step…')]),'x');self.assertIsNone(m.final_message([ev('user','stop'),ev('agent','plan')]));self.assertIsNone(m.final_message([ev('agent','[БЛОКЕР #509] нужна авторизация')]))
