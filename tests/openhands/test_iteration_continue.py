"""Tests for OpenHands max-iteration resume eligibility logic."""
import importlib.util
import pathlib
import unittest

p=pathlib.Path(__file__).resolve().parents[2]/"charts/openhands/files/continue_iterations.py"
s=importlib.util.spec_from_file_location("resume",p)
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)
class Resume(unittest.TestCase):
 """Tests for iteration resume behavior at boundaries."""

 def test_exact_boundary(self):
  """Check resume eligibility only at the exact error-event boundary."""
  e={"kind": "ConversationErrorEvent","source": "environment","code": "MaxIterationsReached","id": "one"}
  assert m.eligible("error", e)
  for k,v in [("kind","MessageEvent"),("source","agent"),("code","MaxBudgetReached"),("code","LLMError"),("id","")]:assert not m.eligible("error", {**e, k: v})
  for st in ["finished","paused","running","waiting_for_confirmation","idle"]:assert not m.eligible(st, e)
 def test_only_explicit_parallel_limit(self):
  """Check only explicit max-parallel rate limits are retryable."""
  e={"kind": "ConversationErrorEvent","source": "environment","detail": "RateLimitError Limit type: max_parallel_requests. Limit resets at: 2026-11-19 06:45:01 UTC"}
  assert m.retry_parallel(e) is not None
  assert m.retry_parallel({**e, "source": "agent"}) is None
  assert m.retry_parallel({**e, "detail": "401 invalid grant"}) is None
 def test_final_gate(self):
  """Check the final-message gate ignores non-final turns."""
  def ev(source,text):return {"id":"x","kind":"MessageEvent","source":source,"llm_message":{"content":[{"text":text}]}}
  assert m.final_message([{"kind": "ConversationStateUpdateEvent", "key": "execution_status"}, ev("agent", "Next step…")]) == "x"
  assert m.final_message([ev("user", "stop"), ev("agent", "plan")]) is None
  assert m.final_message([ev("agent", "[БЛОКЕР #509] нужна авторизация")]) is None
 def test_quoted_stop_in_qa_plan_is_not_a_stop(self):
  """Check quoted QA markers inside a plan do not stop the run."""
  def event(text):return [{"kind":"MessageEvent","source":"agent","id":"qa-turn","llm_message":{"content":[{"type":"text","text":text}]}}]
  assert m.final_message(event("Ограничение внутреннее, не [БЛОКЕР QA]. Следующий шаг — пагинация."), True) == "qa-turn"
  for marker in ("[ИТОГ QA]","[БЛОКЕР QA]"):
   assert m.final_message(event("\n" + marker + " Причина или доказательства."), True) is None
 def test_read_probe_is_narrow(self):
  """Check the ledger read probe matches only its narrow request."""
  def event(t):return {"id": "qa","kind": "MessageEvent","source": "agent","llm_message": {"content":[{"text":t}]}}
  msg="[БЛОКЕР QA] Жду разрешения хост-рантайма на чтение QA_PROGRESS.md"
  assert m.ledger_probe([event(msg)]) == "qa"
  assert m.ledger_probe([event(msg + " EACCES")]) is None
  assert m.ledger_probe([event("[БЛОКЕР QA] нет доступа к GitHub")]) is None
  assert m.ledger_probe([dict(event(msg), source="user")]) is None
 def test_bridge_is_route_and_error_specific(self):
  """Check the disconnected bridge matches only its route and error."""
  e={"kind": "ConversationErrorEvent","code": "LLMServiceUnavailableError","detail": "Connection error. model group 'o-deepseek'"}
  assert m.bridge_disconnected(e)
  assert not m.bridge_disconnected(dict(e, code="LLMAuthenticationError"))
  assert not m.bridge_disconnected(dict(e, detail="Connection error. model group 'v-deepseek-uc'"))
 def test_worker_resume(self):
  """Check worker resume only when the worker states the pause reason."""
  def ev(t):return {"kind": "MessageEvent","source": "agent","id": "p","llm_message": {"content":[{"text":t}]}}
  assert m.pending_worker("finished", [ev("I need to look at the tests.")], 0) == ("plan", "p")
  for t in ["I need to get permission.", "Done: https://github.com/example", "[БЛОКЕР QA]","Tests passed."]:assert m.pending_worker("finished", [ev(t)], 0) is None
  assert m.pending_worker("paused", [ev("I need to read tests.")], 0) is None
 def test_capacity_restart_release_and_pause(self):
  """Check capacity restart releases held slots and stays paused."""
  import tempfile
  with tempfile.TemporaryDirectory() as d:
   path=d+"/db"
   held=True
   observations=[]
   def chat(cid):
    state={"execution_status":"error","agent":{"llm":{"model":"test"}}}
    ev={"id": cid,"kind": "ConversationErrorEvent","source": "environment","code": "LLMRateLimitError","detail": "RateLimitError max_parallel_requests=1 requests in flight"}
    def api(s="",method="GET"):
     if s.startswith("/events"):return {"items":[ev]}
     if not s:return state
     assert not held
     state["execution_status"]="running"
     observations.append((cid,"tool result"))
     return {"success":True}
    return state,lambda now:m.busy_resume(cid,api,[ev],now,path=path)
   a,tick=chat("a")
   b,other=chat("b")
   assert not tick(100)
   assert not other(100)
   assert not tick(159)
   held=False
   a,tick=chat("a")
   assert tick(160)
   assert not other(160)
   b["execution_status"]="paused"
   assert not other(221)
   assert observations == [("a", "tool result")]
