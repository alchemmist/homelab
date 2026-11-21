"""Offline chart rendering and real nginx parser tests; no cluster access."""

from pathlib import Path
import re
import shutil
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHARTS = ("private-gateway", "syncthing", "img-proxy", "litellm-infra", "socrat-home")


class SafeNginxLoggingTests(unittest.TestCase):
    def render(self, chart: str) -> list[dict[str, object]]:
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

    @unittest.skipUnless(shutil.which("docker"), "docker required for nginx syntax validation")
    def test_real_nginx_http_syntax(self) -> None:
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
                    r"map \$status.*?access_log /dev/stdout safe_json;", config, re.S
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
                        "--entrypoint",
                        "sh",
                        "nginx:1.28.0-alpine",
                        "-c",
                        "cat > /tmp/test.conf; TZ=UTC nginx -t -c /tmp/test.conf",
                    ],
                    input=candidate,
                    text=True,
                    capture_output=True,
                )
                assert result.returncode == 0, f"{chart}: nginx syntax rejected"

    def test_socrat_mount_without_homepage(self) -> None:
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
        assert "/etc/nginx/conf.d/00-access-logging.conf" in [m["mountPath"] for m in pod["spec"]["containers"][0]["volumeMounts"]]
