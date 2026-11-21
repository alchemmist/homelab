"""Offline standalone SPI public entry, secret boundary, native OIDC catalog."""

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock

import yaml

ROOT = Path(__file__).resolve().parents[1]

PAGE_FETCH_COUNT = 2
STATE_FILE_MODE = 0o600
spec = importlib.util.spec_from_file_location("spi_oidc", ROOT / "scripts/spi-queue-oidc.py")
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


def render(native=True) -> dict[tuple[str, str, str], dict[str, object]]:
    raw = subprocess.check_output(
        [
            "helm",
            "template",
            "spi-triage",
            str(ROOT / "charts/spi-triage"),
            "-n",
            "automation",
            "-f",
            str(ROOT / "deploy/spi-triage/values.yaml"),
            "--set",
            "queueUI.oidc.enabled=" + str(native).lower(),
        ],
        text=True,
    )
    return {
        (
            x["kind"],
            x["metadata"].get("namespace", "automation"),
            x["metadata"]["name"],
        ): x
        for x in yaml.safe_load_all(raw)
        if x
    }


class NativeQueueChartTests(unittest.TestCase):
    def test_native_host_tls_and_no_forward_auth(self) -> None:
        docs = render()
        entry = docs["Ingress", "automation", "spi-queue-ui"]
        assert entry["spec"]["rules"][0]["host"] == "spi.socrat.alchemmist.xyz"
        assert entry["spec"]["rules"][0]["http"]["paths"][0]["path"] == "/"
        assert entry["spec"]["tls"] == [
            {"hosts": ["spi.socrat.alchemmist.xyz"], "secretName": "spi-queue-tls"}
        ]
        assert (
            entry["metadata"]["annotations"]["cert-manager.io/cluster-issuer"]
            == "letsencrypt-http01"
        )
        assert not any(k[0] == "Middleware" for k in docs)
        assert "router.middlewares" not in str(entry)

    def test_client_credential_mount_is_frontend_only_and_read_only(self) -> None:
        docs = render()
        pod = docs["Deployment", "automation", "spi-queue-ui"]["spec"]["template"]["spec"]
        assert {
            "name": "oidc-client",
            "secret": {"secretName": "spi-queue-oidc", "defaultMode": 288},
        } in pod["volumes"]
        assert {"name": "oidc-client", "mountPath": "/oidc-client", "readOnly": True} in pod[
            "containers"
        ][0]["volumeMounts"]
        assert not pod["automountServiceAccountToken"]
        for name in ("spi-triage",):
            assert "oidc-client" not in str(docs["Deployment", "automation", name])
        assert "spi-queue-oidc" not in str(docs["CronJob", "pr-agent", "spi-github-broker"])
        assert not any(k[0] == "Secret" for k in docs)

    def test_native_entry_does_not_change_backend_pvc_rbac_jobs_or_limits(self) -> None:
        old, new = render(False), render(True)
        for k in set(old) & set(new):
            if k in [
                ("Deployment", "automation", "spi-queue-ui"),
                ("Ingress", "automation", "spi-queue-ui"),
                ("NetworkPolicy", "automation", "spi-queue-ui"),
            ]:
                continue
            assert old[k] == new[k], k
        pod = lambda docs: docs["Deployment", "automation", "spi-queue-ui"]["spec"]["template"][
            "spec"
        ]
        assert pod(old)["containers"][0]["resources"] == pod(new)["containers"][0]["resources"]
        assert pod(old)["nodeSelector"] == pod(new)["nodeSelector"]

    def test_network_is_scoped_to_real_auth_hops_and_same_backend(self) -> None:
        policy = render()["NetworkPolicy", "automation", "spi-queue-ui"]
        text = str(policy["spec"]["egress"])
        assert "8443" in text
        assert "svccontroller.k3s.cattle.io/svcname" in text
        assert "spi-triage" in text
        assert "0.0.0.0/0" not in text
        assert "9000" not in text

    def test_catalog_has_exact_native_callback_groups_and_no_human_assignment(self) -> None:
        catalog = json.loads((ROOT / "deploy/identity/spi-triage-oidc.json").read_text())
        assert catalog["provider"]["redirect_uris"] == [
            {"matching_mode": "strict", "url": "https://spi.socrat.alchemmist.xyz/oauth/callback"}
        ]
        assert catalog["provider"]["sub_mode"] == "user_uuid"
        assert catalog["provider"]["client_type"] == "confidential"
        assert catalog["scopes"] == ["openid", "groups"]
        assert catalog["groups"] == [
            "homelab-owner",
            "homelab-platform-operator",
            "app-spi-triage-operator",
        ]
        assert "client_secret" not in str(catalog)
        assert "users" not in catalog

    def test_app_group_requires_explicit_nonprivileged_shape(self) -> None:
        good = {
            "is_superuser": False,
            "parents": [],
            "roles": [],
            "attributes": identity.MARKER,
        }
        identity.group_valid(good)
        for update in (
            {"parents": ["ancestor"]},
            {"roles": ["admin"]},
            {"is_superuser": True},
            {"attributes": {}},
        ):
            with self.subTest(update=update), self.assertRaises(RuntimeError):
                identity.group_valid({**good, **update})

    def test_no_unknown_provider_is_adopted_without_private_journal(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "without private client journal"):
            identity.validate_existing(None, {}, None, {"pk": 1}, None, {}, {})


