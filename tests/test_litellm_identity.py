"""Offline regression checks; no live credentials or cluster operations."""

import ast
import base64
import hashlib
import importlib.util
import json
import struct
import textwrap
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def controller() -> ModuleType:
    """Import the committed LiteLLM OIDC helper as a module."""
    path = ROOT / "ansible/roles/identity_integrations/files/litellm_oidc.py"
    spec = importlib.util.spec_from_file_location("litellm_oidc", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiteLLMIdentityTests(unittest.TestCase):
    """Prove subject, group, PKCE, and icon boundaries without a live provider."""

    def test_identity_mapping_uses_uuid_not_email_or_name(self) -> None:
        """Select the owner by UUID and refuse an email or username match."""
        module = controller()
        owner = "ad03842b-12a5-41e1-b875-fb712657e326"
        expression = module.identity_expression(owner, "owner@example.org")
        namespace = {
            "request": SimpleNamespace(
                user=SimpleNamespace(uuid=owner, email="different@example.org")
            )
        }
        exec("def mapping():\n" + textwrap.indent(expression, "    "), namespace)
        assert namespace["mapping"]()["litellm_user_id"] == "socrat-admin"
        assert namespace["mapping"]()["litellm_user_role"] == "proxy_admin"
        assert namespace["mapping"]()["litellm_user_email"] == "owner@example.org"
        other = "ed03842b-12a5-41e1-b875-fb712657e326"
        namespace["request"].user = SimpleNamespace(
            uuid=other, email="owner@example.org", username="alchemmist"
        )
        result = namespace["mapping"]()
        assert result["litellm_user_id"] == "authentik:" + other
        assert result["litellm_user_role"] == "internal_user_viewer"
        assert result["litellm_user_email"] != "owner@example.org"

    def test_reviewed_subject_gets_only_internal_user(self) -> None:
        """Grant a reviewed subject internal_user and keep the owner as proxy admin."""
        module = controller()
        owner = "ad03842b-12a5-41e1-b875-fb712657e326"
        member = "ed03842b-12a5-41e1-b875-fb712657e326"
        expression = module.identity_expression(owner, "owner@example.org", [member])
        namespace = {
            "request": SimpleNamespace(
                user=SimpleNamespace(uuid=member, email="owner@example.org")
            )
        }
        exec("def mapping():\n" + textwrap.indent(expression, "    "), namespace)
        assert namespace["mapping"]()["litellm_user_role"] == "internal_user"
        assert namespace["mapping"]()["litellm_user_id"] == "authentik:" + member
        namespace["request"].user.uuid = owner
        assert namespace["mapping"]()["litellm_user_role"] == "proxy_admin"
        namespace["request"].user.uuid = "00000000-0000-0000-0000-000000000001"
        assert namespace["mapping"]()["litellm_user_role"] == "internal_user_viewer"

    def test_app_group_controls_role_without_per_user_uuid_grant(self) -> None:
        """Let the reviewed group grant internal_user without a per-user UUID."""
        module = controller()
        owner = "ad03842b-12a5-41e1-b875-fb712657e326"
        other = "ed03842b-12a5-41e1-b875-fb712657e326"
        memberships = []
        user = SimpleNamespace(
            uuid=other, ak_groups=SimpleNamespace(all=lambda: memberships)
        )
        namespace = {"request": SimpleNamespace(user=user)}
        expression = module.identity_expression(
            owner, "owner@example.org", (), "app-litellm-user"
        )
        exec("def mapping():\n" + textwrap.indent(expression, "    "), namespace)
        assert namespace["mapping"]()["litellm_user_role"] == "internal_user_viewer"
        memberships.append(SimpleNamespace(name="app-litellm-user"))
        assert namespace["mapping"]()["litellm_user_role"] == "internal_user"
        assert namespace["mapping"]()["litellm_user_id"] == "authentik:" + other
        memberships.clear()
        assert namespace["mapping"]()["litellm_user_role"] == "internal_user_viewer"
        user.uuid = owner
        assert namespace["mapping"]()["litellm_user_role"] == "proxy_admin"

    def test_catalog_is_owner_only_and_explicit_native_oidc(self) -> None:
        """Keep the catalog on the owner group and the explicit native OIDC mapping."""
        service = json.loads((ROOT / "deploy/identity/services.json").read_text())[
            "litellm"
        ]
        assert service["groups"] == ["homelab-owner"]
        assert service["redirect"] == "https://llm.alchemmist.xyz/sso/callback"
        assert service["extraScopeMappings"] == ["homelab-litellm-reviewed-identity"]
        assert "native-oidc" in service["migration"]
        account = json.loads(
            (ROOT / "deploy/identity/account-mappings.json").read_text()
        )["alchemmist"]
        assert account["litellmUserId"] == "socrat-admin"

    def test_native_pkce_and_capacity_gate_are_not_bypassed(self) -> None:
        """Require PKCE and the user cap, and keep the local-password boundary unchanged."""
        source = ast.unparse(
            ast.parse(
                (
                    ROOT / "ansible/roles/identity_integrations/files/litellm_oidc.py"
                ).read_text()
            )
        )
        assert "'GENERIC_CLIENT_USE_PKCE': 'true'" in source
        assert "len(users) > 5" in source
        assert "LITELLM_LICENSE" not in source
        assert "set_password" not in source
        assert "verify=False" not in source
        assert (
            "'password'" in source
        )  # Checks non-owner local-password boundary, does not reset it.

    def test_helm_replay_uses_optional_secret_refs(self) -> None:
        """Reference the Authentik secret optionally and disable env credential login."""
        import yaml

        values = yaml.safe_load((ROOT / "deploy/litellm/values.yaml").read_text())
        env = [e for e in values["extraEnvVars"] if e["name"].startswith("GENERIC_")]
        expected_env_count = 10
        assert len(env) == expected_env_count
        for value in env:
            ref = value["valueFrom"]["secretKeyRef"]
            assert ref["optional"]
            assert ref["name"] == "socrat-authentik-litellm"
        assert values["proxy_config"]["general_settings"][
            "disable_env_credential_login"
        ]

    def test_circle_is_original_high_resolution_artwork(self) -> None:
        """Match the reviewed wiki artwork digest and its 512-pixel raster."""
        sources = json.loads((ROOT / "assets/service-icons/sources.json").read_text())[
            "files"
        ]
        for slug in ["wiki"]:
            record = sources[slug + ".svg"]
            assert (
                hashlib.sha256((ROOT / record["source"]).read_bytes()).hexdigest()
                == record["source_sha256"]
            )
            svg = ET.fromstring(
                (ROOT / "assets/service-icons" / (slug + ".svg")).read_bytes()
            )
            image = next(iter(svg))
            content = base64.b64decode(
                image.attrib["{http://www.w3.org/1999/xlink}href"].split(",", 1)[1]
            )
            assert struct.unpack(">II", content[16:24]) == (512, 512)
        assert "/svg/argo-cd.svg" in sources["argocd.svg"]["url"]

    def test_litellm_uses_official_product_logo_not_wiki_artwork(self) -> None:
        """Use the pinned LiteLLM monogram rather than the wiki artwork."""
        sources = json.loads((ROOT / "assets/service-icons/sources.json").read_text())[
            "files"
        ]
        record = sources["litellm.svg"]
        assert "githubusercontent.com/BerriAI/litellm/" in record["url"]
        assert "/" + record["revision"] + "/" in record["url"]
        assert record["url"].endswith("/litellm_monogram.svg")
        content = (ROOT / "assets/service-icons/litellm.svg").read_bytes()
        assert hashlib.sha256(content).hexdigest() == record["sha256"]
        assert record["sha256"] != sources["wiki.svg"]["sha256"]
        svg = ET.fromstring(content)
        assert svg.attrib["viewBox"] == "0 0 372.14 371.53"
        assert any(n.tag.endswith("path") for n in svg)
        assert not any(
            n.tag.split("}")[-1] in ["script", "foreignObject", "image"]
            for n in svg.iter()
        )
        service = json.loads((ROOT / "deploy/identity/services.json").read_text())[
            "litellm"
        ]
        assert (
            service["icon"]
            == "https://auth.socrat.alchemmist.xyz/-/quiet-mono/v1/"
            + record["sha256"][:12]
            + "-litellm.svg"
        )

    def test_icon_reconciler_patches_only_icon_metadata(self) -> None:
        """Allow one Authentik patch and restrict its body to the icon field."""
        tree = ast.parse((ROOT / "ansible/roles/authentik/files/icons.py").read_text())
        patches = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "api"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and n.args[0].value == "PATCH"
        ]
        assert len(patches) == 1
        assert [key.value for key in patches[0].args[2].keys] == ["meta_icon"]


if __name__ == "__main__":
    unittest.main()
