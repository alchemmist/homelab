"""Conservative stateless release path; never silently target the stateful worker."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GatewayReleaseContract(unittest.TestCase):
    def test_explicit_gateway_target_keeps_existing_publication_and_owner(self):
        """Both targets use the same immutable image publisher and existing GitOps action."""
        source = (ROOT / ".github/workflows/ci.yml").read_text()
        assert "default: spi-triage" in source
        assert (
            "github.event_name == 'workflow_dispatch' && inputs.deploy_target == 'alert-graphs'"
            in source
        )
        assert (
            "github.event_name == 'workflow_dispatch' && inputs.deploy_target == 'spi-triage'"
            in source
        )
        assert (
            "github.event_name != 'workflow_dispatch' || inputs.deploy_target != 'alert-graphs'"
            not in source
        )
        assert source.count("uses: alchemmist/deploy-to-socrat@v1") == 2
        assert "app: grafana\n          component: gateway" in source
        assert source.count("image_version: ${{ steps.image.outputs.digest }}") == 2
        assert "environment: spi-triage-production" in source
        assert "kubectl" not in source
        assert "helm upgrade" not in source