class NativeAPIResponseTests(unittest.TestCase):
    def test_list_response_shape_fails_closed(self) -> None:
        for value in (
            None,
            [],
            {},
            {"results": None},
            {"results": [None]},
            {"results": [], "pagination": []},
            {"results": [], "pagination": {"next": "2"}},
            {"results": [], "pagination": {"next": 4}},
        ):
            api = object.__new__(identity.API)
            api.call = Mock(return_value=value)
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(RuntimeError, "Malformed native"),
            ):
                api.rows("core/groups/")

    def test_valid_pagination_is_bounded_and_merged(self) -> None:
        api = object.__new__(identity.API)
        api.call = Mock(
            side_effect=[
                {"results": [{"pk": 1}], "pagination": {"next": 2}},
                {"results": [{"pk": 2}], "pagination": None},
            ]
        )
        assert api.rows("core/groups/") == [{"pk": 1}, {"pk": 2}]
        assert api.call.call_count == PAGE_FETCH_COUNT

    def test_create_response_requires_object_primary_key(self) -> None:
        for value in (None, [], {}, {"pk": None}, {"pk": False}, {"pk": ""}):
            api = object.__new__(identity.API)
            api.token = "fixture"
            api.write = True
            response = Mock()
            response.read.return_value = json.dumps(value).encode()
            api.http = Mock()
            api.http.open.return_value.__enter__ = Mock(return_value=response)
            api.http.open.return_value.__exit__ = Mock(return_value=False)
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(RuntimeError, "Malformed native create"),
            ):
                api.call("POST", "core/groups/", {})

    def test_production_uses_accepted_native_oidc_activation(self) -> None:
        values = yaml.safe_load((ROOT / "deploy/spi-triage/values.yaml").read_text())
        assert values["queueUI"]["oidc"]["enabled"] is True
        assert values["queueUI"]["oidc"]["existingSecret"] == "spi-queue-oidc"


class NativeOIDCDefaultTests(unittest.TestCase):
    def test_partial_oidc_overlay_keeps_boolean_default(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            overlay = Path(directory) / "partial.yaml"
            overlay.write_text("queueUI:\n  oidc:\n    existingSecret: alternate-client\n")
            subprocess.run(
                [
                    "helm",
                    "template",
                    "spi-triage",
                    str(ROOT / "charts/spi-triage"),
                    "-f",
                    str(overlay),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )

    def test_invalid_oidc_enabled_types_are_rejected_not_defaulted(self) -> None:
        for value in ("0", "null", '"false"'):
            result = subprocess.run(
                [
                    "helm",
                    "template",
                    "spi-triage",
                    str(ROOT / "charts/spi-triage"),
                    "--set-json",
                    "queueUI.oidc.enabled=" + value,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            with self.subTest(value=value):
                assert result.returncode != 0


class NativeStatePersistenceTests(unittest.TestCase):
    def test_save_never_overwrites_existing_file_or_follows_symlink(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            victim = root / "victim.json"
            victim.write_text("original")
            link = root / "before.json"
            link.symlink_to(victim)
            for destination in (victim, link):
                with (
                    self.subTest(destination=destination.name),
                    self.assertRaises(FileExistsError),
                ):
                    identity.save(destination, {"fixture": "must not write"})
            assert victim.read_text() == "original"
            assert link.is_symlink()
            dangling = root / "after.json"
            target = root / "missing.json"
            dangling.symlink_to(target)
            with self.assertRaises(FileExistsError):
                identity.save(dangling, {"fixture": "must not create"})
            assert not target.exists()

    def test_new_state_file_is_private_and_exclusive(self) -> None:
        import stat
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            identity.save(path, {"fixture": "not a real credential"})
            assert stat.S_IMODE(path.stat().st_mode) == STATE_FILE_MODE
            assert json.loads(path.read_text()) == {"fixture": "not a real credential"}
            with self.assertRaises(FileExistsError):
                identity.save(path, {})

    def test_cli_rejects_symlink_state_directory_before_api_access(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "public"
            target.mkdir(mode=0o777)
            link = root / "state"
            link.symlink_to(target, target_is_directory=True)
            result = subprocess.run(
                [
                    "python3",
                    str(ROOT / "scripts/spi-queue-oidc.py"),
                    "--state-dir",
                    str(link),
                    "--credentials",
                    str(root / "nonexistent-credential.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result.returncode != 0
            assert "STOP: Private state directory required" in result.stderr
            assert list(target.iterdir()) == []
