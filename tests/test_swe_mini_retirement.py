"""Keep the retired SWE Mini publisher disconnected from the retained service source."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_no_swe_mini_release_workflow() -> None:
    """No Actions entry point may publish the service or pass its app name to deploy."""
    workflows = _ROOT / ".github/workflows"
    for workflow in workflows.iterdir():
        if workflow.is_file() and workflow.suffix in {".yaml", ".yml"}:
            assert "swe-mini" not in workflow.name
            assert "swe-mini" not in workflow.read_text(encoding="utf-8"), workflow


def test_no_swe_mini_gitops_owner() -> None:
    """Cover renamed child manifests in the recursive root source as well as chart inputs."""
    for manifest in (_ROOT / "deploy/argocd/apps").rglob("*"):
        if manifest.is_file() and manifest.suffix in {".yaml", ".yml", ".json"}:
            assert "swe-mini" not in manifest.read_text(encoding="utf-8"), manifest
    assert not (_ROOT / "deploy/swe-mini").exists()
    assert not (_ROOT / "charts/swe-mini").exists()
    assert not (_ROOT / "scripts/provision-swe-mini.py").exists()
