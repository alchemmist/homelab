import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_FILES = (
    ROOT / 'ansible/playbooks/wiki.yml',
    ROOT / 'scripts/bootstrap-wiki-runtime.py',
)
BOOTSTRAP_FORBIDDEN = (
    'fleet.cattle.io',
    'kind: GitRepo',
    'deploy/fleet/',
    'clusters.fleet.cattle.io',
    'fleet-local',
    'wiki-deployer',
)


class NoFleetGitOpsTests(unittest.TestCase):
    def test_deploy_has_no_fleet_gitrepos_or_bundle_files(self):
        bundles = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / 'deploy').rglob('fleet.yaml'))
        self.assertEqual(bundles, [])
        self.assertFalse((ROOT / 'deploy/fleet').exists())
        gitrepos = []
        for path in (ROOT / 'deploy').rglob('*.yaml'):
            text = path.read_text(errors='ignore')
            if 'fleet.cattle.io' in text or 'kind: GitRepo' in text:
                gitrepos.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(gitrepos, [])

    def test_wiki_bootstrap_does_not_register_fleet(self):
        for path in BOOTSTRAP_FILES:
            text = path.read_text()
            for needle in BOOTSTRAP_FORBIDDEN:
                self.assertNotIn(needle, text, f'{path.relative_to(ROOT).as_posix()} still references {needle}')

    def test_former_fleet_workloads_stay_on_argo_applications(self):
        wiki = (ROOT / 'deploy/argocd/apps/wiki-runtime.yaml').read_text()
        n8n = (ROOT / 'deploy/argocd/apps/n8n.yaml').read_text()
        self.assertIn('kind: Application', wiki)
        self.assertIn('path: deploy/wiki-runtime/chart', wiki)
        self.assertIn('kind: Application', n8n)
        self.assertIn('path: charts/n8n', n8n)


if __name__ == '__main__':
    unittest.main()
