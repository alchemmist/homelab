"""Check the retired report intake and the surviving artifact/handoff contracts."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Reports(unittest.TestCase):
    """Cover removal of webhook and storage authorities without executing a consumer."""

    def test_retired_report_intake_is_not_shipped(self) -> None:
        for relative in (
            "charts/openhands/files/report-intake",
            "charts/openhands/templates/report-intake.yaml",
            "docs/n8n/mutation-reports/intake.json",
            "docs/n8n/mutation-reports/pr-lifecycle.json",
        ):
            with self.subTest(relative=relative):
                assert not (ROOT / relative).exists()

    def test_artifact_protocol_rejects_plans_and_multiple_files(self) -> None:
        """Check artifact replies reject plans and multiple code blocks."""
        spec = importlib.util.spec_from_file_location(
            "artifact", ROOT / "services/pi-monori/artifact.py"
        )
        art = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(art)
        sample = "```python\ndef test_fixture() -> None:\n    assert 1 == 1\n```"
        assert art.artifact_response("transport warning\n" + sample).startswith(
            "def test_fixture"
        )
        for raw in (
            "I will write a test.",
            sample + "\n" + sample,
            "```sh\necho test\n```",
        ):
            with self.assertRaises(ValueError):
                art.artifact_response(raw)

    def test_distributed_handoff_gate_matches_canonical_gate(self) -> None:
        """Check the distributed handoff gate is byte-equal to the canonical one."""
        assert (ROOT / "scripts/openhands-pr-ready.py").read_bytes() == (
            ROOT / "charts/openhands/files/steward/ready_gate.py"
        ).read_bytes()
