"""Offline n8n OIDC identity: catalog, chart hostAlias pin, provisioning rails."""

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
IMG = "ghcr.io/alchemmist/n8n@"
SS = "socrat-n8n"


spec = importlib.util.spec_from_file_location("iam_n8n", ROOT / "scripts/spi-queue-oidc.py")
iam_n8n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iam_n8n)


def render() -> dict[tuple[str, str], dict[str, object]]:
    raw = subprocess.check_output(
        [
            "helm",
            "template",
            "n8n",
            str(ROOT / "charts/n8n"),
            "-f",
            str(ROOT / "charts/n8n/values.yaml"),
        ],
        text=True,
    )
    return {
        (x["kind"], x["metadata"]["name"]): x for x in yaml.safe_load_all(raw) if x
    }


class N8nOidcCatalogTests(unittest.TestCase):
    """The identity catalog owns the n8n native-oidc admission decision."""

    def test_catalog_is_ready_and_native(self) -> None:
        catalog = json.loads((ROOT / "deploy/identity/services.json").read_text())
        n8n = catalog["n8n"]
        assert n8n["managedBy"] == "native-n8n"
        assert n8n["accessManagement"]["state"] == "ready"
        assert "no JIT" in n8n["accessManagement"]["reason"]
        assert n8n["admission"] == "native-oidc"
        assert n8n["redirect"] == (
            "https://n8n.socrat.alchemmist.xyz/rest/sso/oidc/callback"
        )
        assert n8n["groups"] == ["homelab-owner"]


class N8nOidcChartTests(unittest.TestCase):
    """The chart pins the Authentik hostAlias and carries no dead OIDC env."""

    def test_host_alias_pins_public_ip(self) -> None:
        pod = render()["Deployment", "n8n"]["spec"]["template"]
        assert {"ip": "109.173.40.247", "hostnames": ["auth.socrat.alchemmist.xyz"]} == (
            pod["spec"]["hostAliases"][0]
        )

    def test_no_dead_oidc_env(self) -> None:
        env = render()["Deployment", "n8n"]["spec"]["template"]["spec"]["containers"][0]["env"]
        assert not [e for e in env if "N8N_SSO_OIDC" in e["name"]]

    def test_image_is_fork_digest(self) -> None:
        image = render()["Deployment", "n8n"]["spec"]["template"]["spec"]["containers"][0]["image"]
        assert image.startswith(IMG)


def _script(name: str) -> str:
    return (ROOT / ("scripts/" + name)).read_text()


@pytest.mark.parametrize(
    "name",
    [
        "provision-n8n-oidc.py",
        "activate-n8n-oidc.py",
    ],
)
def test_scripts_share_the_iam_rails(name: str) -> None:
    """Both n8n identity scripts keep the plan/backup/privacy rails visible."""
    text = _script(name)
    assert "client_secret" in text
    # Never print credentials: reporting is digest/hash only.
    assert "sha256" in text
    assert "print" in text
    assert "kubectl" in text


def test_provisioner_needs_hash_and_backup() -> None:
    text = _script("provision-n8n-oidc.py")
    assert "--approve-plan-hash" in text
    assert "--backup-receipt" in text
    assert "plan_hash" in text
    assert "uncertain" in text
    assert "no adoption/reset" in text
    assert SS in text


def test_activation_is_single_shot_and_private() -> None:
    text = _script("activate-n8n-oidc.py")
    assert "features.oidc" in text
    assert "userManagement.authenticationMethod" in text
    assert "already present" in text  # refuses a second apply
    assert "os.umask(0o077)" in text
    assert "BEGIN;" in text and "COMMIT;" in text  # one transaction
    assert "private(" in text


def test_docs_explain_the_vip_block() -> None:
    doc = (ROOT / "docs/auth/authentik/integrations/n8n-oidc.md").read_text()
    assert "192.168.0.250" in doc
    assert "features.oidc" in doc
    assert "N8N_SSO_OIDC_" in doc


def test_provisioner_module_uses_shared_iam() -> None:
    assert hasattr(iam_n8n, "API")
    assert iam_n8n.FLOWS["authentication_flow"] == "default-authentication-flow"
