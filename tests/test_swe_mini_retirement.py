"""Keep the retired SWE Mini publisher disconnected from the retained service source."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_no_swe_mini_release_workflow() -> None:
    """No Actions entry point may publish the service or pass its app name to deploy."""
    workflows = _ROOT / ".github/workflows"
    for workflow in workflows.iterdir():
        if workflow.suffix in {".yaml", ".yml"}:
            assert "swe-mini" not in workflow.name
            assert "swe-mini" not in workflow.read_text(), workflow
