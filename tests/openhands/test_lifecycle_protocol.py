"""Tests for the OpenHands steward PR lifecycle protocol module."""
import importlib.util
import pathlib
import unittest
from unittest.mock import Mock, patch

root=pathlib.Path(__file__).resolve().parents[2]
p=root/"charts/openhands/files/steward/pr_lifecycle.py"
s=importlib.util.spec_from_file_location("life",p)
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)
H="a"*40

def check(v):
 if not v:
  raise ValueError("blocked")
def owned(n,h):return {"head":{"ref":"openhands/issue-509/"+"a"*32},"labels":[{"name":"mutation-pr"}]}
def snapshot(author="Bot",reply=False):
 def nodes(x) -> "dict[str, object]":return {"nodes":x,"pageInfo":{"hasNextPage":False}}
 ctx=nodes([{"__typename":"CheckRun","name":"Quality Graph","status":"COMPLETED","conclusion":"SUCCESS"}])
 comments=[{"id":"PRRC_1","author":{"__typename":author,"login":"review-bot"},"body":"Please check coverage","url":"url"}]
 return {"headRefOid":H,"tip":nodes([{"commit":{"statusCheckRollup":{"contexts":ctx}}}]),"reviewThreads":nodes([{"id":"T","isResolved":False,"comments":nodes(comments)}]),"comments":nodes([]),"reviews":nodes([])}
class Protocol(unittest.TestCase):
 """Tests for the OpenHands lifecycle readiness protocol."""

 def test_no_ready_if_bot_remark_pending_even_with_otherwise_green_snapshot(self):
  """Check a pending bot remark blocks ready even on a green snapshot."""
  api=Mock(return_value={"data":{"repository":{"pullRequest":snapshot()}}})
  with patch.dict(m.G,assess=lambda *a:{"ready_to_review":True,"blockers":[]}):
   with self.assertRaises(ValueError):
    m.lifecycle({"action":"life_ready","head":H,"pr":515},api,owned,check)
  assert all(v.args[0] == "graphql" for v in api.call_args_list)
 def test_independent_sha_reread_before_marker(self):
  """Check the head SHA is independently re-read before the marker entry."""
  a=snapshot()
  a["reviewThreads"]["nodes"]=[]
  b={**a,"headRefOid":"b"*40}
  items=iter([a,b])
  api=Mock(side_effect=lambda *args:{"data":{"repository":{"pullRequest":next(items)}}})
  with patch.dict(m.G,assess=lambda *a:{"ready_to_review":True,"blockers":[]}):
   with self.assertRaises(ValueError):
    m.lifecycle({"action":"life_ready","head":H,"pr":514},api,owned,check)
  assert [c.args[0] for c in api.call_args_list] == ["graphql", "graphql"]
