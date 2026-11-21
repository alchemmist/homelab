"""Offline checks that Fleet GitOps is absent and workloads stay on Argo CD."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_FILES = (
    ROOT / "ansible/playbooks/wiki.yml",
    ROOT / "scripts/bootstrap-wiki-runtime.py",
)
BOOTSTRAP_FORBIDDEN = (
    "fleet.cattle.io",
    "kind: GitRepo",
    "deploy/fleet/",
    "clusters.fleet.cattle.io",
    "fleet-local",
    "wiki-deployer",
)


class NoFleetGitOpsTests(unittest.TestCase):
    """Read-only repository checks for Fleet GitRepo and bundle absence."""

    def test_deploy_has_no_fleet_gitrepos_or_bundle_files(self) -> None:
        """Require an empty Fleet bundle list and no Fleet GitRepo manifests."""
        bundles = sorted(
            path.relative_to(ROOT).as_posix() for path in (ROOT / "deploy").rglob("fleet.yaml")
        )
        assert bundles == []
        assert not (ROOT / "deploy/fleet").exists()
        gitrepos = []
        for path in (ROOT / "deploy").rglob("*.yaml"):
            text = path.read_text(errors="ignore")
            if "fleet.cattle.io" in text or "kind: GitRepo" in text:
                gitrepos.append(path.relative_to(ROOT).as_posix())
        assert gitrepos == []

    def test_wiki_bootstrap_does_not_register_fleet(self) -> None:
        """Reject Fleet markers in the wiki bootstrap playbook and script."""
        for path in BOOTSTRAP_FILES:
            text = path.read_text()
            for needle in BOOTSTRAP_FORBIDDEN:
                assert needle not in text, (
                    f"{path.relative_to(ROOT).as_posix()} still references {needle}"
                )

    def test_former_fleet_workloads_stay_on_argo_applications(self) -> None:
        """Keep former Fleet workloads on their Argo CD Application sources."""
        wiki = (ROOT / "deploy/argocd/apps/wiki-runtime.yaml").read_text()
        n8n = (ROOT / "deploy/argocd/apps/n8n.yaml").read_text()
        assert "kind: Application" in wiki
        assert "path: deploy/wiki-runtime/chart" in wiki
        assert "kind: Application" in n8n
        assert "path: charts/n8n" in n8n


if __name__ == "__main__":
    unittest.main()
