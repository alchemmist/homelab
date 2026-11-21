import importlib.util
import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "demo_validation", ROOT / "scripts/validate-openhands-demo.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# The demo schedule runs strictly bounded sessions (see services/openhands/.../schedule.json).
SCHEDULE_TIMEOUT_SECONDS = 300
JOB_DEADLINE_SECONDS = 45


class LoopSetup(unittest.TestCase):
    def test_official_mcp_is_version_and_integrity_pinned(self):
        p = json.loads((ROOT / "tools/openhands-mcp/package-lock.json").read_text())
        fs = p["packages"]["node_modules/@modelcontextprotocol/server-filesystem"]
        assert fs["version"] == "2.4.0"
        assert (
            fs["integrity"]
            == "sha512-BoT8Gws5MsetfAey4vDyuzy8WYQES6mGYLSShuqSNGAC0X0NBV4p78/R78KfW4RkxtWz+zxhS9jwhzJrQUTt2Q=="
        )

    def test_local_scheduler_callbacks_do_not_cross_browser_oidc(self):
        values = yaml.safe_load((ROOT / "deploy/openhands/values.yaml").read_text())
        env = {x["name"]: x.get("value") for x in values["config"]["extraEnv"]}
        assert env["AUTOMATION_BASE_URL"] == "http://127.0.0.1:8000"
        assert values["oidc"]["enabled"]
        assert not values["ingress"]["enabled"]

    def test_schedule_is_paused_bounded_and_uses_pinned_image_sdk(self):
        c = json.loads((ROOT / "services/openhands/the-loop-demo/schedule.json").read_text())
        assert not c["enabled"]
        assert not c["keep_alive"]
        assert c["timeout"] == SCHEDULE_TIMEOUT_SECONDS
        assert c["trigger"]["timezone"] == "Europe/Moscow"
        assert c["runtime"] == {"setup_script_path": None, "entrypoint": "python main.py"}

    def test_overlapping_network_policies_fail_closed(self):
        labels = {"app": "fixture", "homelab-app": "openhands-demo-validation"}
        assert m.selector_matches({}, labels)
        assert not m.selector_matches({"matchLabels": {"app": "authentik-postgres"}}, labels)
        assert m.selector_matches(
            {"matchExpressions": [{"key": "app", "operator": "In", "values": ["fixture"]}]}, labels
        )
        assert m.selector_matches(
            {"matchExpressions": [{"key": "missing", "operator": "NotIn", "values": ["x"]}]}, labels
        )
        assert not m.selector_matches(
            {"matchExpressions": [{"key": "app", "operator": "DoesNotExist"}]}, labels
        )
        with self.assertRaises(ValueError):
            m.selector_matches(
                {"matchExpressions": [{"key": "app", "operator": "Unknown"}]}, labels
            )

    def test_independent_review_has_no_network_or_credentials(self):
        cm, np, job = m.resources("fixture-name", "candidate-code", "original-tests")
        assert cm["data"]["test_intervals.py"] == "original-tests"
        assert np["spec"]["egress"] == []
        pod = job["spec"]["template"]["spec"]
        c = pod["containers"][0]
        assert not pod["automountServiceAccountToken"]
        assert "serviceAccountName" not in pod
        assert "hostNetwork" not in pod
        assert c["securityContext"]["readOnlyRootFilesystem"]
        assert c["volumeMounts"][0]["readOnly"]
        assert pod["volumes"] == [{"name": "snapshot", "configMap": {"name": "fixture-name"}}]
        assert job["spec"]["backoffLimit"] == 0
        assert job["spec"]["activeDeadlineSeconds"] == JOB_DEADLINE_SECONDS


if __name__ == "__main__":
    unittest.main()
