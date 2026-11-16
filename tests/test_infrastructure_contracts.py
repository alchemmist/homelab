import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('infra_contract', ROOT/'scripts/check_infrastructure_contracts.py')
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)

class InfrastructureContracts(unittest.TestCase):
    def test_registered_consumers_and_mesh(self):
        self.assertEqual(contract.check(ROOT), 9)

    def fixture(self, directory):
        root = Path(directory)
        c = json.loads((ROOT/'deploy/contracts/infrastructure.json').read_text())
        names = ['deploy/contracts/infrastructure.json', c['meshRegistry'], c['ansibleInventory']]
        names += [x['file'] for x in c['issuerTransport']['consumers']]
        for name in names:
            p = root/name
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/name, p)
        return root

    def test_drift_rejected_and_generation_only_changes_ip(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            p = root/'deploy/platform/rancher/values.yaml'
            original = p.read_text()
            p.write_text(original.replace('10.43.218.222', '10.43.218.223'))
            with self.assertRaisesRegex(ValueError, 'Issuer IP drift'):
                contract.check(root)
            contract.check(root, write=True)
            self.assertEqual(p.read_text(), original)

    def test_scope_widening_not_regenerated(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            p = root/'deploy/platform/rancher/values.yaml'
            p.write_text(p.read_text().replace('[auth.socrat.alchemmist.xyz]', '[auth.socrat.alchemmist.xyz, other.example]'))
            with self.assertRaisesRegex(ValueError, 'scope widened'):
                contract.check(root, write=True)

    def test_inventory_drift_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            p = root/'ansible/inventory/hosts.yml'
            p.write_text(p.read_text().replace('ansible_host: 10.250.0.41', 'ansible_host: 10.250.0.99'))
            with self.assertRaisesRegex(ValueError, 'Inventory endpoint drift: socrat-5'):
                contract.check(root)

    def test_bootstrap_requires_opt_in_and_refuses_existing_workloads(self):
        p = yaml.safe_load((ROOT/'ansible/playbooks/argocd.yml').read_text())[0]
        self.assertFalse(p['vars']['argocd_allow_empty_bootstrap'])
        self.assertTrue(p['vars']['argocd_values_local'].endswith('/deploy/platform/argo-cd/values.yaml'))
        tasks = p['tasks']
        self.assertIn('ansible.builtin.assert', tasks[0])
        self.assertIn('ansible.builtin.assert', tasks[2])
        helm = next(t['ansible.builtin.command']['argv'] for t in tasks
                    if t.get('name') == 'Install Argo CD control plane only')
        self.assertIn('install', helm)
        self.assertNotIn('upgrade', helm)
        self.assertNotIn('--install', helm)

    def test_bootstrap_compatibility_path_is_same_canonical_source(self):
        alias = ROOT/'deploy/argocd/values.yaml'
        self.assertTrue(alias.is_symlink())
        self.assertEqual(alias.resolve(), (ROOT/'deploy/platform/argo-cd/values.yaml').resolve())
        self.assertEqual(alias.read_bytes(), alias.resolve().read_bytes())

if __name__ == '__main__':
    unittest.main()
