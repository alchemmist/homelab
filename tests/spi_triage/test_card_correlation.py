"""Tests for SPI triage card correlation logic."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "charts/spi-triage/files"))
import pytest
from card_correlation import record_receipt
from core import Failure, Store, normalize

# The handoff node sends two copies per receipt and waits 5s for the API answer.
COPIES_PER_RECEIPT = 2
HANDOFF_TIMEOUT_MS = 5000


class CorrelationTests(unittest.TestCase):
    """Tests for SPI card correlation across reports."""

    def setUp(self) -> None:
        """Open a fresh store and card payload fixture."""
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "jobs.sqlite")
        self.payload = {
            "version": 1,
            "source": "https://am.example",
            "alert": {
                "status": "firing",
                "startsAt": "2026-01-01T00:00:00Z",
                "fingerprint": "",
                "labels": {"alertname": "Test", "secret": "private"},
                "annotations": {},
            },
            "receipt": {
                "key": "Test/cluster",
                "copies": [
                    {"chat_id": 1, "message_id": 2},
                    {"chat_id": 3, "message_id": 4},
                ],
            },
        }

    def tearDown(self) -> None:
        """Close the scratch store."""
        self.tmp.cleanup()

    def test_restart_duplicates_raw_identity_and_copies(self) -> None:
        """Verify restart replays raw identity and copies idempotently."""
        expected = normalize(self.payload)
        for store in [self.store, Store(self.store.path)]:
            result = record_receipt(store, self.payload)
            assert result["event_key"] == expected["event_key"]
        with self.store.db() as c:
            assert (
                c.execute("SELECT count(*) FROM telegram_receipts").fetchone()[0]
                == COPIES_PER_RECEIPT
            )
        assert b"private" not in Path(self.store.path).read_bytes()

    def test_resolved_flap_and_unknown(self) -> None:
        """Verify resolution flaps tie episodes and stay bounded."""
        firing = record_receipt(self.store, self.payload)
        self.payload["alert"]["status"] = "resolved"
        resolved = record_receipt(self.store, self.payload)
        assert firing["episode"] == resolved["episode"]
        assert firing["event_key"] != resolved["event_key"]
        self.payload["alert"]["startsAt"] = "2026-01-02T00:00:00Z"
        self.payload["receipt"] = {"error": {"message": "private"}}
        new = record_receipt(self.store, self.payload)
        assert new["episode"] != firing["episode"]
        assert new["state"] == "unknown"

    def test_invalid_copy_and_empty_receipt(self) -> None:
        """Verify invalid copies and empty receipts fail closed."""
        self.payload["receipt"]["copies"] = [{"chat_id": 1, "message_id": "2"}]
        with pytest.raises(Failure):
            record_receipt(self.store, self.payload)
        self.payload["receipt"]["copies"] = []
        assert record_receipt(self.store, self.payload)["state"] == "unknown"

    def test_workflow_graph_and_actual_splitter(self) -> None:
        """Verify the shipped workflow graph matches the tested splitter."""
        w = json.loads((ROOT / "docs/n8n/socrat-bot/workflow.json").read_text())
        nodes = {n["name"]: n for n in w["nodes"]}
        assert nodes["Alertmanager Webhook"]["id"] == "c0ffee00-0001-4000-8000-000000000001"
        handoff = nodes["Record Telegram Receipt"]
        assert handoff["credentials"]["httpHeaderAuth"]["id"] == "SPI_WORKER_CREDENTIAL_ID"
        assert handoff["parameters"]["options"]["timeout"] == HANDOFF_TIMEOUT_MS
        assert (
            "$('One item per alert').itemMatching(index)"
            in nodes["Prepare Telegram Receipt"]["parameters"]["jsCode"]
        )
        assert ".first()" not in handoff["parameters"]["jsonBody"]
        assert (
            w["connections"]["Post Telegram Message"]["main"][0][0]["node"]
            == "Prepare Telegram Receipt"
        )
        assert (
            w["connections"]["Prepare Telegram Receipt"]["main"][0][0]["node"]
            == "Record Telegram Receipt"
        )
        assert nodes["Post Telegram Message"]["onError"] == "continueRegularOutput"
        script = nodes["One item per alert"]["parameters"]["jsCode"]
        alert = self.payload["alert"]
        alert["endsAt"] = "2026-01-01T01:00:00Z"
        js = (
            "const items = "
            + json.dumps(
                [
                    {
                        "json": {
                            "body": {
                                "externalURL": "https://am.example",
                                "alerts": [alert, alert],
                            }
                        }
                    }
                ]
            )
            + ";\nconsole.log(JSON.stringify((function(){"
            + script
            + "})()));"
        )
        output = json.loads(subprocess.check_output(["node", "-e", js]))
        assert len(output) == COPIES_PER_RECEIPT
        for item in output:
            assert item["json"]["source"] == "https://am.example"
            for field in ["startsAt", "endsAt", "fingerprint"]:
                assert item["json"]["alert"][field] == alert[field]
