import base64, hashlib, hmac, importlib.util, json, sqlite3, tempfile, unittest
from pathlib import Path
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
   self.assertEqual(call()['cards'],405); self.assertEqual(call()['status'],'duplicate');e['issue']['body']+=' changed';self.assertEqual(call()['status'],'changed_report_requires_review');self.assertEqual(sqlite3.connect(d).execute('select count(*) from cards').fetchone(),(405,))
