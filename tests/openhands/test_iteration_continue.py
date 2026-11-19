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
 def test_quoted_stop_in_qa_plan_is_not_a_stop(self):
  def event(text):return [{'kind':'MessageEvent','source':'agent','id':'qa-turn','llm_message':{'content':[{'type':'text','text':text}]}}]
  self.assertEqual(m.final_message(event('Ограничение внутреннее, не [БЛОКЕР QA]. Следующий шаг — пагинация.'),True),'qa-turn')
  for marker in ('[ИТОГ QA]','[БЛОКЕР QA]'):
   self.assertIsNone(m.final_message(event('\n'+marker+' Причина или доказательства.'),True))
 def test_read_probe_is_narrow(self):
  def event(t):return dict(id='qa',kind='MessageEvent',source='agent',llm_message={'content':[{'text':t}]})
  msg='[БЛОКЕР QA] Жду разрешения хост-рантайма на чтение QA_PROGRESS.md';self.assertEqual(m.ledger_probe([event(msg)]),'qa');self.assertIsNone(m.ledger_probe([event(msg+' EACCES')]));self.assertIsNone(m.ledger_probe([event('[БЛОКЕР QA] нет доступа к GitHub')]));self.assertIsNone(m.ledger_probe([dict(event(msg),source='user')]))
 def test_bridge_is_route_and_error_specific(self):
  e=dict(kind='ConversationErrorEvent',code='LLMServiceUnavailableError',detail="Connection error. model group 'o-deepseek'");self.assertTrue(m.bridge_disconnected(e));self.assertFalse(m.bridge_disconnected(dict(e,code='LLMAuthenticationError')));self.assertFalse(m.bridge_disconnected(dict(e,detail="Connection error. model group 'v-deepseek-uc'")))
