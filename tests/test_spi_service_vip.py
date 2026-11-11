"""The native SPI RPC endpoint is the fixed Service, not Pod/public DNS/IP."""
import json,re,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class SpiServiceVipTests(unittest.TestCase):
    def test_existing_service_vip_is_declared_and_rendered_only_on_service(self):
        values=(ROOT/'deploy/spi-triage/values.yaml').read_text();self.assertRegex(values,r'(?m)^serviceClusterIP: 10\.43\.194\.185 ')
        worker=(ROOT/'charts/spi-triage/templates/worker.yaml').read_text();self.assertEqual(worker.count('.Values.serviceClusterIP'),2)
        self.assertNotIn('.Values.serviceClusterIP',worker.split('kind: Service')[0])
    def test_five_native_stage_urls_no_post_retry(self):
        w=json.loads((ROOT/'docs/n8n/spi/triage-workflow.json').read_text());found=[]
        for n in w['nodes']:
            if n['type']=='n8n-nodes-base.httpRequest':
                self.assertRegex(n['parameters']['url'],r'^http://10\.43\.194\.185:8080/(claim|match|collect|analyze|publish)$')
                self.assertFalse(n.get('retryOnFail',False));found.append(n['parameters']['url'])
        self.assertEqual(len(found),5)
