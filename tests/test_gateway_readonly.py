import base64
import copy
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "gateway", ROOT / "ansible/roles/monitoring_llm_gateway/files/configure_gateway.py"
)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


class Response(io.BytesIO):
    def __init__(self, status, body=None):
        super().__init__(json.dumps(body).encode())
        self.status = status


class GatewayReadonly(unittest.TestCase):
    def fixture(self):
        args = SimpleNamespace(
            namespace="llm",
            release="litellm",
            chart_version="1.105.1",
            kubeconfig="/fixture/config",
            secret="litellm-monitoring",
        )
        b64 = lambda value: base64.b64encode(value.encode()).decode()
        objects = {
            ("application", "litellm"): {
                "spec": {
                    "destination": {"namespace": "llm", "server": "https://kubernetes.default.svc"},
                    "sources": [
                        {
                            "repoURL": "https://github.com/alchemmist/homelab.git",
                            "path": "charts/litellm",
                        }
                    ],
                }
            },
            ("deployment", "litellm"): {
                "metadata": {"labels": {"helm.sh/chart": "litellm-helm-1.105.1"}},
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "env": [
                                        {
                                            "name": "PROXY_MASTER_KEY",
                                            "valueFrom": {
                                                "secretKeyRef": {
                                                    "name": "current-master",
                                                    "key": "master",
                                                }
                                            },
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                },
            },
            ("service", "litellm"): {"spec": {"clusterIP": "10.43.1.2"}},
            ("secret", "litellm-monitoring"): {"data": {"api-key": b64("fixture-metrics")}},
            ("secret", "current-master"): {"data": {"master": b64("fixture-master")}},
        }
        commands, requests = [], []

        def runner(command, **kwargs):
            commands.append(command)
            self.assertIn("get", command)
            self.assertNotIn("helm", command)
            i = command.index("get")
            key = tuple(command[i + 1 : i + 3])
            return SimpleNamespace(returncode=0, stdout=json.dumps(objects[key]))

        def opener(request, **kwargs):
            requests.append(request)
            self.assertEqual(request.get_method(), "GET")
            path = urllib.parse.urlsplit(request.full_url).path
            if path == "/key/info":
                return Response(200, {"info": {"allowed_routes": ["/metrics"]}})
            if path == "/metrics":
                return Response(200 if request.get_header("Authorization") else 401)
            if path == "/v1/models":
                return Response(403)
            self.fail("Unexpected API path")

        return args, objects, commands, requests, runner, opener

    def test_success_only_reads_and_preserves_existing_restricted_key(self):
        args, objects, commands, requests, runner, opener = self.fixture()
        before = copy.deepcopy(objects)
        self.assertFalse(g.verify(args, runner, opener))
        self.assertEqual(len(commands), 5)
        self.assertEqual(len(requests), 4)
        self.assertEqual(before, objects)

    def test_every_failed_cluster_read_stops_without_fallback(self):
        for fail_at in range(1, 6):
            with self.subTest(fail_at=fail_at):
                args, objects, commands, requests, runner, opener = self.fixture()

                def failed(command, **kwargs):
                    if len(commands) + 1 == fail_at:
                        commands.append(command)
                        return SimpleNamespace(returncode=1, stdout="")
                    return runner(command, **kwargs)

                with self.assertRaises(RuntimeError):
                    g.verify(args, failed, opener)
                self.assertEqual(len(commands), fail_at)
                self.assertEqual(requests, [])

    def test_absent_or_changed_owner_fails_before_credential_reads(self):
        for change in ["empty", "wrong-source", "wrong-destination", "wrong-cluster"]:
            args, objects, commands, requests, runner, opener = self.fixture()
            app = objects["application", "litellm"]
            if change == "empty":
                app["spec"]["sources"] = []
            elif change == "wrong-source":
                app["spec"]["sources"][0]["path"] = "other"
            elif change == "wrong-destination":
                app["spec"]["destination"]["namespace"] = "other"
            else:
                app["spec"]["destination"]["server"] = "https://other.example"
            with self.assertRaises(RuntimeError):
                g.verify(args, runner, opener)
            self.assertEqual(len(commands), 1)
            self.assertEqual(requests, [])

    def test_no_master_reference_or_chart_drift_fails_closed(self):
        for change in ["reference", "chart"]:
            args, objects, commands, requests, runner, opener = self.fixture()
            d = objects["deployment", "litellm"]
            if change == "chart":
                d["metadata"]["labels"]["helm.sh/chart"] = "unreviewed"
            else:
                d["spec"]["template"]["spec"]["containers"][0]["env"] = []
            with self.assertRaises(RuntimeError):
                g.verify(args, runner, opener)
            self.assertEqual(len(commands), 2)
            self.assertEqual(requests, [])

    def test_api_acl_or_redirect_mismatch_never_triggers_repair(self):
        for path, status in [("/key/info", 302), ("/metrics", 200), ("/v1/models", 200)]:
            with self.subTest(path=path):
                args, objects, commands, requests, runner, opener = self.fixture()

                def bad(req, **kwargs):
                    if urllib.parse.urlsplit(req.full_url).path == path:
                        return Response(status, {})
                    return opener(req, **kwargs)

                with self.assertRaises(RuntimeError):
                    g.verify(args, runner, bad)
                self.assertEqual(len(commands), 5)

    def test_broader_key_is_rejected_not_repaired(self):
        args, objects, commands, requests, runner, opener = self.fixture()

        def bad(req, **kwargs):
            return Response(200, {"info": {"allowed_routes": ["/metrics", "/v1/models"]}})

        with self.assertRaises(RuntimeError):
            g.verify(args, runner, bad)
        self.assertEqual(len(commands), 5)

    def test_authorization_redirects_are_not_followed(self):
        self.assertIsNone(
            g.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "http://other/")
        )

    def test_public_or_loopback_service_address_never_receives_credentials(self):
        for address in ["127.0.0.1", "0.0.0.0", "8.8.8.8"]:
            with self.subTest(address=address):
                args, objects, commands, requests, runner, opener = self.fixture()
                objects["service", "litellm"]["spec"]["clusterIP"] = address
                with self.assertRaises(RuntimeError):
                    g.verify(args, runner, opener)
                self.assertEqual(len(commands), 3)
                self.assertEqual(requests, [])

    def test_cli_does_not_echo_credential_bearing_failures(self):
        argv = [
            "gateway",
            "--namespace",
            "llm",
            "--release",
            "litellm",
            "--chart-version",
            "1.105.1",
            "--kubeconfig",
            "/fixture/config",
            "--secret",
            "litellm-monitoring",
        ]
        with (
            patch("sys.argv", argv),
            patch.object(
                g, "verify", side_effect=RuntimeError("http://fixture/key/info?key=private-fixture")
            ),
        ):
            with self.assertRaises(SystemExit) as error:
                g.main()
        self.assertNotIn("private-fixture", str(error.exception))
        self.assertNotIn("http://", str(error.exception))


if __name__ == "__main__":
    unittest.main()
