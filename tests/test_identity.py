"""Tests for the identity management helper script."""

import contextlib
import hashlib
import io
import json
import runpy
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from typing import cast
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ansible/roles/authentik/files"))
import pytest
from app_iam import admission_groups


class FakeAuthentik:
    """Callable in-memory double for the authentik REST API."""

    def __init__(self) -> None:
        """Seed the committed authentik bootstrap state."""
        self.data: dict[str, list[dict[str, object]]] = {
            "core/groups/": [],
            "core/users/": [],
            "providers/oauth2/": [],
            "core/applications/": [],
            "policies/bindings/": [],
            "providers/proxy/": [],
            "outposts/instances/": [
                {
                    "pk": "embedded",
                    "managed": "goauthentik.io/outposts/embedded",
                    "config": {},
                    "providers": [],
                }
            ],
            "stages/authenticator/validate/": [
                {"pk": "validate", "name": "default-authentication-mfa-validation"}
            ],
            "stages/authenticator/totp/": [
                {"pk": "totp", "name": "default-authenticator-totp-setup"}
            ],
            "flows/instances/": cast(
                "list[dict[str, object]]",
                [
                    {"pk": s, "slug": s}
                    for s in [
                        "default-authentication-flow",
                        "default-provider-authorization-explicit-consent",
                        "default-provider-invalidation-flow",
                        "default-provider-authorization-implicit-consent",
                    ]
                ],
            ),
            "crypto/certificatekeypairs/": [
                {"pk": "cert", "name": "authentik Self-signed Certificate"}
            ],
            "propertymappings/provider/scope/": cast(
                "list[dict[str, object]]",
                [
                    {
                        "pk": s,
                        "scope_name": s,
                        "name": "authentik default OAuth Mapping: OpenID '" + s + "'",
                    }
                    for s in ["openid", "profile", "email", "offline_access"]
                ],
            ),
        }
        self.requests: list[tuple[str, str, object | None, dict[str, list[str]]]] = []

    def __call__(self, req: urllib.request.Request, timeout: int = 60) -> io.BytesIO:
        """Answer one authentik API call from the in-memory state."""
        uri = urlparse(req.full_url)
        path = uri.path.split("/api/v3/")[1]
        method = req.get_method()
        raw = cast("str | bytes", req.data) if req.data else None
        payload = json.loads(raw) if raw else None
        self.requests.append((method, path, payload, parse_qs(uri.query)))
        if method == "GET":
            rows = self.data[path]
            for k, vs in parse_qs(uri.query).items():
                if k in ["name", "username", "slug", "target"]:
                    rows = [r for r in rows if str(r.get(k)) == vs[0]]
            return io.BytesIO(json.dumps({"results": rows}).encode())
        if path.endswith("/set_password/"):
            return io.BytesIO(b"{}")
        if method == "POST":
            row: dict[str, object] = {
                "pk": len(self.data[path]) + 1,
                **cast("dict[str, object]", payload),
            }
            if path == "core/groups/":
                # Current 2026.8.6 GroupSerializer defaults, including M2M parents.
                row = {
                    "attributes": {},
                    "is_superuser": False,
                    "parents": [],
                    "roles": [],
                    "users": [],
                    **row,
                }
                row["pk"] = "group-" + str(row["pk"])
            if path == "core/users/":
                known = json.loads((ROOT / "deploy/identity/account-mappings.json").read_text())
                row["uuid"] = known.get(row["username"], {}).get("idpUserUuid", "test-new-subject")
                row["is_superuser"] = False
                for g in self.data["core/groups/"]:
                    if g["pk"] in payload.get("groups", []):
                        cast("list[object]", g["users"]).append(row["pk"])
            self.data[path].append(row)
        else:
            parent, pk, _ = path.rsplit("/", 2)
            parent += "/"
            row = next(
                r
                for r in self.data[parent]
                if str(r["slug"] if parent == "core/applications/" else r["pk"]) == pk
            )
            row.update(cast("dict[str, object]", payload))
        return io.BytesIO(json.dumps(row).encode())


