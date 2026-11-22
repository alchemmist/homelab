"""Tests for the remaining public web access paths."""

import ast
import copy
import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType
from typing import NotRequired, TypedDict

import pytest
import yaml

from tests.public_entry_contract import assert_read_only_status_policy

ROOT = Path(__file__).resolve().parents[1]


def module(name: str, directory: str = "ansible/scripts") -> ModuleType:
    s = importlib.util.spec_from_file_location(name, ROOT / directory / f"{name}.py")
    assert s is not None
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_scoped_web_groups_create_no_users() -> None:
    m = module("public-web-role-groups")
    ops = m.plan([])
    assert {x["name"] for x in ops} == {
        "syncthing-web-admins",
        "uptime-kuma-web-admins",
    }
    assert all(
        x["users"] == x["parents"] == x["children"] == x["roles"] == []
        and x["is_superuser"] is False
        for x in ops
    )
    assert m.plan(ops) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("is_superuser", True),
        ("parents", ["owner"]),
        ("roles", ["admin"]),
        ("attributes", {}),
        ("children", ["inheritor"]),
    ],
)
def test_reject_foreign_or_privileged_web_group(field, value) -> None:
    m = module("public-web-role-groups")
    ops = m.plan([])
    ops[0][field] = value
    with pytest.raises(RuntimeError):
        m.plan(ops)


class _EnvVar(TypedDict):
    """Grafana environment entry sourced from reviewed defaults or a secret."""

    name: str
    value: NotRequired[str]
    valueFrom: NotRequired[dict[str, dict[str, str]]]


class _Container(TypedDict):
    """Deployment container with an optional ordered environment list."""

    name: str
    env: NotRequired[list[_EnvVar]]


class _PodSpec(TypedDict):
    """Pod template owned fields exercised by the SSO environment plan."""

    containers: list[_Container]


class _TemplateSpec(TypedDict):
    """Inner template pod spec block."""

    spec: _PodSpec


class _DeploymentSpec(TypedDict):
    """Deployment spec template holder."""

    template: _TemplateSpec


class _Deployment(TypedDict):
    """Grafana deployment fragment rendered for public SSO review."""

    spec: _DeploymentSpec


def grafana() -> _Deployment:
    e = {
        "GF_AUTH_GENERIC_OAUTH_ENABLED": "true",
        "GF_AUTH_GENERIC_OAUTH_CLIENT_ID": "socrat-grafana",
        "GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT": "true",
        "GF_AUTH_OAUTH_ALLOW_INSECURE_EMAIL_LOOKUP": "false",
        "GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN": "false",
        "GF_AUTH_GENERIC_OAUTH_ALLOWED_GROUPS": "homelab-owner homelab-observer homelab-platform-operator homelab-project-maintainer",
        "GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH": "contains(groups[*], 'homelab-owner') && 'GrafanaAdmin' || 'Viewer'",
        "GOMEMLIMIT": "1GiB",
    }
    env: list[_EnvVar] = [{"name": k, "value": v} for k, v in e.items()]
    env.append(
        {
            "name": "GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET",
            "valueFrom": {
                "secretKeyRef": {
                    "name": "socrat-authentik-grafana",
                    "key": "client-secret",
                }
            },
        }
    )
    return {
        "spec": {
            "template": {
                "spec": {"containers": [{"name": "sidecar"}, {"name": "grafana", "env": env}]}
            }
        }
    }


def test_grafana_only_reviewed_env_changes() -> None:
    m = module("grafana-public-sso")
    d = grafana()
    before = copy.deepcopy(d)
    index, changes, result = m.env_plan(d)
    assert d == before
    assert index == 1
    assert set(changes) == set(m.DESIRED)
    assert next(x for x in result if x["name"] == "GOMEMLIMIT")["value"] == "1GiB"
    for e in before["spec"]["template"]["spec"]["containers"][1]["env"]:
        if e["name"] not in m.DESIRED:
            assert e in result
    d["spec"]["template"]["spec"]["containers"][1]["env"] = result
    assert m.env_plan(d)[1] == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("GF_AUTH_GENERIC_OAUTH_ENABLED", "false"),
        ("GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT", "false"),
        ("GF_AUTH_GENERIC_OAUTH_ALLOWED_GROUPS", "All"),
        ("GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_PATH", "'GrafanaAdmin'"),
        ("GF_AUTH_OAUTH_ALLOW_INSECURE_EMAIL_LOOKUP", "true"),
    ],
)
def test_grafana_drift_stops(key, value) -> None:
    m = module("grafana-public-sso")
    d = grafana()
    next(e for e in d["spec"]["template"]["spec"]["containers"][1]["env"] if e["name"] == key)[
        "value"
    ] = value
    with pytest.raises(RuntimeError):
        m.env_plan(d)


