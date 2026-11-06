import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('writer_helper',Path(__file__).resolve().parents[1]/'scripts/rustfs/spi_writer_secret.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)

class WriterSecret(unittest.TestCase):
    def test_offline_and_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            storage={r:{'access':r+'-access','secret':r+'-secret'} for r in ('root','reader','writer')}
            def put(name,obj):
                p=d/name;p.write_text(json.dumps(obj));p.chmod(0o600)
            put('storage.json',storage)
            with self.assertRaises(ValueError):helper.render(d)
            journal={storage[r]['access']:hashlib.sha256(storage[r]['secret'].encode()).hexdigest() for r in ('reader','writer')}
            put('bootstrap-journal.json',journal)
            helper.render(d);helper.render(d)
            p=d/'spi-evidence-writer.secret.json';doc=json.loads(p.read_text())
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
            self.assertEqual(doc['metadata'],{'name':'spi-evidence-writer','namespace':'automation'})
            self.assertEqual(json.loads(base64.b64decode(doc['data']['credentials.json'])),storage['writer'])
            put('bootstrap-journal.json',{})
            with self.assertRaises(ValueError):helper.render(d)
            put('bootstrap-journal.json',journal);put(p.name,{})
            with self.assertRaises(ValueError):helper.render(d)
            storage['writer']=storage['root'];put('storage.json',storage)
            with self.assertRaises(ValueError):helper.render(d)
