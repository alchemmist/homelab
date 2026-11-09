"""Offline standalone SPI public entry, secret boundary, native OIDC catalog."""

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "spi_oidc", ROOT / "scripts/spi-queue-oidc.py"
)
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


def render(native=True):
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
    def test_native_host_tls_and_no_forward_auth(self):
        docs = render()
        entry = docs["Ingress", "automation", "spi-queue-ui"]
        self.assertEqual(entry["spec"]["rules"][0]["host"], "spi.socrat.alchemmist.xyz")
        self.assertEqual(entry["spec"]["rules"][0]["http"]["paths"][0]["path"], "/")
        self.assertEqual(
            entry["spec"]["tls"],
            [{"hosts": ["spi.socrat.alchemmist.xyz"], "secretName": "spi-queue-tls"}],
        )
        self.assertEqual(
            entry["metadata"]["annotations"]["cert-manager.io/cluster-issuer"],
            "letsencrypt-http01",
        )
        self.assertFalse(any(k[0] == "Middleware" for k in docs))
        self.assertNotIn("router.middlewares", str(entry))

    def test_client_credential_mount_is_frontend_only_and_read_only(self):
        docs = render()
        pod = docs["Deployment", "automation", "spi-queue-ui"]["spec"]["template"][
            "spec"
        ]
        self.assertIn(
            {
                "name": "oidc-client",
                "secret": {"secretName": "spi-queue-oidc", "defaultMode": 288},
            },
            pod["volumes"],
        )
        self.assertIn(
            {"name": "oidc-client", "mountPath": "/oidc-client", "readOnly": True},
            pod["containers"][0]["volumeMounts"],
        )
        self.assertFalse(pod["automountServiceAccountToken"])
        for name in ("spi-triage",):
            self.assertNotIn("oidc-client", str(docs["Deployment", "automation", name]))
        self.assertNotIn(
            "spi-queue-oidc", str(docs["CronJob", "pr-agent", "spi-github-broker"])
        )
        self.assertFalse(any(k[0] == "Secret" for k in docs))

    def test_native_entry_does_not_change_backend_pvc_rbac_jobs_or_limits(self):
        old, new = render(False), render(True)
        for k in set(old) & set(new):
            if k in [
                ("Deployment", "automation", "spi-queue-ui"),
                ("Ingress", "automation", "spi-queue-ui"),
                ("NetworkPolicy", "automation", "spi-queue-ui"),
            ]:
                continue
            self.assertEqual(old[k], new[k], k)
        pod = lambda docs: docs["Deployment", "automation", "spi-queue-ui"]["spec"][
            "template"
        ]["spec"]
        self.assertEqual(
            pod(old)["containers"][0]["resources"],
            pod(new)["containers"][0]["resources"],
        )
        self.assertEqual(pod(old)["nodeSelector"], pod(new)["nodeSelector"])

    def test_network_is_scoped_to_real_auth_hops_and_same_backend(self):
        policy = render()["NetworkPolicy", "automation", "spi-queue-ui"]
        text = str(policy["spec"]["egress"])
        self.assertIn("8443", text)
        self.assertIn("svccontroller.k3s.cattle.io/svcname", text)
        self.assertIn("spi-triage", text)
        self.assertNotIn("0.0.0.0/0", text)
        self.assertNotIn("9000", text)

    def test_catalog_has_exact_native_callback_groups_and_no_human_assignment(self):
        catalog = json.loads(
            (ROOT / "deploy/identity/spi-triage-oidc.json").read_text()
        )
        self.assertEqual(
            catalog["provider"]["redirect_uris"],
            [
                {
                    "matching_mode": "strict",
                    "url": "https://spi.socrat.alchemmist.xyz/oauth/callback",
                }
            ],
        )
        self.assertEqual(catalog["provider"]["sub_mode"], "user_uuid")
        self.assertEqual(catalog["provider"]["client_type"], "confidential")
        self.assertEqual(catalog["scopes"], ["openid", "groups"])
        self.assertEqual(
            catalog["groups"],
            ["homelab-owner", "homelab-platform-operator", "app-spi-triage-operator"],
        )
        self.assertNotIn("client_secret", str(catalog))
        self.assertNotIn("users", catalog)

    def test_app_group_requires_explicit_nonprivileged_shape(self):
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

    def test_no_unknown_provider_is_adopted_without_private_journal(self):
        with self.assertRaisesRegex(RuntimeError, "without private client journal"):
            identity.validate_existing(None, {}, None, {"pk": 1}, None, {}, {})


class NativeAPIResponseTests(unittest.TestCase):
    def test_list_response_shape_fails_closed(self):
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

    def test_valid_pagination_is_bounded_and_merged(self):
        api = object.__new__(identity.API)
        api.call = Mock(
            side_effect=[
                {"results": [{"pk": 1}], "pagination": {"next": 2}},
                {"results": [{"pk": 2}], "pagination": None},
            ]
        )
        self.assertEqual(api.rows("core/groups/"), [{"pk": 1}, {"pk": 2}])
        self.assertEqual(api.call.call_count, 2)

    def test_create_response_requires_object_primary_key(self):
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

    def test_production_native_activation_stays_disabled_until_release(self):
        values = yaml.safe_load((ROOT / "deploy/spi-triage/values.yaml").read_text())
        self.assertIs(values["queueUI"]["oidc"]["enabled"], False)
