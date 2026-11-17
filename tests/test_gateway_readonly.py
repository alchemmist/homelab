"""Read-only gateway admission rejects owner, transport and authorization drift."""

import base64
import copy
import importlib.util
import io
import json
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import NotRequired, Protocol, TypedDict
from unittest.mock import patch

import pytest


class _SecretReference(TypedDict):
    """Reference to a resource and its data key, not a credential value."""

    name: str
    key: str


class _EnvironmentSource(TypedDict):
    """Existing Kubernetes Secret reference consumed by the deployment."""

    secretKeyRef: _SecretReference


class _EnvironmentEntry(TypedDict):
    """Master-key environment reference, removable to test refusal before reads."""

    name: str
    valueFrom: _EnvironmentSource


class _Container(TypedDict):
    """The fixture only needs the deployment's existing environment references."""

    env: list[_EnvironmentEntry]


class _TemplateSpec(TypedDict):
    """Pod-template containers read without modifying the owning deployment."""

    containers: list[_Container]


class _Template(TypedDict):
    """Existing deployment template used for read-only master-reference discovery."""

    spec: _TemplateSpec


class _ClusterSpec(TypedDict):
    """Optional fields distinguish Application, Deployment and Service fixtures."""

    destination: NotRequired[dict[str, str]]
    sources: NotRequired[list[dict[str, str]]]
    template: NotRequired[_Template]
    clusterIP: NotRequired[str]


class _Metadata(TypedDict):
    """Helm chart label supplies the independently checked version identity."""

    labels: dict[str, str]


class _ClusterObject(TypedDict):
    """Read-only fixture document; each resource kind supplies its relevant fields."""

    spec: NotRequired[_ClusterSpec]
    metadata: NotRequired[_Metadata]
    data: NotRequired[dict[str, str]]


ROOT = Path(__file__).resolve().parents[1]
MISSING_AUTHORIZATION_STATUS = 401
spec = importlib.util.spec_from_file_location(
    "gateway", ROOT / "ansible/roles/monitoring_llm_gateway/files/configure_gateway.py"
)
assert spec is not None
assert spec.loader is not None
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


class Response(io.BytesIO):
    """Represent a local JSON HTTP response without opening a socket."""

    def __init__(self, status: int, body: object = None) -> None:
        """Encode a local JSON payload and retain its simulated HTTP status."""
        super().__init__(json.dumps(body).encode())
        self.status = status


class _Runner(Protocol):
    """Accept the same command and optional arguments as the injected transport."""

    def __call__(self, command: list[str], **kwargs: object) -> SimpleNamespace:
        """Return a simulated process result without executing its command."""
        ...


class _Opener(Protocol):
    """Accept a real Request but respond entirely in memory."""

    def __call__(self, request: urllib.request.Request, **kwargs: object) -> Response:
        """Return an in-memory response without opening a network connection."""
        ...


def _fail_on_read(commands: list[list[str]], fail_at: int, runner: _Runner) -> _Runner:
    """Bind the fault point and command log before a callback outlives its loop turn."""

    def failed(command: list[str], **kwargs: object) -> SimpleNamespace:
        if len(commands) + 1 == fail_at:
            commands.append(command)
            return SimpleNamespace(returncode=1, stdout="")
        return runner(command, **kwargs)

    return failed


def _override_status(path: str, status: int, opener: _Opener) -> _Opener:
    """Bind one endpoint fault without capturing the mutable outer loop variables."""

    def bad(request: urllib.request.Request, **kwargs: object) -> Response:
        if urllib.parse.urlsplit(request.full_url).path == path:
            return Response(status, {})
        return opener(request, **kwargs)

    return bad