class IdentityTests(unittest.TestCase):
    """Run the identity configure script against a fake Authentik."""

    def configure(self, root: Path, api: FakeAuthentik) -> None:
        """Run the authentik configure script against the fake API."""
        with (
            patch("sys.argv", ["configure.py", str(root)]),
            patch("urllib.request.urlopen", api),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            runpy.run_path(
                str(ROOT / "ansible/roles/authentik/files/configure.py"),
                run_name="__main__",
            )

    def setup_root(self, root: Path) -> None:
        """Stage the identity input files for a configuration run."""
        (root / "credentials.json").write_text(
            json.dumps({"AUTHENTIK_BOOTSTRAP_TOKEN": "fake-test-token"})
        )
        (root / "services.json").write_text((ROOT / "deploy/identity/services.json").read_text())
        (root / "observer-profile.json").write_bytes(
            (ROOT / "deploy/identity/observer/profile.json").read_bytes()
        )
        # Most foundation tests represent the post-bootstrap steady state.
        receipt = root / "observer-ready.json"
        receipt.write_text(
            json.dumps(
                {
                    "version": 1,
                    "nativeObserverReady": True,
                    "policy_sha256": hashlib.sha256(
                        (root / "observer-profile.json").read_bytes()
                    ).hexdigest(),
                }
            )
        )
        receipt.chmod(0o600)

    def setup_reviewed(self, root: Path, api: FakeAuthentik) -> None:
        """Add the restored reviewed user on top of a configured root."""
        # Restored current identities, not speculative/future users.
        self.configure(root, api)
        accounts = json.loads((ROOT / "deploy/identity/account-mappings.json").read_text())
        observer = next(g for g in api.data["core/groups/"] if g["name"] == "homelab-observer")
        api.data["core/users/"].append(
            {
                "pk": 6,
                "uuid": accounts["antropophag"]["idpUserUuid"],
                "username": "antropophag",
                "email": accounts["antropophag"]["email"],
                "is_active": True,
                "is_superuser": False,
                "groups": [observer["pk"]],
            }
        )
        cast("list[object]", observer["users"]).append(6)
        (root / "antropophag-login.json").write_text(json.dumps({"initialized": True}))
        (root / "antropophag-login.json").chmod(0o600)
        (root / "account-mappings.json").write_text(json.dumps(accounts))

    def test_harbor_observer_stays_gated_even_with_native_readiness_receipt(
        self,
    ) -> None:
        """Keep the harbor observer gated behind the readiness receipt."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.setup_root(root)
            api = FakeAuthentik()
            (root / "observer-ready.json").unlink()
            self.configure(root, api)
            observer = next(g for g in api.data["core/groups/"] if g["name"] == "homelab-observer")
            harbor = next(a for a in api.data["core/applications/"] if a["slug"] == "harbor")
            assert not any(
                b["target"] == harbor["pk"] and b["group"] == observer["pk"]
                for b in api.data["policies/bindings/"]
            )
            receipt = root / "observer-ready.json"
            receipt.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "nativeObserverReady": True,
                        "policy_sha256": hashlib.sha256(
                            (root / "observer-profile.json").read_bytes()
                        ).hexdigest(),
                    }
                )
            )
            receipt.chmod(0o600)
            self.configure(root, api)
            assert (
                sum(
                    b["target"] == harbor["pk"] and b["group"] == observer["pk"]
                    for b in api.data["policies/bindings/"]
                )
                == 0
            )

    def test_configuration_idempotent_and_mfa_required(self) -> None:
        """Replay idempotently while keeping MFA required."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.setup_root(root)
            api = FakeAuthentik()
            self.configure(root, api)
            clients = (root / "oidc-clients.json").read_bytes()
            owner = (root / "owner-login.json").read_bytes()
            self.configure(root, api)
            assert (root / "oidc-clients.json").read_bytes() == clients
            assert (root / "owner-login.json").read_bytes() == owner
            assert len(api.data["core/users/"]) == 1
            assert api.data["core/users/"][0]["username"] == "alchemmist"
            privileged = [g["name"] for g in api.data["core/groups/"] if g["is_superuser"]]
            assert privileged == ["homelab-owner"]
            assert (
                api.data["stages/authenticator/validate/"][0]["not_configured_action"]
                == "configure"
            )
            for provider in api.data["providers/oauth2/"]:
                assert provider["grant_types"] == ["authorization_code", "refresh_token"]
            grafana = next(
                p for p in api.data["providers/oauth2/"] if p["name"] == "homelab-grafana"
            )
            assert "offline_access" in cast("list[str]", grafana["property_mappings"])
            assert len(api.data["core/applications/"]) == 6
            assert len(api.data["policies/bindings/"]) == sum(
                len(admission_groups(slug, service))
                for slug, service in json.loads((root / "services.json").read_text()).items()
                if slug != "litellm" and not service.get("managedBy")
            )
            for method, path, _body, query in api.requests:
                if method == "GET" and path == "core/applications/":
                    assert query["superuser_full_list"] == ["true"]
            assert (root / "owner-login.json").stat().st_mode & 511 == 384
            assert (root / "oidc-clients.json").stat().st_mode & 511 == 384

    def test_scoped_monori_replay_preserves_secret_and_requires_owner_binding(
        self,
    ) -> None:
        """Do not attach a provider until the owner restriction exists."""
        sys.path.insert(0, str(ROOT / "ansible/roles/identity_integrations/files"))
        from monori_oidc import configure_monori

        fake = FakeAuthentik()
        fake.data["core/groups/"].append({"name": "homelab-owner", "pk": "owner"})

        def api(method, path, payload=None):
            req = urllib.request.Request(
                "https://id.example/api/v3/" + path,
                method=method,
                data=json.dumps(payload).encode() if payload else None,
            )
            return json.load(fake(req))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "monori-services.json").write_bytes(
                (ROOT / "deploy/identity/services.json").read_bytes()
            )
            (root / "monori-account-mappings.json").write_text(
                json.dumps({"antropophag": {"idpUserUuid": "reviewed"}})
            )
            fake.data["core/users/"].append(
                {
                    "pk": 7,
                    "username": "antropophag",
                    "uuid": "reviewed",
                    "is_active": True,
                }
            )

            def malformed(method, path, payload=None):
                if path.startswith("providers/oauth2/?"):
                    return {"results": ["invalid row"]}
                return api(method, path, payload)

            with pytest.raises(RuntimeError, match="Malformed identity lookup"):
                configure_monori(root, malformed)
            assert not (root / "monori-client-secret").exists()

            def interrupted(method, path, payload=None):
                if method == "PATCH" and path == "core/applications/monori/":
                    msg = "simulated interruption"
                    raise RuntimeError(msg)
                return api(method, path, payload)

            with pytest.raises(RuntimeError, match="simulated interruption"):
                configure_monori(root, interrupted)
            sent = [
                body
                for method, path, body, _ in fake.requests
                if (method, path) == ("POST", "providers/oauth2/")
            ]
            assert len(sent) == 1
            assert sent[0]["redirect_uris"] == [
                {
                    "matching_mode": "strict",
                    "url": "https://monori.alchemmist.xyz/oidc/callback",
                    "redirect_uri_type": "authorization",
                }
            ]
            secret_path = root / "monori-client-secret"
            secret = secret_path.read_text()
            assert secret_path.stat().st_mode & 511 == 384
            assert fake.data["providers/oauth2/"][0]["client_secret"] == secret
            assert configure_monori(root, api) == secret
            assert configure_monori(root, api) == secret
            writes = [(method, path) for method, path, _, _ in fake.requests if method != "GET"]
            assert writes == [
                ("POST", "core/applications/"),
                ("POST", "policies/bindings/"),
                ("POST", "policies/bindings/"),
                ("POST", "providers/oauth2/"),
                ("PATCH", "core/applications/monori/"),
            ]
            secret_path.write_text("x" * 64)
            with pytest.raises(RuntimeError, match="Cannot verify retained Monori secret"):
                configure_monori(root, api)
            secret_path.write_text(secret)
            fake.data["policies/bindings/"][0]["group"] = "other"
            with pytest.raises(RuntimeError, match="binding drift"):
                configure_monori(root, api)
            (root / "monori-client-secret").unlink()
            with pytest.raises(RuntimeError, match="Restore retained credentials"):
                configure_monori(root, api)

    def test_scoped_monori_secret_apply_needs_no_shared_registry(self) -> None:
        """Exercise the entrypoint in an empty directory, without cluster access."""
        import subprocess

        scripts = ROOT / "ansible/roles/identity_integrations/files"
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules):
            with (
                patch.object(sys, "path", [str(scripts), *sys.path]),
                patch("monori_oidc.configure_monori", return_value="test-value"),
                patch.object(sys, "argv", ["integrate.py", directory, "monori"]),
                patch(
                    "subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0, stdout=""),
                ) as command,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                runpy.run_path(str(scripts / "integrate.py"), run_name="__main__")
            args, kwargs = command.call_args
            assert "--server-side" in args[0]
            assert "--field-manager=monori-oidc" in args[0]
            assert "--force-conflicts" not in args[0]
            assert json.loads(kwargs["input"])["metadata"] == {
                "name": "monori-oidc",
                "namespace": "monori",
            }

    def test_existing_litellm_custom_scope_survives_foundation_replay(self) -> None:
        """Preserve the custom litellm scope across replays."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.setup_root(root)
            api = FakeAuthentik()
            api.data["propertymappings/provider/scope/"].append(
                {
                    "pk": "litellm-identity",
                    "name": "homelab-litellm-reviewed-identity",
                    "scope_name": "litellm_identity",
                }
            )
            self.configure(root, api)
            self.configure(root, api)
            provider = next(
                p for p in api.data["providers/oauth2/"] if p["name"] == "homelab-litellm"
            )
            assert "litellm-identity" in cast("list[str]", provider["property_mappings"])
            assert len(api.data["core/applications/"]) == 7

    def test_existing_owner_never_silently_taken_over(self) -> None:
        """Never take over an existing owner account."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.setup_root(root)
            api = FakeAuthentik()
            api.data["core/users/"] = [{"pk": 42, "username": "alchemmist"}]
            with pytest.raises(RuntimeError, match="already exists"):
                self.configure(root, api)
            assert not any(path.endswith("/set_password/") for _, path, _, _ in api.requests)

    def test_missing_provider_credentials_refuses_rotation(self) -> None:
        """Refuse credential rotation when files are missing."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.setup_root(root)
            api = FakeAuthentik()
            self.configure(root, api)
            (root / "oidc-clients.json").unlink()
            with pytest.raises(RuntimeError, match="refusing rotation"):
                self.configure(root, api)

    def test_unexpected_owner_member_cannot_be_promoted(self) -> None:
        """Refuse to promote an unexpected member of the owner group."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.setup_root(root)
            api = FakeAuthentik()
            self.configure(root, api)
            group = next(g for g in api.data["core/groups/"] if g["name"] == "homelab-owner")
            cast("list[object]", group["users"]).append(999)
            group["is_superuser"] = False
            with pytest.raises(RuntimeError, match="Unexpected owner"):
                self.configure(root, api)
            assert not group["is_superuser"]

    def test_runtime_is_not_a_cluster_administrator(self) -> None:
        """Keep the runtime service account out of cluster administration."""
        values = yaml.safe_load((ROOT / "deploy/authentik/values.yaml").read_text())
        assert not values["serviceAccount"]["create"]
        for name in ["server", "worker"]:
            assert not values[name]["automountServiceAccountToken"]
            assert values[name]["resources"]["limits"]["memory"]
        assert not values["postgresql"]["enabled"]
        assert "secret_key" not in values["authentik"]

    def test_world_readable_primary_kubeconfig_not_reintroduced(self) -> None:
        """Keep the primary kubeconfig non-world-readable."""
        source = (ROOT / "ansible/roles/k3s_ha/templates/config.yaml.j2").read_text()
        assert "'0644'" not in source
        assert "write-kubeconfig-group: alchemmist" in source
        install = (ROOT / "ansible/playbooks/k3s.yml").read_text()
        assert "--write-kubeconfig-mode 644" not in install

    def test_personal_keys_replaced_not_appended(self) -> None:
        """Replace personal key sets instead of appending."""
        tasks = yaml.safe_load((ROOT / "ansible/roles/users/tasks/main.yml").read_text())
        key_task = next(t for t in tasks if "Replace managed key sets" in t["name"])
        assert "ansible.builtin.copy" in key_task
        assert "ansible.builtin.lineinfile" not in key_task
        assert "'disabled'" in key_task["ansible.builtin.copy"]["content"]

    def test_grafana_keeps_local_login_and_uses_secret_reference(self) -> None:
        """Keep local Grafana login with secret references."""
        v = yaml.safe_load((ROOT / "deploy/identity/grafana-oidc-values.yaml").read_text())[
            "grafana"
        ]
        assert "GF_AUTH_DISABLE_LOGIN_FORM" not in v["env"]
        assert v["env"]["GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN"] == "true"
        assert v["env"]["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
        assert "GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET" not in v["env"]
        assert (
            v["envValueFrom"]["GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET"]["secretKeyRef"]["name"]
            == "socrat-authentik-grafana"
        )


class RolloutRegressionTests(unittest.TestCase):
    def test_pinned_icons_match_local_portal_assets(self) -> None:
        """Match pinned icons to the committed portal assets."""
        import hashlib
        import xml.etree.ElementTree as ET

        manifest = json.loads((ROOT / "assets/service-icons/sources.json").read_text())
        services = json.loads((ROOT / "deploy/identity/services.json").read_text())
        managed = {
            slug: service
            for slug, service in services.items()
            if not service.get("managedBy") or slug == "monori"
        }
        assert len(managed) == 8
        for slug, service in managed.items():
            data = (ROOT / "assets/service-icons" / f"{slug}.svg").read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            assert digest == manifest["files"][f"{slug}.svg"]["sha256"]
            assert (
                service["icon"]
                == f"https://auth.socrat.alchemmist.xyz/-/quiet-mono/v1/{digest[:12]}-{slug}.svg"
            )
            for node in ET.fromstring(data).iter():
                assert node.tag.split("}")[-1] not in ["script", "foreignObject"]
                assert not any(k.lower().startswith("on") for k in node.attrib)

    def test_reviewed_human_reconciliation_keeps_tim_non_privileged(self) -> None:
        """Keep the reviewed human non-privileged after replay."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            helper = IdentityTests()
            helper.setup_root(root)
            api = FakeAuthentik()
            helper.setup_reviewed(root, api)
            helper.configure(root, api)
            helper.configure(root, api)
            assert len(api.data["core/users/"]) == 2
            owner_group = next(g for g in api.data["core/groups/"] if g["name"] == "homelab-owner")
            tim = next(u for u in api.data["core/users/"] if u["username"] == "antropophag")
            assert owner_group["pk"] not in cast("list[object]", tim["groups"])
            assert tim["pk"] not in cast("list[object]", owner_group["users"])
            assert (root / "antropophag-login.json").stat().st_mode & 511 == 384

    def test_n8n_native_login_and_machine_paths_have_no_idp_gate(self) -> None:
        """Keep n8n native paths free of identity gates."""
        services = json.loads((ROOT / "deploy/identity/services.json").read_text())
        assert services["n8n"]["managedBy"] == "native-n8n"
        assert services["n8n"]["accessManagement"]["state"] == "blocked"
        assert "proxy" not in services["n8n"]
        assert "redirect" not in services["n8n"]
        assert "uptime-kuma" not in services
        resources = list(
            yaml.safe_load_all((ROOT / "charts/n8n/templates/access.yaml").read_text())
        )
        assert len(resources) == 1
        machine = resources[0]
        assert machine["metadata"]["namespace"] == "automation"
        for path in machine["spec"]["rules"][0]["http"]["paths"]:
            assert path["backend"]["service"]["name"] == "n8n"
            assert path["path"] != "/"
        assert yaml.safe_load((ROOT / "charts/n8n/values.yaml").read_text())["ingress"]["enabled"]
        assert "n8n-gateway" not in (ROOT / "ansible/roles/authentik/tasks/main.yml").read_text()

    def test_owner_mapping_is_server_admin_only_for_owner_group(self) -> None:
        """Grant Grafana server admin only to the owner group."""
        env = yaml.safe_load((ROOT / "deploy/identity/grafana-oidc-values.yaml").read_text())[
            "grafana"
        ]["env"]
        assert env["GF_AUTH_GENERIC_OAUTH_ALLOW_ASSIGN_GRAFANA_ADMIN"] == "true"
        assert (
            env["GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH"]
            == "contains(groups[*], 'homelab-owner') && 'GrafanaAdmin' || contains(groups[*], 'app-grafana-editor') && 'Editor' || (contains(groups[*], 'homelab-observer') || contains(groups[*], 'homelab-platform-operator') || contains(groups[*], 'homelab-project-maintainer') || contains(groups[*], 'app-grafana-viewer')) && 'Viewer' || ''"
        )
        assert "offline_access" in env["GF_AUTH_GENERIC_OAUTH_SCOPES"].split()
        assert env["GF_AUTH_GENERIC_OAUTH_USE_REFRESH_TOKEN"] == "true"
        assert env["GF_AUTH_LOGIN_MAXIMUM_LIFETIME_DURATION"] == "8h"
        webui = json.loads((ROOT / "deploy/identity/open-webui-env.json").read_text())
        assert webui["OAUTH_MERGE_ACCOUNTS_BY_EMAIL"] == "False"
        assert webui["OAUTH_ADMIN_ROLES"] == "homelab-owner"

    def test_sudo_listing_rc_zero_is_not_a_privilege_grant(self) -> None:
        """Treat an rc-zero sudo listing as no privilege grant."""
        import subprocess
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".ssh").mkdir()
            (Path(d) / ".ssh/authorized_keys").write_text("key1\nkey2\n")

            def run(args: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
                """Answer sshd -T, sudo, and generic probes with scripted results."""
                if "-T" in args:
                    return subprocess.CompletedProcess(
                        args,
                        0,
                        "\x1b]3008;test\x1b\\pubkeyauthentication yes\nusepam yes\n",
                        "",
                    )
                if args[0] == "sudo":
                    return subprocess.CompletedProcess(
                        args,
                        0,
                        "User tim is not allowed to run sudo on socrat-0.\n",
                        "",
                    )
                return subprocess.CompletedProcess(args, 1, "", "")

            output = io.StringIO()
            with (
                patch("sys.argv", ["verify.py", "tim"]),
                patch(
                    "pwd.getpwnam",
                    return_value=SimpleNamespace(pw_dir=d, pw_shell="/bin/bash"),
                ),
                patch("subprocess.run", run),
                patch("shutil.which", return_value="/usr/sbin/sshd"),
                contextlib.redirect_stdout(output),
            ):
                runpy.run_path(
                    str(ROOT / "ansible/roles/users/files/verify.py"),
                    run_name="__main__",
                )
            result = json.loads(output.getvalue())
            assert not result["hasSudoGrant"]
            assert not result["canReadAdminKubeconfig"]
            assert result["pubkeyAuthentication"] == "yes"
            assert result["usePAM"] == "yes"


if __name__ == "__main__":
    unittest.main()
