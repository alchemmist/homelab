import pathlib
import subprocess
import unittest
import yaml
ROOT=pathlib.Path(__file__).resolve().parents[2]

class UpgradeSafety(unittest.TestCase):
    def test_backup_is_separate_retained_readonly_source_and_offline(self):
        r=subprocess.check_output(['helm','template','openhands',str(ROOT/'charts/openhands'),'-n','openhands','-f',str(ROOT/'deploy/openhands/values.yaml')],text=True)
        objs=[x for x in yaml.safe_load_all(r) if x]
        j=next(x for x in objs if x['kind']=='Job' and x['metadata']['name']=='openhands-cold-backup-20261119')
        p=j['spec']['template']['spec'];self.assertFalse(p['automountServiceAccountToken'])
        self.assertEqual(p['volumes'][0]['persistentVolumeClaim'],{'claimName':'data-openhands-0','readOnly':True})
        self.assertEqual(p['volumes'][1]['persistentVolumeClaim']['claimName'],'openhands-cold-backups')
        np=next(x for x in objs if x['kind']=='NetworkPolicy' and x['metadata']['name']=='openhands-backup-pre142')
        self.assertEqual(np['spec']['egress'],[])
        self.assertEqual(j['spec']['template']['metadata']['labels']['app'], 'openhands-backup-pre142')
        boundary=next(x for x in objs if x['kind']=='NetworkPolicy' and x['metadata']['name']=='openhands-boundary')
        self.assertIn({'key':'app','operator':'NotIn','values':['openhands-backup-pre142']}, boundary['spec']['podSelector']['matchExpressions'])
        self.assertNotIn('PRIVATE KEY',(ROOT/'charts/openhands/files/backup-recipient.pem').read_text())

    def test_otel_remains_sole_scraper(self):
        v=yaml.safe_load((ROOT/'charts/prometheus/values.yaml').read_text())['kube-prometheus-stack']['prometheus']['prometheusSpec']
        self.assertEqual(v['serviceMonitorSelector']['matchLabels']['homelab.alchemmist.xyz/scrape-owner'],'retired-legacy-prometheus')
        c=next(x for x in v['containers'] if x['name']=='otel-cluster')
        self.assertEqual(c['args'],['--config=/etc/otel/config/collector.yaml','--config=/etc/otel/software-updates/collector.yaml'])
        addon=yaml.safe_load((ROOT/'charts/prometheus/templates/software-update-otel.yaml').read_text().replace('{{ .Release.Namespace }}','cattle-monitoring-system'))
        config=yaml.safe_load(addon['data']['collector.yaml'])
        self.assertEqual(config['service']['pipelines']['metrics']['receivers'],['prometheus','otlp','prometheus/software_updates'])
        self.assertEqual(config['receivers']['prometheus/software_updates']['config']['scrape_configs'][0]['job_name'],'monitoring-update-watch')

if __name__=='__main__':unittest.main()