class GatewayReadonly(unittest.TestCase):
    """Reject unauthorized reads without repair, fallback or credential disclosure."""

    def fixture(
        self,
    ) -> tuple[
        SimpleNamespace,
        dict[tuple[str, str], _ClusterObject],
        list[list[str]],
        list[urllib.request.Request],
        _Runner,
        _Opener,
    ]:
        """Build mocked cluster and HTTP reads with independently observable effects."""
        args = SimpleNamespace(
            namespace="llm",
            release="litellm",
            chart_version="1.105.1",
            kubeconfig="/fixture/config",
            secret="litellm-monitoring",
        )

        def b64(value: str) -> str:
            return base64.b64encode(value.encode()).decode()

        objects: dict[tuple[str, str], _ClusterObject] = {
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
        commands: list[list[str]] = []
        requests: list[urllib.request.Request] = []

        def runner(command: list[str], **_kwargs: object) -> SimpleNamespace:
            commands.append(command)
            assert "get" in command
            assert "helm" not in command
            i = command.index("get")
            key = (command[i + 1], command[i + 2])
            return SimpleNamespace(returncode=0, stdout=json.dumps(objects[key]))

        def opener(request: urllib.request.Request, **_kwargs: object) -> Response:
            requests.append(request)
            assert request.get_method() == "GET"
            path = urllib.parse.urlsplit(request.full_url).path
            if path == "/key/info":
                return Response(200, {"info": {"allowed_routes": ["/metrics"]}})
            if path == "/metrics":
                return Response(
                    200 if request.get_header("Authorization") else MISSING_AUTHORIZATION_STATUS
                )
            if path == "/v1/models":
                return Response(403)
            message = "Unexpected API path"
            raise AssertionError(message)

        return args, objects, commands, requests, runner, opener

    def test_deferred_read_fault_callbacks_retain_their_own_logs_and_fault_points(self) -> None:
        """Callbacks invoked after loop completion must not share the last fixture."""
        callbacks: list[tuple[list[list[str]], int, _Runner]] = []
        for fail_at in (1, 2):
            _args, _objects, commands, _requests, runner, _opener = self.fixture()
            callbacks.append((commands, fail_at, _fail_on_read(commands, fail_at, runner)))
        command = ["kubectl", "get", "application", "litellm"]
        for commands, fail_at, callback in callbacks:
            for _read in range(1, fail_at):
                assert callback(command).returncode == 0
            assert callback(command).returncode == 1
            assert len(commands) == fail_at
        assert callbacks[0][0] is not callbacks[1][0]

    def test_deferred_http_fault_callbacks_retain_their_own_endpoint_and_status(self) -> None:
        """Deferred endpoint faults preserve both earlier overrides and the fallback."""
        _args, _objects, _commands, _requests, _runner, opener = self.fixture()
        faults = (("/key/info", 302), ("/v1/models", 200))
        callbacks = [_override_status(path, status, opener) for path, status in faults]
        for (path, status), callback in zip(faults, callbacks, strict=True):
            request = urllib.request.Request("http://fixture" + path)
            assert callback(request).status == status
            fallback = urllib.request.Request("http://fixture/metrics")
            assert callback(fallback).status == MISSING_AUTHORIZATION_STATUS

    def test_success_only_reads_and_preserves_existing_restricted_key(self) -> None:
        """Verify success only reads and preserves existing restricted key."""
        args, objects, commands, requests, runner, opener = self.fixture()
        before = copy.deepcopy(objects)
        assert not g.verify(args, runner, opener)
        cluster_reads = 5
        api_reads = 4
        assert len(commands) == cluster_reads
        assert len(requests) == api_reads
        assert before == objects

    def test_every_failed_cluster_read_stops_without_fallback(self) -> None:
        """Verify every failed cluster read stops without fallback."""
        for fail_at in range(1, 6):
            with self.subTest(fail_at=fail_at):
                args, _objects, commands, requests, runner, opener = self.fixture()

                failed = _fail_on_read(commands, fail_at, runner)

                with pytest.raises(RuntimeError):
                    g.verify(args, failed, opener)
                assert len(commands) == fail_at
                assert requests == []

    def test_absent_or_changed_owner_fails_before_credential_reads(self) -> None:
        """Verify absent or changed owner fails before credential reads."""
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
            with pytest.raises(RuntimeError):
                g.verify(args, runner, opener)
            assert len(commands) == 1
            assert requests == []

    def test_no_master_reference_or_chart_drift_fails_closed(self) -> None:
        """Verify no master reference or chart drift fails closed."""
        for change in ["reference", "chart"]:
            args, objects, commands, requests, runner, opener = self.fixture()
            d = objects["deployment", "litellm"]
            if change == "chart":
                d["metadata"]["labels"]["helm.sh/chart"] = "unreviewed"
            else:
                d["spec"]["template"]["spec"]["containers"][0]["env"] = []
            with pytest.raises(RuntimeError):
                g.verify(args, runner, opener)
            reads_before_credentials = 2
            assert len(commands) == reads_before_credentials
            assert requests == []

    def test_api_acl_or_redirect_mismatch_never_triggers_repair(self) -> None:
        """Verify api acl or redirect mismatch never triggers repair."""
        for path, status in [("/key/info", 302), ("/metrics", 200), ("/v1/models", 200)]:
            with self.subTest(path=path):
                args, _objects, commands, _requests, runner, opener = self.fixture()

                bad = _override_status(path, status, opener)

                with pytest.raises(RuntimeError):
                    g.verify(args, runner, bad)
                cluster_reads = 5
                assert len(commands) == cluster_reads

    def test_broader_key_is_rejected_not_repaired(self) -> None:
        """Verify broader key is rejected not repaired."""
        args, _objects, commands, _requests, runner, _opener = self.fixture()

        def bad(_req: urllib.request.Request, **_kwargs: object) -> Response:
            return Response(200, {"info": {"allowed_routes": ["/metrics", "/v1/models"]}})

        with pytest.raises(RuntimeError):
            g.verify(args, runner, bad)
        cluster_reads = 5
        assert len(commands) == cluster_reads

    def test_authorization_redirects_are_not_followed(self) -> None:
        """Verify authorization redirects are not followed."""
        assert (
            g.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "http://other/")
            is None
        )

    def test_public_or_loopback_service_address_never_receives_credentials(self) -> None:
        """Verify public or loopback service address never receives credentials."""
        for address in ["127.0.0.1", "0.0.0.0", "8.8.8.8"]:
            with self.subTest(address=address):
                args, objects, commands, requests, runner, opener = self.fixture()
                objects["service", "litellm"]["spec"]["clusterIP"] = address
                with pytest.raises(RuntimeError):
                    g.verify(args, runner, opener)
                reads_before_credentials = 3
                assert len(commands) == reads_before_credentials
                assert requests == []

    def test_cli_does_not_echo_credential_bearing_failures(self) -> None:
        """Verify cli does not echo credential bearing failures."""
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
            pytest.raises(SystemExit) as error,
        ):
            g.main()
        assert "private-fixture" not in str(error.value)
        assert "http://" not in str(error.value)


if __name__ == "__main__":
    unittest.main()
