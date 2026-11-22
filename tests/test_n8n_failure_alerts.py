"""Tests for the n8n failure alert sync script."""

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/n8n"))
import pytest
import sync_failure_alerts as sync

TEMPLATE = json.loads((ROOT / "docs/n8n/workflow-failure-alerts.json").read_text())


def _mapping(value: object) -> dict[str, object]:
    """Return the assert-verified mapping view of a parsed JSON value."""
    assert isinstance(value, dict)
    result: dict[str, object] = value
    return result


def _text(value: object) -> str:
    """Return the assert-verified string view of a parsed JSON value."""
    assert isinstance(value, str)
    return value


class FailureAlertsTests(unittest.TestCase):
    """Run the n8n failure alert node against fake notifications."""

    def notification(self, payload, handler="4321") -> dict[str, object]:
        """Run the alert template's JS code against a payload via node:vm."""
        code = TEMPLATE["nodes"][1]["parameters"]["jsCode"]
        js = 'const vm=require("node:vm");const x=JSON.parse(process.argv[1]);const fn=vm.runInNewContext("(function(){"+x.code+"})",{items:[{json:x.payload}],$execution:{id:x.handler}});console.log(JSON.stringify(fn()));'
        result: dict[str, object] = json.loads(
            subprocess.check_output(
                [
                    "node",
                    "-e",
                    js,
                    json.dumps({"code": code, "payload": payload, "handler": handler}),
                ]
            )
        )[0]["json"]
        return result

    def test_metadata_only_and_trusted_url(self) -> None:
        """Only safe metadata and the trusted URL reach the alert."""
        p = {
            "workflow": {"id": "abc123", "name": "Calendar"},
            "execution": {
                "id": "123",
                "url": "https://evil.invalid/?token=secret",
                "lastNodeExecuted": "Announce",
                "error": {"message": "secret", "stack": "private"},
                "executionContext": {"token": "private"},
            },
        }
        result = self.notification(p)
        text = json.dumps(result)
        assert "secret" not in text
        assert "private" not in text
        assert "evil.invalid" not in text
        assert (
            _mapping(result["alert"])["generatorURL"]
            == "https://n8n.socrat.alchemmist.xyz/workflow/abc123/executions/123"
        )
        assert (
            _mapping(result["alert"])["fingerprint"]
            == _mapping(self.notification(p, "9999")["alert"])["fingerprint"]
        )
        p["execution"]["id"] = "124"
        assert (
            _mapping(result["alert"])["fingerprint"]
            != _mapping(self.notification(p)["alert"])["fingerprint"]
        )

    def test_trigger_failure_without_execution_id(self) -> None:
        """Trigger failures alert without leaking the error message."""
        p = {
            "workflow": {"id": "abc", "name": "Calendar"},
            "trigger": {"error": {"message": "password"}},
        }
        result = self.notification(p)
        assert "Trigger failure" in _text(
            _mapping(_mapping(result["alert"])["annotations"])["description"]
        )
        assert "password" not in json.dumps(result)
        assert (
            _mapping(result["alert"])["fingerprint"]
            != _mapping(self.notification(p, "9999")["alert"])["fingerprint"]
        )

    def test_no_message_storage_retries_recursion_or_spi_ingress(self) -> None:
        """The template stores no messages, retries or recursion."""
        assert "errorWorkflow" not in TEMPLATE["settings"]
        assert TEMPLATE["settings"]["saveDataErrorExecution"] == "none"
        assert TEMPLATE["settings"]["saveDataSuccessExecution"] == "none"
        assert TEMPLATE["nodes"][0]["type"] == "n8n-nodes-base.errorTrigger"
        last = TEMPLATE["nodes"][-1]
        assert not last.get("retryOnFail", False)
        assert "onError" not in last
        assert last["parameters"]["url"] == "http://socrat-bot.socrat-bot.svc:8080/v1/messages"

    def wf(self, active=True) -> dict[str, object]:
        """Build an example workflow document in the requested active state."""
        return {
            "id": "abc",
            "name": "Calendar",
            "nodes": [{"id": "n", "credentials": {"native": {"id": "credential-ref"}}}],
            "connections": {},
            "settings": {"executionTimeout": 1800},
            "active": active,
            "versionId": "v1",
            "activeVersionId": "v1" if active else None,
            "activeVersion": {
                "nodes": [{"id": "n", "credentials": {"native": {"id": "credential-ref"}}}],
                "connections": {},
            }
            if active
            else None,
        }

    def test_guard_rejects_unpublished_changes_and_other_handler(self) -> None:
        """Guard rejects unpublished changes and foreign handlers."""
        w = self.wf()
        _mapping(w["activeVersion"])["nodes"] = []
        with pytest.raises(RuntimeError):
            sync.guard(w, "handler")
        w = self.wf()
        _mapping(w["settings"])["errorWorkflow"] = "other"
        with pytest.raises(RuntimeError):
            sync.guard(w, "handler")

    def test_only_settings_change_and_active_state_preserved(self) -> None:
        """Only settings change; active state drives activation alone."""
        for active in (True, False):
            original = self.wf(active)
            current = copy.deepcopy(original)
            calls = []

            def api(
                method, path, body=None, original=original, current=current, calls=calls
            ) -> dict[str, object]:
                calls.append((method, path, body))
                if method == "PUT":
                    assert body["nodes"] == original["nodes"]
                    assert body["connections"] == original["connections"]
                    current["settings"] = body["settings"]
                    current["versionId"] = "v2"
                if method == "POST":
                    assert path.endswith("/activate")
                    current["activeVersionId"] = "v2"
                return copy.deepcopy(current)

            result = sync.bind(api, original, "handler")
            assert result["active"] == active
            assert result["settings"] == {
                "executionTimeout": 1800,
                "errorWorkflow": "handler",
            }
            assert sum(m == "POST" for m, _, _ in calls) == int(active)
            assert not any("execute" in path or "deactivate" in path for _, path, _ in calls)

    def test_idempotent_and_concurrent_drift_stops(self) -> None:
        """A bound workflow is idempotent until drift appears."""
        w = self.wf()
        _mapping(w["settings"])["errorWorkflow"] = "handler"
        calls = []

        def api(*args) -> dict[str, object]:
            calls.append(args)
            return copy.deepcopy(w)

        sync.bind(api, w, "handler")
        assert len(calls) == 1
        before = self.wf()
        w["name"] = "Changed"
        with pytest.raises(RuntimeError):
            sync.bind(api, before, "handler")

    def test_only_native_github_registration_may_change(self) -> None:
        """Only native GitHub registration fields may change."""
        before = self.wf()
        before["nodes"] = [{"id": "n", "name": "Push", "type": "n8n-nodes-base.githubTrigger"}]
        before["staticData"] = {
            "node:Push": {
                "webhookId": 1,
                "webhookSecret": "old",
                "webhookEvents": ["push"],
            },
            "global": {"checkpoint": "preserved"},
        }
        after = copy.deepcopy(before)
        _mapping(after["settings"])["errorWorkflow"] = "handler"
        _mapping(_mapping(after["staticData"])["node:Push"]).update(
            webhookId=2, webhookSecret="new"
        )
        sync.check(before, after, "handler")
        _mapping(_mapping(after["staticData"])["global"])["checkpoint"] = "changed"
        with pytest.raises(RuntimeError):
            sync.check(before, after, "handler")
        after = copy.deepcopy(before)
        _mapping(after["settings"])["errorWorkflow"] = "handler"
        _mapping(_mapping(after["staticData"])["node:Push"])["webhookEvents"] = ["issues"]
        with pytest.raises(RuntimeError):
            sync.check(before, after, "handler")

    def test_transient_put_state_requires_authoritative_readback(self) -> None:
        """Transient PUT state requires an authoritative readback."""
        before = self.wf()
        before["staticData"] = {"checkpoint": "must-remain"}
        transient = copy.deepcopy(before)
        _mapping(transient["settings"])["errorWorkflow"] = "handler"
        transient["staticData"] = None
        sync.check(before, transient, "handler", verify_static=False)
        with pytest.raises(RuntimeError):
            sync.check(before, transient, "handler")
        stable = copy.deepcopy(before)
        _mapping(stable["settings"])["errorWorkflow"] = "handler"
        sync.check(before, stable, "handler")

    def test_unexpected_settings_drift_stops(self) -> None:
        """Unexpected settings drift stops the sync."""
        before = self.wf()
        after = copy.deepcopy(before)
        after["settings"] = {"errorWorkflow": "handler"}
        with pytest.raises(RuntimeError):
            sync.check(before, after, "handler")


if __name__ == "__main__":
    unittest.main()
