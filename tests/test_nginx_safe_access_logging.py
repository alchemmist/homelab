"""Offline chart rendering and real nginx parser tests; no cluster access."""

import re
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHARTS = ("private-gateway", "syncthing", "img-proxy", "litellm-infra", "socrat-home")


class SafeNginxLoggingTests(unittest.TestCase):
    """Verify nginx access logging renders with sensitive data stripped."""

    def render(self, chart: str) -> list[dict[str, object]]:
        """Render a chart and return its documents."""
        return list(
            yaml.safe_load_all(
                subprocess.check_output(
                    ["helm", "template", "test", str(ROOT / "charts" / chart)]
                    + (["--set", "privateGui.enabled=true"] if chart == "syncthing" else []),
                    text=True,
                )
            )
        )

    def test_render_and_safe_contract(self) -> None:
        """Every chart renders the safe logging contract."""
        for chart in CHARTS:
            with self.subTest(chart=chart):
                docs = self.render(chart)
                configs: list[str] = []
                for doc in docs:
                    if not doc or doc["kind"] != "ConfigMap":
                        continue
                    data = doc.get("data", {})
                    assert isinstance(data, dict)
                    for entry in data.values():
                        assert isinstance(entry, str)
                        if "log_format safe_json" in entry:
                            configs.append(entry)
                assert configs
                for config in configs:
                    fmt_match = re.search(r"log_format safe_json escape=json '([^']+)';", config)
                    assert fmt_match is not None
                    fmt = fmt_match.group(1)
                    for forbidden in (
                        "$request_uri",
                        '$request"',
                        "$args",
                        "$http_",
                        "$remote_addr",
                        "$cookie_",
                    ):
                        assert forbidden not in fmt
                    assert '"path":"$uri"' in fmt
                    assert '"timestamp":"$time_iso8601"' in fmt
                    assert "~^4 warn;" in config
                    assert "~^5 error;" in config
                    assert "access_log /dev/stdout safe_json;" in config

    def test_private_gateway_renders_declared_resource_budget(self) -> None:
        """The gateway Pod uses its chart's declared requests and limits."""
        gateway = next(
            doc for doc in self.render("private-gateway") if doc and doc.get("kind") == "DaemonSet"
        )
        container = gateway["spec"]["template"]["spec"]["containers"][0]
        assert container["resources"] == {
            "requests": {"cpu": "50m", "memory": "128Mi"},
            "limits": {"memory": "512Mi"},
        }
        # Listener remains on the node's existing address/ports.
        assert gateway["spec"]["template"]["spec"]["hostNetwork"] is True
        assert container["ports"][0]["containerPort"] == 18443

    def test_real_nginx_http_syntax(self) -> None:
        """The rendered logging directives pass real nginx syntax checks."""
        # Extract exact rendered logging directives; TLS/listen/upstream resources
        # in full gateway configs depend on deployment-only IPs and secrets.
        for chart in CHARTS:
            configs: list[str] = []
            for doc in self.render(chart):
                if not doc or doc["kind"] != "ConfigMap":
                    continue
                data = doc.get("data", {})
                assert isinstance(data, dict)
                for entry in data.values():
                    assert isinstance(entry, str)
                    if "log_format safe_json" in entry:
                        configs.append(entry)
            for config in configs:
                block_match = re.search(
                    r"map \$status.*?access_log /dev/stdout safe_json;",
                    config,
                    re.DOTALL,
                )
                assert block_match is not None
                block = block_match.group()
                candidate = (
                    "events {}\nhttp {\n" + block + "\nserver { listen 8080; return 204; }\n}\n"
                )
                result = subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "-i",
                        "--network=none",
                        "--pull=never",
                        "--entrypoint",
                        "sh",
                        (ROOT / "ci/quality/nginx-syntax-image.txt").read_text().strip(),
                        "-c",
                        "cat > /tmp/test.conf; TZ=UTC nginx -t -c /tmp/test.conf",
                    ],
                    input=candidate,
                    text=True,
                    capture_output=True,
                )
                assert result.returncode == 0, f"{chart}: nginx syntax rejected"

    def test_socrat_mount_without_homepage(self) -> None:
        """The socrat-home chart mounts access logging without the homepage."""
        output = subprocess.check_output(
            [
                "helm",
                "template",
                "test",
                str(ROOT / "charts/socrat-home"),
                "--set",
                "homepageIndex.enabled=false",
            ],
            text=True,
        )
        deployment = next(d for d in yaml.safe_load_all(output) if d and d["kind"] == "Deployment")
        pod = deployment["spec"]["template"]
        assert "checksum/access-logging" in pod["metadata"]["annotations"]
        assert pod["spec"]["volumes"][0]["name"] == "access-logging"
        assert "/etc/nginx/conf.d/00-access-logging.conf" in [
            m["mountPath"] for m in pod["spec"]["containers"][0]["volumeMounts"]
        ]
