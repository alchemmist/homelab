"""The native SPI RPC endpoint is the fixed Service, not Pod/public DNS/IP."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VIP_TEMPLATE_REF_COUNT = 2
NATIVE_STAGE_URL_COUNT = 5


class SpiServiceVipTests(unittest.TestCase):
    """Require the fixed SPI Service VIP on values, the chart, and n8n stages."""

    def test_existing_service_vip_is_declared_and_rendered_only_on_service(
        self,
    ) -> None:
        """Require the VIP in values and only in the Service half of the worker chart."""
        values = (ROOT / "deploy/spi-triage/values.yaml").read_text()
        assert re.search(r"(?m)^serviceClusterIP: 10\.43\.194\.185 ", values)
        worker = (ROOT / "charts/spi-triage/templates/worker.yaml").read_text()
        assert worker.count(".Values.serviceClusterIP") == VIP_TEMPLATE_REF_COUNT
        assert ".Values.serviceClusterIP" not in worker.split("kind: Service")[0]

    def test_five_native_stage_urls_no_post_retry(self) -> None:
        """Require five exact stage URLs and no HTTP Request retryOnFail."""
        w = json.loads((ROOT / "docs/n8n/spi/triage-workflow.json").read_text())
        found = []
        for n in w["nodes"]:
            if n["type"] == "n8n-nodes-base.httpRequest":
                assert re.search(
                    r"^http://10\.43\.194\.185:8080/(claim|match|collect|analyze|publish)$",
                    n["parameters"]["url"],
                )
                assert not n.get("retryOnFail", False)
                found.append(n["parameters"]["url"])
        assert len(found) == NATIVE_STAGE_URL_COUNT
