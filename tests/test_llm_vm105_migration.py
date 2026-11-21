"""Contracts for the owner-approved four-app handoff; legacy volumes stay intact."""

from collections.abc import Iterable
from pathlib import Path
import subprocess
import unittest
from typing import Literal, Protocol, overload
import yaml

ROOT = Path(__file__).resolve().parents[1]


class _Name(Protocol):
    def __getitem__(self, key: Literal["name"], /) -> str: ...


class _Manifest(Protocol):
    @overload
    def __getitem__(self, key: Literal["kind"], /) -> str: ...
    @overload
    def __getitem__(self, key: Literal["metadata"], /) -> _Name: ...
    @overload
    def __getitem__(self, key: str, /) -> object: ...


def render(name: str, *args: str):
    return list(
        yaml.safe_load_all(
            subprocess.check_output(
                [
                    "helm",
                    "template",
                    name,
                    str(ROOT / "charts" / name),
                    "--namespace",
                    "llm" if name != "umami" else "umami",
                    *args,
                ],
                text=True,
            )
        )
    )


def obj(docs: Iterable[_Manifest | None], kind: str, name: str):
    return next(d for d in docs if d and d["kind"] == kind and d["metadata"]["name"] == name)


class FourAppMigrationTests(unittest.TestCase):
    def test_stateless_placement_does_not_move_umami_database(self):
        for name in ["umami", "searxng"]:
            d = render(name)
            self.assertEqual(
                obj(d, "Deployment", name)["spec"]["template"]["spec"]["nodeSelector"],
                {"kubernetes.io/hostname": "socrat-5"},
            )
        db = obj(render("umami"), "Deployment", "umami-db")["spec"]["template"]["spec"]
        self.assertEqual(db["nodeSelector"], {"kubernetes.io/hostname": "socrat-0"})
        self.assertEqual(db["volumes"][0]["hostPath"]["path"], "/srv/umami/postgres")

    def test_dedicated_retained_vm_storage_and_original_claims(self):
        for name in ["open-webui", "open-terminal"]:
            with self.subTest(app=name):
                docs = render(name)
                old = obj(docs, "PersistentVolumeClaim", name + "-data")
                self.assertEqual(old["spec"]["storageClassName"], "local-path")
                self.assertEqual(old["metadata"]["annotations"]["helm.sh/resource-policy"], "keep")
                pv = obj(docs, "PersistentVolume", name + "-socrat5")
                self.assertEqual(pv["spec"]["persistentVolumeReclaimPolicy"], "Retain")
                self.assertEqual(
                    pv["spec"]["local"]["path"], "/mnt/files/homelab/" + name + "/data"
                )
                self.assertEqual(
                    pv["spec"]["nodeAffinity"]["required"]["nodeSelectorTerms"][0][
                        "matchExpressions"
                    ][0]["values"],
                    ["socrat-5"],
                )
                claim = obj(docs, "PersistentVolumeClaim", name + "-socrat5")
                self.assertEqual(claim["spec"]["volumeName"], name + "-socrat5")
                self.assertEqual(claim["spec"]["storageClassName"], "")

    def test_activation_requires_verified_existing_data_and_single_writer(self):
        for name, field in [
            ("open-webui", "persistence.claimName"),
            ("open-terminal", "claimName"),
        ]:
            with self.subTest(app=name):
                d = obj(
                    render(
                        name, "--set", field + "=" + name + "-socrat5", "--set", "nodeName=socrat-5"
                    ),
                    "Deployment",
                    name,
                )
                self.assertIn(d["spec"]["replicas"], [0, 1])
                self.assertEqual(d["spec"]["strategy"]["type"], "Recreate")
                s = d["spec"]["template"]["spec"]
                self.assertEqual(s["nodeSelector"], {"kubernetes.io/hostname": "socrat-5"})
                init = next(
                    c for c in s["initContainers"] if c["name"] == "require-verified-migration"
                )
                self.assertIn(".homelab-vm105-migration-verified.json", init["args"][0])
                compile(init["args"][0], "<migration-guard>", "exec")
                self.assertTrue(init["volumeMounts"][0]["readOnly"])
                self.assertFalse(s["automountServiceAccountToken"])

    def test_private_gateway_address_and_node_stay_together(self):
        docs = render("open-webui", "--set", "nodeName=socrat-5")
        s = obj(docs, "Deployment", "open-webui-gateway")["spec"]["template"]["spec"]
        self.assertEqual(s["nodeSelector"], {"kubernetes.io/hostname": "socrat-0"})
        cm = obj(docs, "ConfigMap", "open-webui-gateway")["data"]["default.conf"]
        self.assertIn("listen 10.250.0.1:18080", cm)
        self.assertIn("return 308 https://$host$request_uri;", cm)

    def test_terminal_is_still_internal_and_webui_only(self):
        docs = render("open-terminal")
        self.assertFalse(any(d and d["kind"] == "Ingress" for d in docs))
        policy = obj(docs, "NetworkPolicy", "open-terminal-isolation")["spec"]
        self.assertEqual(
            policy["ingress"][0]["from"], [{"podSelector": {"matchLabels": {"app": "open-webui"}}}]
        )
        self.assertEqual(obj(docs, "Service", "open-terminal")["spec"]["type"], "ClusterIP")

    def test_idp_internal_tls_route_is_scoped_to_webui_pod(self):
        docs = render("open-webui")
        spec = obj(docs, "Deployment", "open-webui")["spec"]["template"]["spec"]
        self.assertEqual(
            spec["hostAliases"],
            [{"ip": "10.43.218.222", "hostnames": ["auth.socrat.alchemmist.xyz"]}],
        )
        self.assertNotIn(
            "hostAliases", obj(docs, "Deployment", "open-webui-gateway")["spec"]["template"]["spec"]
        )
        env = {e["name"]: e for e in spec["containers"][0]["env"]}
        self.assertEqual(env["WEBUI_AUTH"]["value"], "True")
        self.assertEqual(env["WEBUI_AUTH_COOKIE_SECURE"]["value"], "True")
        self.assertNotIn("NODE_TLS_REJECT_UNAUTHORIZED", env)
