import importlib.util,pathlib,unittest
from collections.abc import Callable
p=pathlib.Path(__file__).resolve().parents[2]/'charts/openhands/files/continue_iterations.py';s=importlib.util.spec_from_file_location('resume',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Resume(unittest.TestCase):
 def test_exact_boundary(self):
  e=dict(kind='ConversationErrorEvent',source='environment',code='MaxIterationsReached',id='one');self.assertTrue(m.eligible('error',e))
  for k,v in [('kind','MessageEvent'),('source','agent'),('code','MaxBudgetReached'),('code','LLMError'),('id','')]:self.assertFalse(m.eligible('error',{**e,k:v}))
  for st in ['finished','paused','running','waiting_for_confirmation','idle']:self.assertFalse(m.eligible(st,e))
 def test_only_explicit_parallel_limit(self):
  e=dict(kind='ConversationErrorEvent',source='environment',detail='RateLimitError Limit type: max_parallel_requests. Limit resets at: 2026-11-19 06:45:01 UTC');self.assertIsNotNone(m.retry_parallel(e));self.assertIsNone(m.retry_parallel({**e,'source':'agent'}));self.assertIsNone(m.retry_parallel({**e,'detail':'401 invalid grant'}))
 def test_final_gate(self):
  def ev(source: str,text: str)->dict[str, object]:
   return {'id':'x','kind':'MessageEvent','source':source,'llm_message':{'content':[{'text':text}]}}
  self.assertEqual(m.final_message([{'kind':'ConversationStateUpdateEvent','key':'execution_status'},ev('agent','Next step…')]),'x');self.assertIsNone(m.final_message([ev('user','stop'),ev('agent','plan')]));self.assertIsNone(m.final_message([ev('agent','[БЛОКЕР #509] нужна авторизация')]))
 def test_quoted_stop_in_qa_plan_is_not_a_stop(self):
  def event(text: str)->list[dict[str, object]]:
   return [{'kind':'MessageEvent','source':'agent','id':'qa-turn',
    'llm_message':{'content':[{'type':'text','text':text}]}}]
  self.assertEqual(m.final_message(event('Ограничение внутреннее, не [БЛОКЕР QA]. Следующий шаг — пагинация.'),True),'qa-turn')
  for marker in ('[ИТОГ QA]','[БЛОКЕР QA]'):
   self.assertIsNone(m.final_message(event('\n'+marker+' Причина или доказательства.'),True))
 def test_read_probe_is_narrow(self):
  def event(t: str)->dict[str, object]:
   return dict(id='qa',kind='MessageEvent',source='agent',llm_message={'content':[{'text':t}]})
  msg='[БЛОКЕР QA] Жду разрешения хост-рантайма на чтение QA_PROGRESS.md';self.assertEqual(m.ledger_probe([event(msg)]),'qa');self.assertIsNone(m.ledger_probe([event(msg+' EACCES')]));self.assertIsNone(m.ledger_probe([event('[БЛОКЕР QA] нет доступа к GitHub')]));self.assertIsNone(m.ledger_probe([dict(event(msg),source='user')]))
 def test_bridge_is_route_and_error_specific(self):
  e=dict(kind='ConversationErrorEvent',code='LLMServiceUnavailableError',detail="Connection error. model group 'o-deepseek'");self.assertTrue(m.bridge_disconnected(e));self.assertFalse(m.bridge_disconnected(dict(e,code='LLMAuthenticationError')));self.assertFalse(m.bridge_disconnected(dict(e,detail="Connection error. model group 'v-deepseek-uc'")))
 def test_worker_resume(self):
  def ev(t: str)->dict[str, object]:
   return dict(kind='MessageEvent',source='agent',id='p',llm_message={'content':[{'text':t}]})
  self.assertEqual(m.pending_worker('finished',[ev('I need to look at the tests.')],0),('plan','p'))
  for t in ['I need to get permission.', 'Done: https://github.com/example', '[БЛОКЕР QA]','Tests passed.']:self.assertIsNone(m.pending_worker('finished',[ev(t)],0))
  self.assertIsNone(m.pending_worker('paused',[ev('I need to read tests.')],0))
 def test_capacity_restart_release_and_pause(self):
  import tempfile
  with tempfile.TemporaryDirectory() as d:
   path=d+'/db';held=True;observations=[]
   def chat(cid: str)->tuple[dict[str, object],Callable[[int],object]]:
    state:dict[str, object]={'execution_status':'error','agent':{'llm':{'model':'test'}}}
    ev=dict(id=cid,kind='ConversationErrorEvent',source='environment',code='LLMRateLimitError',
     detail='RateLimitError max_parallel_requests=1 requests in flight')
    def api(s: str='',method: str='GET')->dict[str, object]:
     if s.startswith('/events'):return {'items':[ev]}
     if not s:return state
     self.assertFalse(held);state['execution_status']='running';observations.append((cid,'tool result'));return {'success':True}
    return state,lambda now:m.busy_resume(cid,api,[ev],now,path=path)
   a,tick=chat('a');b,other=chat('b');self.assertFalse(tick(100));self.assertFalse(other(100));self.assertFalse(tick(159));held=False
   # New client/controller, same database and same chat/event, no manual run.
   a,tick=chat('a');self.assertTrue(tick(160));self.assertFalse(other(160));b['execution_status']='paused';self.assertFalse(other(221));self.assertEqual(observations,[('a','tool result')])
