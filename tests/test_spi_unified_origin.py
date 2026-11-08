import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]

class PublicationOrigin(unittest.TestCase):
    def test_publication_origin_changes_links_not_objects(self):
        code = ROOT/'charts/spi-triage/files'
        sys.path.insert(0, str(code))
        try:
            spec = importlib.util.spec_from_file_location('unified_evidence_bundle', code/'evidence_bundle.py')
            bundle = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bundle)
            objects = [('spi/v1/'+'a'*64+'/'+'b'*64+'/manifest.json', b'{"immutable":true}')]
            before = list(objects)
            with patch.dict(os.environ, SPI_EVIDENCE_PUBLIC_ORIGIN='https://rustfs.socrat.alchemmist.xyz'):
                text = bundle.storage_markdown(objects)
            self.assertIn('](https://rustfs.socrat.alchemmist.xyz/'+objects[0][0]+')', text)
            self.assertNotIn('/spi-evidence/', text)
            self.assertEqual(objects, before)
            with patch.dict(os.environ, clear=True):
                legacy = bundle.storage_markdown(objects)
            self.assertIn('https://spi-evidence.socrat.alchemmist.xyz/'+objects[0][0], legacy)
            for origin in ('https://evil.invalid', 'https://rustfs.socrat.alchemmist.xyz/', 'http://rustfs.socrat.alchemmist.xyz'):
                with patch.dict(os.environ, SPI_EVIDENCE_PUBLIC_ORIGIN=origin):
                    with self.assertRaises(bundle.Failure):
                        bundle.storage_markdown(objects)
            with patch.dict(os.environ, SPI_EVIDENCE_PUBLIC_ORIGIN='https://evil.invalid'):
                with self.assertRaises(bundle.Failure):
                    bundle.storage_markdown(objects)
        finally:
            sys.path.pop(0)

    def test_live_activation_is_only_publication_origin(self):
        import subprocess, yaml, copy
        raw = subprocess.check_output(['helm','template','spi-triage',str(ROOT/'charts/spi-triage'),'-n','automation','-f',str(ROOT/'charts/spi-triage/values-off-live.yaml')],text=True)
        docs = [x for x in yaml.safe_load_all(raw) if x]
        worker = next(x for x in docs if x['kind']=='Deployment' and x['metadata']['name']=='spi-triage')
        env = {x['name']:x.get('value') for x in worker['spec']['template']['spec']['containers'][0]['env']}
        self.assertEqual(env['SPI_EVIDENCE_PUBLIC_ORIGIN'],'https://rustfs.socrat.alchemmist.xyz')
        self.assertEqual(env['SPI_LLM_MINUTE_TOKENS'],'30000')
        self.assertEqual(worker['spec']['strategy']['type'],'Recreate')
        self.assertIn('@sha256:4cd6a12c1b046c03b74195b2d93aff183d8465230d364b527fa116fd25624a91',worker['spec']['template']['spec']['containers'][0]['image'])
        failed = subprocess.run(['helm','template','spi-triage',str(ROOT/'charts/spi-triage'),'--set','s3Evidence.publicOrigin=https://evil.invalid'],capture_output=True)
        self.assertNotEqual(failed.returncode,0)
