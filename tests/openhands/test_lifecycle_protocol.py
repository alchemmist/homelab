import importlib.util,pathlib,unittest
from typing import cast
from unittest.mock import Mock,patch
root=pathlib.Path(__file__).resolve().parents[2];p=root/'charts/openhands/files/steward/pr_lifecycle.py';s=importlib.util.spec_from_file_location('life',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
H='a'*40

def check(v) -> None:
 if not v:raise ValueError('blocked')
def owned(n,h) -> dict[str, object]:return {'head':{'ref':'openhands/issue-509/'+'a'*32},'labels':[{'name':'mutation-pr'}]}
def snapshot(author='Bot',reply=False) -> dict[str, object]:
 def nodes(x):return {'nodes':x,'pageInfo':{'hasNextPage':False}}
 ctx=nodes([{'__typename':'CheckRun','name':'Quality Graph','status':'COMPLETED','conclusion':'SUCCESS'}]);comments=[{'id':'PRRC_1','author':{'__typename':author,'login':'review-bot'},'body':'Please check coverage','url':'url'}];return {'headRefOid':H,'tip':nodes([{'commit':{'statusCheckRollup':{'contexts':ctx}}}]),'reviewThreads':nodes([{'id':'T','isResolved':False,'comments':nodes(comments)}]),'comments':nodes([]),'reviews':nodes([])}
class Protocol(unittest.TestCase):
 def test_no_ready_if_bot_remark_pending_even_with_otherwise_green_snapshot(self) -> None:
  api=Mock(return_value={'data':{'repository':{'pullRequest':snapshot()}}});
  with patch.dict(m.G,assess=lambda *a:{'ready_to_review':True,'blockers':[]}):
   with self.assertRaises(ValueError):m.lifecycle({'action':'life_ready','head':H,'pr':515},api,owned,check)
  self.assertTrue(all(v.args[0]=='graphql' for v in api.call_args_list))
 def test_independent_sha_reread_before_marker(self) -> None:
  a=snapshot();cast("dict[str, object]",a['reviewThreads'])['nodes']=[];b={**a,'headRefOid':'b'*40};items=iter([a,b]);api=Mock(side_effect=lambda *args:{'data':{'repository':{'pullRequest':next(items)}}});
  with patch.dict(m.G,assess=lambda *a:{'ready_to_review':True,'blockers':[]}):
   with self.assertRaises(ValueError):m.lifecycle({'action':'life_ready','head':H,'pr':514},api,owned,check)
  self.assertEqual([c.args[0] for c in api.call_args_list],['graphql','graphql'])
