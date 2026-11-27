"""Offline checks for the n8n log-streaming bridge to otel-loki."""

import ast
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_REL = "scripts/n8n-otel-log-bridge.py"
BRIDGE_CHART = "charts/n8n/scripts/n8n-otel-log-bridge.py"
VALUES = ROOT / "charts" / "n8n" / "values.yaml"


def load_bridge():
    """Import the bridge module offline with the required environment."""
    import os

    os.environ.setdefault("LOKI_URL", "https://otel-loki.example:3100")
    os.environ.setdefault("LOKI_SERVER_NAME", "otel-loki.example")
    spec = importlib.util.spec_from_file_location("bridge", ROOT / BRIDGE_REL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class N8nOtelLogBridge(unittest.TestCase):
    """Prove the bridge is stdlib-only, safe and renders correctly."""

    def test_chart_copy_matches_root_script(self) -> None:
        """The chart-embedded copy matches the maintained root source."""
        assert (ROOT / BRIDGE_REL).read_text() == (ROOT / BRIDGE_CHART).read_text()

    def test_bridge_is_stdlib_only(self) -> None:
        """Only standard-library imports are allowed in the bridge."""
        tree = ast.parse((ROOT / BRIDGE_REL).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= {
            "json",
            "os",
            "ssl",
            "threading",
            "time",
            "urllib",
            "http",
        }

    def test_bridge_parses_locally(self) -> None:
        """Python 3 syntax check must succeed locally."""
        subprocess.run(["python3", "-m", "py_compile", str(ROOT / BRIDGE_REL)], check=True)

    def test_configmap_renders_only_when_enabled(self) -> None:
        """ConfigMap appears only when the bridge flag is enabled."""
        assert subprocess.run(
            [
                "helm",
                "template",
                "n8n",
                str(ROOT / "charts" / "n8n"),
                "--set",
                "otelLogBridge.enabled=true",
                "--show-only",
                "templates/otel-log-bridge.yaml",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.count("kind: ConfigMap") == 1
        docs = subprocess.run(
            ["helm", "template", "n8n", str(ROOT / "charts" / "n8n"), "--set", "otelLogBridge.enabled=true"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "n8n-otel-log-bridge" in docs.stdout

    def test_sidecar_mounts_dedicated_leaf_and_lives_in_pod(self) -> None:
        """When enabled the deployment gains the bridge sidecar with the n8n leaf."""
        out = subprocess.run(
            [
                "helm",
                "template",
                "n8n",
                str(ROOT / "charts" / "n8n"),
                "--set",
                "otelLogBridge.enabled=true",
                "--show-only",
                "templates/deployment.yaml",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        doc = next(yaml.safe_load_all(out))
        containers = doc["spec"]["template"]["spec"]["containers"]
        names = [container["name"] for container in containers]
        assert "otel-log-bridge" in names
        bridge = next(c for c in containers if c["name"] == "otel-log-bridge")
        mounts = {m["name"]: m for m in bridge["volumeMounts"]}
        assert mounts["otel-log-bridge-tls"]["readOnly"] is True
        assert mounts["otel-log-bridge-tls"]["mountPath"] == "/etc/otel-tls"
        assert mounts["otel-log-bridge-script"]["readOnly"] is True
        env = {e["name"]: e["value"] for e in bridge["env"]}
        assert env["LOKI_URL"].startswith("https://otel-loki.cattle-monitoring-system.svc")
        assert env["TLS_DIR"] == "/etc/otel-tls"
        volumes = {v["name"]: v for v in doc["spec"]["template"]["spec"]["volumes"]}
        assert volumes["otel-log-bridge-tls"]["secret"]["secretName"] == "otel-app-tls-n8n"
        assert bridge["securityContext"]["readOnlyRootFilesystem"] is True
        assert bridge["securityContext"]["allowPrivilegeEscalation"] is False

    def test_values_enable_bridge_in_chart_and_deploy(self) -> None:
        """Chart values (the live ArgoCD source) enable the bridge; deploy values match."""
        values = yaml.safe_load(VALUES.read_text())
        assert values["otelLogBridge"]["enabled"] is True
        assert values["otelLogBridge"]["secretName"] == "otel-app-tls-n8n"

        def disabled() -> subprocess.CompletedProcess:
            """Render with the bridge force-disabled."""
            return subprocess.run(
                [
                    "helm",
                    "template",
                    "n8n",
                    str(ROOT / "charts" / "n8n"),
                    "--set",
                    "otelLogBridge.enabled=false",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

        enabled = subprocess.run(
            ["helm", "template", "n8n", str(ROOT / "charts" / "n8n")],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "n8n-otel-log-bridge" not in disabled().stdout
        # A bridge-script edit must roll the pod: the configmap is checksummed
        # into the pod template whenever the sidecar is rendered.
        assert "checksum/otel-log-bridge:" in enabled.stdout
        assert "checksum/otel-log-bridge:" not in disabled().stdout
        deploy = yaml.safe_load((ROOT / "deploy" / "n8n" / "values.yaml").read_text())
        assert deploy["otelLogBridge"] == {
            "enabled": True,
            "secretName": "otel-app-tls-n8n",
        }

    def test_bridge_silences_access_logs_and_never_prints_payloads(self) -> None:
        """The bridge must not log payload contents nor request paths."""
        source = (ROOT / BRIDGE_REL).read_text()
        assert "def log_message" in source
        assert "log_message(self, fmt, *args)" in source
        assert "secret" not in source.lower()

    def test_loki_push_format(self) -> None:
        """The push payload matches the Loki streams JSON contract."""
        module = load_bridge()
        source = (ROOT / BRIDGE_REL).read_text()
        assert '"/loki/api/v1/push"' in source
        assert "job" in source and "n8n" in source

    def test_labels_read_n8n_event_shape(self) -> None:
        """n8n log-streaming events nest workflowId in payload and use eventName."""
        module = load_bridge()
        labels = module.event_labels(
            {
                "id": "evt-id",
                "eventName": "n8n.workflow.started",
                "payload": {"workflowId": "wf123", "executionId": "90718"},
            }
        )
        assert labels == {
            "job": "n8n",
            "source": "n8n-log-streaming",
            "event": "n8n.workflow.started",
            "workflow_id": "wf123",
        }
        legacy = module.event_labels({"event": "evt", "workflowId": "wf9"})
        assert legacy["event"] == "evt"
        assert legacy["workflow_id"] == "wf9"
        assert module.event_labels({})["workflow_id"] == "none"

    def test_pki_and_mirror_registration(self) -> None:
        """n8n is registered in the otel PKI and the mirror destinations."""
        pki = list(
            yaml.safe_load_all(
                (ROOT / "deploy" / "monitoring" / "otel-application-pki.yaml").read_text()
            )
        )
        cert = next(
            d
            for d in pki
            if d
            and d.get("kind") == "Certificate"
            and d["metadata"]["name"] == "otel-app-tls-n8n"
        )
        assert cert["spec"]["commonName"] == "otel-app-n8n"
        assert "client auth" in cert["spec"]["usages"]
        assert cert["spec"]["secretName"] == "otel-app-tls-n8n"

        creds = yaml.safe_load_all(
            (ROOT / "deploy" / "monitoring" / "otel-application-credentials.yaml").read_text()
        )
        config, roles = None, []
        for doc in creds:
            if doc is None:
                continue
            if doc.get("kind") == "ConfigMap":
                config = doc
            if doc.get("kind") == "Role":
                roles.append(doc)
        destinations = json.loads(config["data"]["destinations.json"])
        n8n = next(d for d in destinations if d["application"] == "n8n")
        assert n8n == {
            "application": "n8n",
            "namespace": "automation",
            "secret": "otel-app-tls-n8n",
            "reloadDeployments": [],
        }
        automation = next(r for r in roles if r["metadata"]["namespace"] == "automation")
        assert automation["rules"][0]["resourceNames"] == ["otel-app-tls-n8n"]

        scope = json.loads(
            (ROOT / "deploy" / "monitoring" / "otel-application-scope.json").read_text()
        )
        registered = next(
            a
            for a in scope["applications"]
            if a.get("application", a.get("namespace")) == "n8n"
        )
        assert registered["dedicatedClientCertificate"] == "otel-app-tls-n8n"
        assert registered["workloads"] == ["n8n"]


if __name__ == "__main__":
    unittest.main()