def test_public_policies_keep_machine_auth_and_block_human_fallbacks() -> None:
    gf = (ROOT / "deploy/platform/grafana/public-entry/files/grafana-policy.conf").read_text()
    assert "~*^Basic 1" in gf
    assert "~^POST:/login/?$ 1" in gf
    assert 'proxy_set_header Authorization ""' not in gf
    assert "proxy_set_header Upgrade $http_upgrade" in gf
    kuma = (ROOT / "charts/uptime-kuma/files/kuma-policy.conf").read_text()
    assert_read_only_status_policy(kuma)
    sync = (ROOT / "charts/syncthing/files/syncthing-policy.conf").read_text()
    assert "proxy_pass http://gui0/;" in sync
    assert "auth_basic" not in sync
    assert "auth_request" not in sync
    assert "return 410" in sync
    assert "syncthing-sync-1" not in sync


def render_status(*args: str) -> list[dict[str, object]]:
    """Render the complete post-retirement status release, including Gatus."""
    return [
        x
        for x in yaml.safe_load_all(
            subprocess.check_output(
                [
                    "helm",
                    "template",
                    "uptime-kuma",
                    str(ROOT / "charts/uptime-kuma"),
                    *args,
                ],
                text=True,
            )
        )
        if x
    ]


def test_kuma_no_gitops_random_secret_by_default() -> None:
    docs = render_status()
    assert not any(x["kind"] == "Secret" for x in docs)
    assert (
        next(x for x in docs if x["kind"] == "Ingress")["spec"]["rules"][0]["http"]["paths"][0][
            "backend"
        ]["service"]["name"]
        == "public-web-kuma-proxy"
    )
    deployments = [x for x in docs if x["kind"] == "Deployment"]
    assert len(deployments) == 2
    assert {x["metadata"]["name"]: x["spec"]["replicas"] for x in deployments} == {
        "gatus": 1,
        "public-web-kuma-proxy": 1,
    }


def test_schema_recovery_never_resets_existing_passwords_or_restarts_database() -> None:
    text = ast.unparse(
        ast.parse((ROOT / "ansible/scripts/kuma-db-account-recovery.py").read_text())
    )
    assert "CREATE USER" in text
    assert "ALTER USER" not in text
    assert "DROP USER" not in text
    assert "rollout restart" not in text
    assert "secret['metadata']['resourceVersion']" in text
    assert "schema_grant.replace" in text
    assert "--patch-file=/dev/stdin" in text
    assert "Foreign/partial service account; stop" in text
    assert "uncertain.json" in text


def test_retired_bootstrap_cannot_provision_a_database_or_account() -> None:
    # The retired chart inputs must have no effect, even if an old override
    # requests a fresh account and a running MariaDB/Kuma writer.
    assert (
        render_status(
            "--set",
            "database.bootstrapSecret=true,database.enabled=true,database.replicaCount=1,replicaCount=1",
        )
        == render_status()
    )


def test_dns_cleanup_only_owned_files_and_no_global_flush_or_vpn_commands() -> None:
    text = (ROOT / "scripts/macos-public-dns-cleanup.py").read_text()
    m = module("macos-public-dns-cleanup", "scripts")
    assert len(m.DOMAINS) == 12
    assert all(x.endswith(".alchemmist.xyz") for x in m.DOMAINS)
    for forbidden in [
        "dscacheutil",
        "killall",
        "networksetup",
        "netbird down",
        "set State:/Network/Global/DNS",
    ]:
        assert forbidden not in text
    expected = ast.parse("run(['/bin/launchctl', 'bootout', 'system/' + LABEL])", mode="eval").body
    assert any(
        isinstance(node, ast.Call) and ast.dump(node) == ast.dump(expected)
        for node in ast.walk(ast.parse(text))
    )
    assert "Backup verification failed" in text
    assert "Fresh exact plan approval required" in text


def test_new_clients_do_not_reinstall_private_dns_by_default() -> None:
    defaults = yaml.safe_load(
        (ROOT / "ansible/roles/wireguard_admin_client/defaults/main.yml").read_text()
    )
    assert defaults["wireguard_admin_dns_mode"] == "none"
    task = (ROOT / "ansible/roles/wiki_editor_client/tasks/main.yml").read_text()
    assert "wiki_editor_client_private_dns_legacy | default(false)" in task
    assert "include_tasks: legacy-resolver.yml" in task
