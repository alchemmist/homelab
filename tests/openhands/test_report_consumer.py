import base64, hashlib, hmac, importlib.util, json, sqlite3, tempfile, unittest
from pathlib import Path
from contextlib import closing
ROOT=Path(__file__).resolve().parents[2]; src=ROOT/'charts/openhands/files/report-intake';sp=importlib.util.spec_from_file_location('report_intake',src/'intake.py');intake=importlib.util.module_from_spec(sp);sp.loader.exec_module(intake)
class Reports(unittest.TestCase):
 def test_observed_report_and_replayed_transport(self):
  registry=json.loads((src/'repos.json').read_text());rid,cfg=next(iter(registry.items()));owner={'id':cfg['reporters'][0]};label={'name':cfg['label']}; e={'repository':{'id':int(rid),'full_name':cfg['name']},'issue':{'state':'open','number':509,'user':owner,'labels':[label],'body':(ROOT/'services/pi-monori/issue509.md').read_text()},'label':label,'action':'labeled','sender':owner}
  def envelope():
   b=json.dumps(e).encode();return {'raw':base64.b64encode(b).decode(),'signature':'sha256='+hmac.new(b'test',b,hashlib.sha256).hexdigest()}
  with tempfile.TemporaryDirectory() as td:
   d=Path(td)/'db';call=lambda:intake.ingest(envelope(),registry,b'test',d)
   with self.assertRaises(PermissionError):intake.ingest(envelope(),registry,b'bad',d)
   e['sender']={'id':1};self.assertEqual(call()['status'],'ignored_sender');e['sender']=owner
   self.assertEqual(call()['cards'],405); self.assertEqual(call()['status'],'duplicate');e['issue']['body']+=' changed';self.assertEqual(call()['status'],'changed_report_requires_review')
   with closing(sqlite3.connect(d)) as db:self.assertEqual(db.execute('select count(*) from cards').fetchone(),(405,))
 def test_artifact_protocol_rejects_plans_and_multiple_files(self):
  spec=importlib.util.spec_from_file_location('artifact',ROOT/'services/pi-monori/artifact.py');art=importlib.util.module_from_spec(spec);spec.loader.exec_module(art)
  sample='```python\ndef test_fixture() -> None:\n    assert 1 == 1\n```';self.assertTrue(art.artifact_response('transport warning\n'+sample).startswith('def test_fixture'))
  for raw in ('I will write a test.',sample+'\n'+sample,'```sh\necho test\n```'):
   with self.assertRaises(ValueError):art.artifact_response(raw)
