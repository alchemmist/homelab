"""Render owner OpenHands values offline; never install or start the agent image."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from scripts.quality.common import command

ROOT = Path(__file__).resolve().parents[1]
VOLUME_FIELD_COUNT = 2
BACKUP_DEADLINE_SECONDS = 2400
IMAGE = (
    "ghcr.io/openhands/agent-canvas:1.41.0@sha256:"
    "dcae97b63c9845fd1d4313857af6b10fb5888324a154238c4795ef86233d227c"
)


def _mapping(value: object) -> dict[str, object]:
    """Validate mapping keys without pretending to certify its dynamic fields."""
    assert isinstance(value, dict)
    result: dict[str, object] = {}
    for key, item in value.items():
        assert isinstance(key, str)
        result[key] = item
    return result


def _list(value: object) -> list[object]:
    """Retain every unknown element for subsequent concrete shape checks."""
    assert isinstance(value, list)
    return list(value)


def _one(documents: list[dict[str, object]], kind: str) -> dict[str, object]:
    """Require one resource of the requested kind rather than choosing an arbitrary one."""
    matches = [doc for doc in documents if doc.get("kind") == kind]
    assert len(matches) == 1
    return matches[0]


def _pod(documents: list[dict[str, object]]) -> dict[str, object]:
    """Read the concrete rendered pod template, not merely the override intentions."""
    stateful = _mapping(_one(documents, "StatefulSet")["spec"])
    return _mapping(_mapping(stateful["template"])["spec"])


def _assert_isolated_boundary(documents: list[dict[str, object]]) -> None:
    """Guard rendered privileges, storage and image without certifying runtime isolation."""
    allowed = {
        "Namespace",
        "ResourceQuota",
        "NetworkPolicy",
        "ServiceAccount",
        "Service",
        "StatefulSet",
    }
    for doc in documents:
        kind = doc.get("kind")
        assert isinstance(kind, str)
        assert kind in allowed, "Unexpected OpenHands resource kind"
    expected_count = 7
    assert len(documents) == expected_count
    pod = _pod(documents)
    assert pod["automountServiceAccountToken"] is False, "Pod token automount enabled"
    account = _one(documents, "ServiceAccount")
    assert account["automountServiceAccountToken"] is False, (
        "ServiceAccount token automount enabled"
    )
    assert not any(
        key in pod for key in ("volumes", "hostNetwork", "hostPID", "hostIPC", "initContainers")
    ), "Host or extra mounts/process namespaces enabled"
    security = _mapping(pod["securityContext"])
    assert security == {
        "fsGroup": 10001,
        "runAsGroup": 10001,
        "runAsNonRoot": True,
        "runAsUser": 10001,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    containers = _list(pod["containers"])
    assert len(containers) == 1
    container = _mapping(containers[0])
    assert container["image"] == IMAGE, "Image pin changed"
    assert container["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
    }
    stateful = _mapping(_one(documents, "StatefulSet")["spec"])
    assert stateful["replicas"] == 1
    assert stateful["persistentVolumeClaimRetentionPolicy"] == {
        "whenDeleted": "Retain",
        "whenScaled": "Retain",
    }, "PVC retention weakened"
    claims = _list(stateful["volumeClaimTemplates"])
    assert len(claims) == 1
    claim = _mapping(claims[0])
    assert _mapping(claim["metadata"])["name"] == "data"
    spec = _mapping(claim["spec"])
    assert spec["storageClassName"] == "local-path"
    assert spec["accessModes"] == ["ReadWriteOnce"]
    assert _mapping(_mapping(spec["resources"])["requests"])["storage"] == "6Gi"
    assert container["volumeMounts"] == [
        {
            "name": "data",
            "mountPath": "/home/openhands/.openhands",
            "subPath": "openhands",
        },
        {
            "name": "data",
            "mountPath": "/home/openhands/workspace",
            "subPath": "workspace",
        },
    ]


def _get(value: object, *path: str) -> object:
    """Traverse validated mappings without importing operational code."""
    for key in path:
        value = _mapping(value)[key]
    return value


def _named(documents: list[dict[str, object]], kind: str, name: str) -> dict[str, object]:
    """Select a unique named role, never the first resource of an expanded kind."""
    matches = [
        d for d in documents if d.get("kind") == kind and _get(d, "metadata", "name") == name
    ]
    assert len(matches) == 1
    return matches[0]


def _embedded(relative: str) -> str:
    """Read source as inert text using YAML literal-block trailing-newline semantics."""
    return (ROOT / "charts/openhands" / relative).read_text().rstrip("\n") + "\n"


def _assert_owner_inventory(documents: list[dict[str, object]]) -> None:
    """Check the explicit owner inventory without executing its source."""
    expected = {
        ("Namespace", "", "openhands"),
        ("ConfigMap", "openhands", "pi-monori-code"),
        ("Deployment", "openhands", "pi-monori-author"),
        ("Deployment", "openhands", "pi-monori-judge"),
        ("NetworkPolicy", "openhands", "pi-monori-judge-offline"),
        ("NetworkPolicy", "openhands", "automation-postgres-egress"),
        ("ResourceQuota", "openhands", "openhands-budget"),
        ("ServiceAccount", "openhands", "openhands"),
        ("StatefulSet", "openhands", "openhands"),
        ("Service", "openhands", "openhands"),
        ("Service", "openhands", "openhands-headless"),
        ("NetworkPolicy", "openhands", "openhands-boundary"),
        ("NetworkPolicy", "openhands", "monori-publisher-canvas-out"),
        ("NetworkPolicy", "openhands", "monori-publisher-canvas-in"),
        ("NetworkPolicy", "identity", "openhands-oidc"),
        ("NetworkPolicy", "identity", "openhands-oidc-sessions"),
        ("NetworkPolicy", "openhands", "openhands-backup-pre142"),
        ("ConfigMap", "openhands", "openhands-cold-backup-20261119"),
        ("ConfigMap", "openhands", "monori-publisher-code"),
        ("ConfigMap", "openhands", "openhands-backup-pre142"),
        ("PersistentVolumeClaim", "openhands", "openhands-cold-backups"),
        ("PersistentVolumeClaim", "openhands", "openhands-upgrade-backups"),
        ("Service", "openhands", "monori-publisher"),
        ("Service", "identity", "openhands-oidc"),
        ("Service", "identity", "openhands-oidc-sessions"),
        ("Deployment", "openhands", "monori-publisher"),
        ("Deployment", "identity", "openhands-oidc"),
        ("Deployment", "identity", "openhands-oidc-sessions"),
        ("Job", "openhands", "openhands-cold-backup-20261119"),
        ("Ingress", "identity", "openhands-oidc"),
        ("Certificate", "identity", "openhands-oidc-tls"),
    }
    identities: set[tuple[str, str, str]] = set()
    for document in documents:
        kind = document.get("kind")
        assert isinstance(kind, str), "Unexpected OpenHands resource kind"
        assert isinstance(document.get("metadata"), dict), "Unexpected OpenHands resource kind"
        metadata = _mapping(document["metadata"])
        name = metadata.get("name")
        namespace = metadata.get("namespace", "" if kind == "Namespace" else "openhands")
        assert isinstance(name, str), "Unexpected OpenHands resource kind"
        assert isinstance(namespace, str), "Unexpected OpenHands resource kind"
        identity = (kind, namespace, name)
        assert identity in expected, "Unexpected OpenHands resource kind or identity"
        assert identity not in identities, "Unexpected OpenHands resource kind or identity"
        identities.add(identity)
    assert identities == expected, "Missing owner resource"


def _assert_owner_pods(documents: list[dict[str, object]], *, continuation: bool) -> None:
    """Check the explicit owner pods without executing its source."""
    values = _mapping(yaml.safe_load((ROOT / "deploy/openhands/values.yaml").read_text()))
    for document in documents:
        if document.get("kind") not in {"Deployment", "StatefulSet", "Job"}:
            continue
        pod = _mapping(_get(document, "spec", "template", "spec"))
        assert pod.get("automountServiceAccountToken") is False, "Pod token automount enabled"
        assert not any(k in pod for k in ("hostNetwork", "hostPID", "hostIPC")), (
            "Host or extra mounts/process namespaces enabled"
        )
        assert _get(pod, "securityContext", "runAsNonRoot") is True
        assert _get(pod, "securityContext", "seccompProfile") == {"type": "RuntimeDefault"}
        assert pod["nodeSelector"] == {"kubernetes.io/hostname": "socrat-5"}
        for volume in _list(pod.get("volumes", [])):
            v = _mapping(volume)
            assert len(v) == VOLUME_FIELD_COUNT, "Host or extra mounts enabled"
            assert set(v) <= {
                "name",
                "emptyDir",
                "secret",
                "configMap",
                "persistentVolumeClaim",
            }, "Host or extra mounts enabled"
        role = _get(document, "metadata", "name")
        assert isinstance(role, str)
        names = {
            "openhands": ["agent-canvas"]
            + (["iteration-continuation"] if continuation else []),
            "pi-monori-author": ["sandbox", "relay"],
            "pi-monori-judge": ["sandbox"],
            "monori-publisher": ["publisher"],
            "openhands-oidc": ["oauth2-proxy"],
            "openhands-oidc-sessions": ["redis"],
            "openhands-cold-backup-20261119": ["backup"],
        }
        containers = [_mapping(c) for c in _list(pod["containers"])]
        assert [c["name"] for c in containers] == names[role]
        init = [_mapping(c) for c in _list(pod.get("initContainers", []))]
        expected_init = {
            "openhands": ["prepare-iteration-policy"],
            "monori-publisher": ["prepare-encoder"],
            "pi-monori-author": ["install-pi"],
        }
        assert [c["name"] for c in init] == expected_init.get(role, [])
        for container in containers + init:
            security = _mapping(container["securityContext"])
            assert security["allowPrivilegeEscalation"] is False
            assert security.get("privileged", False) is False
            assert security["capabilities"] == {"drop": ["ALL"]}
            if container["name"] != "agent-canvas":
                assert security["readOnlyRootFilesystem"] is True
            expected_image = (
                _get(values, "oidc", "image")
                if role == "openhands-oidc"
                else _get(values, "oidc", "sessionImage")
                if role == "openhands-oidc-sessions"
                else IMAGE
            )
            assert container["image"] == expected_image, "Image pin changed"


def _pilot_fixture() -> dict[str, object]:
    """Load independently declared authority edges, not the chart under test."""
    return _mapping(
        yaml.safe_load((ROOT / "tests/fixtures/openhands-pilot-boundaries.yaml").read_text())
    )


def _assert_owner_canvas_extensions(
    documents: list[dict[str, object]], *, continuation: bool
) -> None:
    """Check the explicit owner canvas extensions without executing its source."""
    pod = _pod(documents)
    fixture = _pilot_fixture()
    assert pod["volumes"] == fixture["canvasVolumes"], "Host or extra mounts enabled"
    init = _mapping(_list(pod["initContainers"])[0])
    assert init["command"] == ["python", "-IB", "-c"]
    assert init["args"] == [_embedded("files/uncap_sdk_iterations.py")]
    assert init["volumeMounts"] == [{"name": "sdk-iteration-policy", "mountPath": "/overlay"}]
    containers = [_mapping(c) for c in _list(pod["containers"])]
    overlay = [
        {
            "name": "sdk-iteration-policy",
            "mountPath": (
                "/usr/local/lib/python3.13/site-packages/openhands/sdk/conversation/"
                "impl/local_conversation.py"
            ),
            "subPath": "local_conversation.py",
            "readOnly": True,
        },
        {
            "name": "sdk-iteration-policy",
            "mountPath": (
                "/usr/local/lib/python3.13/site-packages/openhands/sdk/conversation/"
                "goal/controller.py"
            ),
            "subPath": "controller.py",
            "readOnly": True,
        },
    ]
    mounts = _list(containers[0]["volumeMounts"])
    assert mounts[:3] == [{"name": "pg-ca", "mountPath": "/pg-ca", "readOnly": True}, *overlay], (
        "Database CA or SDK overlay mount boundary changed"
    )
    # Check sources and uniqueness: a second literal URL must not override the Secret.
    required = {
        "AUTOMATION_DB_URL": {"valueFrom": {"secretKeyRef": {"name": "automations-postgres", "key": "url"}}},
        "PGSSLROOTCERT": {"value": "/pg-ca/ca.crt"},
        "AUTOMATION_DB_POOL_SIZE": {"value": "3"},
        "AUTOMATION_DB_MAX_OVERFLOW": {"value": "1"},
        "AUTOMATION_RUN_MIGRATIONS_ON_STARTUP": {"value": "false"},
    }
    env = [_mapping(entry) for entry in _list(containers[0]["env"])]
    for name, source in required.items():
        assert [v for v in env if v["name"] == name] == [{"name": name, **source}], name
    if not continuation:
        return
    sidecar = containers[1]
    assert sidecar["command"] == ["python", "-IBu", "-c"]
    assert sidecar["args"] == [_embedded("files/continue_iterations.py")]
    assert sidecar["env"] == [
        {"name": "CONVERSATION_ID", "value": "1ab3985a-2193-4177-8dd2-8ec7d54dbfeb"},
        {"name": "QA_CONVERSATION_ID", "value": "51a35822-a870-43cc-a775-fd5e662f0039"},
    ]
    assert sidecar["volumeMounts"] == [
        {"name": "data", "mountPath": "/wait-state", "subPath": "iteration-wait-state"},
        {
            "name": "data",
            "mountPath": "/session-key",
            "subPath": "openhands/agent-canvas/api-key.txt",
            "readOnly": True,
        },
        {
            "name": "data",
            "mountPath": "/mutation-registry",
            "subPath": "openhands/agent-canvas/workspaces/75ad056ce4354c2e86fd12f8e1f4f6fe/.worker-registry",
            "readOnly": True,
        },
        {
            "name": "data",
            "mountPath": "/qa-registry",
            "subPath": "openhands/agent-canvas/workspaces/e74a67536db4498196f4a961070bf471/.worker-registry",
            "readOnly": True,
        },
    ], "Continuation session mount changed"


def _assert_owner_publisher_extensions(documents: list[dict[str, object]]) -> None:
    """Check the explicit owner publisher extensions without executing its source."""
    publisher = _named(documents, "Deployment", "monori-publisher")
    pub = _get(publisher, "spec", "template", "spec")
    assert _get(pub, "volumes") == [
        {"name": "encoder", "emptyDir": {"sizeLimit": "120Mi"}},
        {"name": "temp", "emptyDir": {"sizeLimit": "24Mi"}},
        {"name": "code", "configMap": {"name": "monori-publisher-code"}},
        {"name": "proof", "secret": {"secretName": "monori-proof-ticket", "defaultMode": 288}},
        {
            "name": "credential",
            "secret": {"secretName": "monori-publisher-user", "defaultMode": 288},
        },
    ]
    writer = _mapping(_list(_get(pub, "containers"))[0])
    assert writer["command"] == ["python", "-IB", "/code/publisher.py"]
    assert writer["volumeMounts"] == [
        {"name": "code", "mountPath": "/code", "readOnly": True},
        {"name": "encoder", "mountPath": "/encoder", "readOnly": True},
        {"name": "temp", "mountPath": "/tmp"},
        {"name": "credential", "mountPath": "/credential", "readOnly": True},
        {"name": "proof", "mountPath": "/proof", "readOnly": True},
    ], "Publisher credential mount changed"
    encoder = _mapping(_list(_get(pub, "initContainers"))[0])
    assert encoder["volumeMounts"] == [{"name": "encoder", "mountPath": "/encoder"}]
    assert encoder["args"] == [_embedded("files/steward/install_ffmpeg.py"), "/encoder/ffmpeg"]


def _assert_owner_oidc_extensions(documents: list[dict[str, object]]) -> None:
    """Check the explicit owner oidc extensions without executing its source."""
    gateway = _named(documents, "Deployment", "openhands-oidc")
    oauth = _mapping(_list(_get(gateway, "spec", "template", "spec", "containers"))[0])
    args = _list(oauth["args"])
    required = [
        "--provider=oidc",
        "--oidc-issuer-url=https://auth.socrat.alchemmist.xyz/application/o/openhands/",
        "--redirect-url=https://openhands.socrat.alchemmist.xyz/oauth2/callback",
        "--upstream=http://openhands.openhands.svc.cluster.local:8000/",
        "--allowed-group=homelab-owner",
        "--code-challenge-method=S256",
        "--skip-jwt-bearer-tokens=false",
        "--cookie-secure=true",
        "--cookie-httponly=true",
        "--session-store-type=redis",
        "--pass-access-token=false",
        "--pass-authorization-header=false",
        "--set-authorization-header=false",
    ]
    for required_arg in required:
        prefix = required_arg.split("=", 1)[0] + "="
        assert [a for a in args if isinstance(a, str) and a.startswith(prefix)] == [required_arg], (
            "OIDC authorization weakened"
        )
    assert not any(
        isinstance(a, str) and a.startswith(("--skip-auth", "--insecure-oidc", "--ssl-insecure"))
        for a in args
    ), "OIDC authorization weakened"
    ingress = _named(documents, "Ingress", "openhands-oidc")
    assert ingress["spec"] == {
        "ingressClassName": "traefik",
        "tls": [{"hosts": ["openhands.socrat.alchemmist.xyz"], "secretName": "openhands-oidc-tls"}],
        "rules": [
            {
                "host": "openhands.socrat.alchemmist.xyz",
                "http": {
                    "paths": [
                        {
                            "path": "/",
                            "pathType": "Prefix",
                            "backend": {
                                "service": {"name": "openhands-oidc", "port": {"number": 4180}}
                            },
                        }
                    ]
                },
            }
        ],
    }, "Public route bypasses OIDC"
    certificate = _named(documents, "Certificate", "openhands-oidc-tls")
    assert certificate["spec"] == {
        "secretName": "openhands-oidc-tls",
        "dnsNames": ["openhands.socrat.alchemmist.xyz"],
        "issuerRef": {"name": "letsencrypt-http01", "kind": "ClusterIssuer"},
    }


def _assert_owner_backup_declarations(documents: list[dict[str, object]]) -> None:
    """Check the explicit owner backup declarations without executing its source."""
    backup = _named(documents, "Job", "openhands-cold-backup-20261119")
    assert _get(backup, "spec", "backoffLimit") == 0
    assert _get(backup, "spec", "activeDeadlineSeconds") == BACKUP_DEADLINE_SECONDS
    backup_pod = _get(backup, "spec", "template", "spec")
    assert _get(backup_pod, "restartPolicy") == "Never"
    assert _get(backup_pod, "volumes") == [
        {
            "name": "source",
            "persistentVolumeClaim": {"claimName": "data-openhands-0", "readOnly": True},
        },
        {"name": "backup", "persistentVolumeClaim": {"claimName": "openhands-cold-backups"}},
        {"name": "config", "configMap": {"name": "openhands-cold-backup-20261119"}},
        {"name": "tmp", "emptyDir": {"medium": "Memory", "sizeLimit": "128Mi"}},
    ], "Backup source authority changed"
    backup_container = _mapping(_list(_get(backup_pod, "containers"))[0])
    assert backup_container["volumeMounts"] == [
        {"name": "source", "mountPath": "/source", "readOnly": True},
        {"name": "backup", "mountPath": "/backup"},
        {"name": "config", "mountPath": "/config", "readOnly": True},
        {"name": "tmp", "mountPath": "/tmp"},
    ], "Backup source authority changed"
    for name, size in [("openhands-cold-backups", "3Gi"), ("openhands-upgrade-backups", "1Gi")]:
        claim = _named(documents, "PersistentVolumeClaim", name)
        assert _get(claim, "metadata", "annotations") == {
            "argocd.argoproj.io/sync-options": "Prune=false,Delete=false"
        }
        assert claim["spec"] == {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": "local-path",
            "resources": {"requests": {"storage": size}},
        }


def _assert_owner_policy_declarations(documents: list[dict[str, object]]) -> None:
    """Check the explicit owner policy declarations without executing its source."""
    # Compare static policy declarations independently of Helm, not frozen hashes.
    # Only these exact framing directives occur outside the literal policy YAML.
    for relative in (
        "templates/scoped-publisher.yaml",
        "templates/socrat-oidc.yaml",
        "templates/socrat-sessions.yaml",
        "templates/upgrade-backup.yaml",
    ):
        for fragment in (ROOT / "charts/openhands" / relative).read_text().split("\n---\n"):
            if "\nkind: NetworkPolicy\n" not in fragment:
                continue
            literal = fragment.rstrip()
            for suffix in ("{{- end }}", "{{- if not .Values.retireFailedBackup }}"):
                literal = literal.removesuffix(suffix).rstrip()
            assert "{{" not in literal, "Policy template requires explicit review"
            declaration = _mapping(yaml.safe_load(literal))
            name = _get(declaration, "metadata", "name")
            assert isinstance(name, str)
            assert _named(documents, "NetworkPolicy", name)["spec"] == declaration["spec"], (
                "Network policy differs from declared edges"
            )
    boundary = _named(documents, "NetworkPolicy", "openhands-boundary")
    assert _get(boundary, "spec", "ingress") == [
        {
            "from": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": "identity"}
                    },
                    "podSelector": {"matchLabels": {"app": "openhands-oidc"}},
                }
            ],
            "ports": [{"port": 8000, "protocol": "TCP"}],
        }
    ], "Canvas ingress bypasses OIDC"


def _assert_owner_core_projection(documents: list[dict[str, object]]) -> None:
    """Check the explicit owner core projection without executing its source."""
    containers = [_mapping(c) for c in _list(_pod(documents)["containers"])]
    mounts = _list(containers[0]["volumeMounts"])
    # Only explicitly checked extensions are projected out. The original core
    # function and every original assertion remain intact, including exact mounts.
    core = copy.deepcopy(
        [
            d
            for d in documents
            if d.get("kind") in {"Namespace", "ResourceQuota", "ServiceAccount", "StatefulSet"}
            or (
                d.get("kind") == "Service"
                and _get(d, "metadata", "name") in {"openhands", "openhands-headless"}
            )
            or (
                d.get("kind") == "NetworkPolicy"
                and _get(d, "metadata", "name") == "openhands-boundary"
            )
        ]
    )
    stateful = _one(core, "StatefulSet")
    spec = _mapping(stateful["spec"])
    template = _mapping(spec["template"])
    plain_pod = _pod(core)
    plain_pod.pop("volumes")
    plain_pod.pop("initContainers")
    canvas = _mapping(containers[0])
    canvas["volumeMounts"] = mounts[3:]
    plain_pod["containers"] = [canvas]
    template["spec"] = plain_pod
    spec["template"] = template
    stateful["spec"] = spec
    _assert_isolated_boundary(core)


def _assert_pilot_boundaries(documents: list[dict[str, object]]) -> None:
    """Separate scratch/data access from model and report credentials."""
    fixture = _pilot_fixture()
    for name, expected in _mapping(fixture["deployments"]).items():
        role = _named(documents, "Deployment", name)
        pod = _mapping(_get(role, "spec", "template", "spec"))
        assert _get(role, "spec", "template", "metadata", "labels") == {"app": name}
        assert pod["volumes"] == _get(expected, "volumes")
        assert pod.get("shareProcessNamespace", False) is False
        assert not pod.get("ephemeralContainers")
        for value in _list(pod["containers"]) + _list(pod.get("initContainers", [])):
            container = _mapping(value)
            container_name = container["name"]
            assert isinstance(container_name, str)
            assert container["volumeMounts"] == _get(expected, "mounts", container_name)
            assert "envFrom" not in container
            assert container.get("env", []) == (
                [
                    {"name": "HOME", "value": "/scratch/home"},
                    {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
                ]
                if container_name == "sandbox"
                else []
            )
    for name, expected in _mapping(fixture["policies"]).items():
        assert _named(documents, "NetworkPolicy", name)["spec"] == expected
    boundary = _named(documents, "NetworkPolicy", "openhands-boundary")
    assert _get(boundary, "spec", "podSelector") == {
        "matchExpressions": [
            {"key": "app", "operator": "NotIn", "values": ["openhands-backup-pre142"]},
            {"key": "app", "operator": "NotIn", "values": ["pi-monori-judge"]},
        ]
    }


def _assert_boundary(documents: list[dict[str, object]], *, continuation: bool = False) -> None:
    """Validate every extension before invoking the unchanged original core guard."""
    _assert_owner_inventory(documents)
    _assert_owner_pods(documents, continuation=continuation)
    _assert_owner_canvas_extensions(documents, continuation=continuation)
    _assert_pilot_boundaries(documents)
    _assert_owner_publisher_extensions(documents)
    _assert_owner_oidc_extensions(documents)
    _assert_owner_backup_declarations(documents)
    _assert_owner_policy_declarations(documents)
    _assert_owner_core_projection(documents)


def _render(*options: str) -> list[dict[str, object]]:
    """Use only local Helm source/values with an explicitly empty kubeconfig."""
    result = command(
        [
            "helm",
            "template",
            "openhands",
            str(ROOT / "charts/openhands"),
            "-f",
            str(ROOT / "deploy/openhands/values.yaml"),
            "--namespace",
            "openhands",
            "--kubeconfig",
            "/dev/null",
            *options,
        ]
    )
    return [_mapping(value) for value in yaml.safe_load_all(result.stdout) if value is not None]


@pytest.fixture(scope="module")
def rendered() -> list[dict[str, object]]:
    """Render the actual owner values without feature overrides."""
    return _render()


def test_owner_overrides_render_without_cluster_or_public_ingress_authority(
    rendered: list[dict[str, object]],
) -> None:
    """The deployed source graph keeps token/RBAC/ingress and PVC retention boundaries."""
    _assert_boundary(rendered)
    namespace = _mapping(_one(rendered, "Namespace")["metadata"])
    assert _mapping(namespace["labels"])["pod-security.kubernetes.io/enforce"] == "restricted"
    policy = _mapping(_named(rendered, "NetworkPolicy", "openhands-boundary")["spec"])
    assert policy["policyTypes"] == ["Ingress", "Egress"]


@pytest.mark.parametrize(
    ("name", "replacement"),
    [
        ("AUTOMATION_DB_URL", {"value": "sqlite:///fallback"}),
        ("PGSSLROOTCERT", {"value": "/tmp/untrusted"}),
        ("AUTOMATION_RUN_MIGRATIONS_ON_STARTUP", {"value": "true"}),
    ],
)
def test_database_connection_rejects_changed_source(
    rendered: list[dict[str, object]], name: str, replacement: dict[str, str]
) -> None:
    """A literal URL, altered CA or startup DDL must not pass the owner contract."""
    _assert_boundary(rendered)
    documents = copy.deepcopy(rendered)
    owner = _one(documents, "StatefulSet")
    canvas = _mapping(_list(_pod(documents)["containers"])[0])
    index, = [i for i, entry in enumerate(_list(canvas["env"])) if _get(entry, "name") == name]
    documents[documents.index(owner)] = _mapping(_replace_path(
        owner, ("spec", "template", "spec", "containers", 0, "env", index),
        {"name": name, **replacement},
    ))
    with pytest.raises(AssertionError, match=name):
        _assert_boundary(documents)


def test_retired_pilot_switch_cannot_restore_any_authority() -> None:
    """A stale owner override must not reintroduce the pilot, its ticket, or intake."""
    _assert_boundary(_render("--set", "monoriPilot=true"))


def test_openhands_mcp_inventory_is_explicitly_no_client() -> None:
    """Do not confuse source admission with a new diagnostics/agent authorization."""
    audit = _mapping(json.loads((ROOT / "deploy/mcp/service-audit.json").read_text()))
    rows = [_mapping(value) for value in _list(audit["applications"])]
    matches = [row for row in rows if row.get("application") == "openhands"]
    assert len(matches) == 1
    assert matches[0]["decision"] == "no-client"
    assert "connector" not in matches[0]
    config = _mapping(json.loads((ROOT / ".pi/mcp.json").read_text()))
    assert "openhands" not in _mapping(config["mcpServers"])


@pytest.mark.parametrize(
    ("violation", "message"),
    [
        ("pod-token", "Pod token automount enabled"),
        ("sa-token", "ServiceAccount token automount enabled"),
        ("host-volume", "Host or extra mounts"),
        ("image", "Image pin changed"),
        ("retention", "PVC retention weakened"),
        ("rbac", "Unexpected OpenHands resource kind"),
        ("ingress", "Unexpected OpenHands resource kind"),
    ],
)
def test_boundary_rejects_real_rendered_graph_mutations(
    rendered: list[dict[str, object]],
    violation: str,
    message: str,
) -> None:
    """Each critical synthetic violation must fail the same compiled-graph guard."""
    _assert_boundary(rendered)
    documents = copy.deepcopy(rendered)
    pod = _pod(documents)
    # Helpers copy mappings, so explicitly replace the relevant source resource.
    stateful = _one(documents, "StatefulSet")
    spec = _mapping(stateful["spec"])
    template = _mapping(spec["template"])
    if violation == "pod-token":
        pod["automountServiceAccountToken"] = True
    elif violation == "sa-token":
        _one(documents, "ServiceAccount")["automountServiceAccountToken"] = True
    elif violation == "host-volume":
        pod["volumes"] = [{"name": "host", "hostPath": {"path": "/"}}]
    elif violation == "image":
        containers = _list(pod["containers"])
        container = _mapping(containers[0])
        container["image"] = "unverified:latest"
        containers[0] = container
        pod["containers"] = containers
    elif violation == "retention":
        spec["persistentVolumeClaimRetentionPolicy"] = {
            "whenDeleted": "Delete",
            "whenScaled": "Delete",
        }
    elif violation == "rbac":
        documents.append({"kind": "ClusterRoleBinding"})
    elif violation == "ingress":
        documents.append({"kind": "Ingress"})
    else:
        raise AssertionError(violation)
    template["spec"] = pod
    spec["template"] = template
    stateful["spec"] = spec
    with pytest.raises(AssertionError, match=message):
        _assert_boundary(documents)


def _replace_path(value: object, path: tuple[str | int, ...], replacement: object) -> object:
    """Replace one real nested fixture field, rebuilding its validated parents."""
    if not path:
        return replacement
    key, *tail = path
    if isinstance(key, int):
        items = _list(value)
        items[key] = _replace_path(items[key], tuple(tail), replacement)
        return items
    mapping = _mapping(value)
    mapping[key] = _replace_path(mapping[key], tuple(tail), replacement)
    return mapping


def _oidc_target(
    violation: str, documents: list[dict[str, object]]
) -> tuple[str, str, tuple[str | int, ...], object]:
    """Target the OIDC deployment args for the PKCE or bypass violations."""
    role, kind = "openhands-oidc", "Deployment"
    container = _mapping(
        _list(_get(_named(documents, kind, role), "spec", "template", "spec", "containers"))[0]
    )
    args = _list(container["args"])
    replacement = (
        [
            "--code-challenge-method=plain" if a == "--code-challenge-method=S256" else a
            for a in args
        ]
        if violation == "oidc-pkce"
        else [*args, "--skip-auth-regex=.*"]
    )
    return role, kind, ("spec", "template", "spec", "containers", 0, "args"), replacement


def _violation_target(
    violation: str, documents: list[dict[str, object]]
) -> tuple[str, str, tuple[str | int, ...], object] | None:
    """Locate the one authority edge each violation must mutate."""
    simple: dict[str, tuple[str, str, tuple[str | int, ...], object]] = {
        "public-backend": (
            "openhands-oidc",
            "Ingress",
            ("spec", "rules", 0, "http", "paths", 0, "backend", "service", "name"),
            "openhands",
        ),
        "overlay-write": (
            "openhands",
            "StatefulSet",
            ("spec", "template", "spec", "containers", 0, "volumeMounts", 1, "readOnly"),
            False,
        ),
        "database-ca-write": (
            "openhands",
            "StatefulSet",
            ("spec", "template", "spec", "containers", 0, "volumeMounts", 0, "readOnly"),
            False,
        ),
        "publisher-write": (
            "monori-publisher",
            "Deployment",
            ("spec", "template", "spec", "containers", 0, "volumeMounts", 3, "readOnly"),
            False,
        ),
        "relay-secret-in-author": (
            "pi-monori-author",
            "Deployment",
            ("spec", "template", "spec", "containers", 0, "volumeMounts", 0, "name"),
            "model",
        ),
        "judge-egress": ("pi-monori-judge-offline", "NetworkPolicy", ("spec", "egress"), [{}]),
        "database-egress": ("automation-postgres-egress", "NetworkPolicy", ("spec", "egress"), [{}]),
        "publisher-token": (
            "monori-publisher",
            "Deployment",
            ("spec", "template", "spec", "automountServiceAccountToken"),
            True,
        ),
        "redis-egress": ("openhands-oidc-sessions", "NetworkPolicy", ("spec", "egress"), [{}]),
    }
    if violation in simple:
        return simple[violation]
    if violation.startswith("oidc-"):
        return _oidc_target(violation, documents)
    if violation.startswith("backup-"):
        path = (
            ("spec", "template", "spec", "volumes", 0, "persistentVolumeClaim", "readOnly")
            if violation == "backup-volume-write"
            else ("spec", "template", "spec", "containers", 0, "volumeMounts", 0, "readOnly")
        )
        return "openhands-cold-backup-20261119", "Job", path, False
    if violation == "duplicate-identity":
        documents.append(copy.deepcopy(_named(documents, "Ingress", "openhands-oidc")))
        return None
    raise AssertionError(violation)


@pytest.mark.parametrize(
    "violation",
    [
        "oidc-pkce",
        "oidc-bypass",
        "public-backend",
        "overlay-write",
        "database-ca-write",
        "publisher-write",
        "backup-volume-write",
        "backup-mount-write",
        "relay-secret-in-author",
        "judge-egress",
        "database-egress",
        "publisher-token",
        "redis-egress",
        "duplicate-identity",
    ],
)
def test_current_owner_extensions_reject_targeted_mutations(
    rendered: list[dict[str, object]], violation: str
) -> None:
    """Prove a passing full baseline before mutating one actual authority edge."""
    _assert_boundary(rendered)
    documents = copy.deepcopy(rendered)
    target = _violation_target(violation, documents)
    if target is None:
        with pytest.raises(AssertionError, match="Unexpected OpenHands resource kind or identity"):
            _assert_boundary(documents)
        return
    role, kind, path, replacement = target
    resource = _named(documents, kind, role)
    documents[documents.index(resource)] = _mapping(_replace_path(resource, path, replacement))
    with pytest.raises(AssertionError):
        _assert_boundary(documents)


@pytest.mark.parametrize("mount", ["/session-key", "/mutation-registry", "/qa-registry"])
def test_opt_in_continuation_rejects_writable_credentials_and_registries(mount: str) -> None:
    """Retain the guard on real opt-in Helm output even though owner continuation is disarmed."""
    documents = _render(
        "--set-string",
        "continueIterationChat=1ab3985a-2193-4177-8dd2-8ec7d54dbfeb",
        "--set-string",
        "continueQaChat=51a35822-a870-43cc-a775-fd5e662f0039",
    )
    _assert_boundary(documents, continuation=True)
    stateful = _one(documents, "StatefulSet")
    pod = _pod(documents)
    sidecar = _mapping(_list(pod["containers"])[-1])
    index = next(
        i for i, v in enumerate(_list(sidecar["volumeMounts"])) if _get(v, "mountPath") == mount
    )
    documents[documents.index(stateful)] = _mapping(
        _replace_path(
            stateful,
            ("spec", "template", "spec", "containers", 1, "volumeMounts", index, "readOnly"),
            replacement=False,
        )
    )
    with pytest.raises(AssertionError, match="Continuation session mount changed"):
        _assert_boundary(documents, continuation=True)


@pytest.fixture
def handoff_gate(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load reviewed read-only definitions with the sole native fetch transport trapped."""

    def denied(*_args: object, **_kwargs: object) -> None:
        message = "Native fetch transport forbidden"
        raise AssertionError(message)

    monkeypatch.setattr(subprocess, "check_output", denied)
    spec = importlib.util.spec_from_file_location(
        "reviewed_openhands_gate",
        ROOT / "scripts/openhands-pr-ready.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert isinstance(module, ModuleType)
    return module


def _handoff_snapshot() -> dict[str, object]:
    """Construct only synthetic GitHub shapes, without authentication or API access."""
    head = "a" * 40
    snapshot: dict[str, object] = {
        "state": "OPEN",
        "url": "https://github.com/example/example/pull/1",
        "headRefOid": head,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "commits": {"nodes": [{"commit": {"oid": head}}]},
        "reviews": {
            "nodes": [
                {
                    "id": "review",
                    "author": {"login": "review-bot", "__typename": "Bot"},
                    "state": "APPROVED",
                    "body": "",
                    "commit": {"oid": head},
                }
            ]
        },
        "comments": {"nodes": []},
        "reviewThreads": {"nodes": []},
        "statusCheckRollup": {
            "contexts": {
                "nodes": [
                    {
                        "__typename": "CheckRun",
                        "name": "tests",
                        "status": "COMPLETED",
                        "conclusion": "SUCCESS",
                    },
                ]
            }
        },
    }

    for name, direction in [
        ("reviews", "hasNextPage"),
        ("comments", "hasNextPage"),
        ("reviewThreads", "hasNextPage"),
        ("commits", "hasPreviousPage"),
    ]:
        section = _mapping(snapshot[name])
        section["pageInfo"] = {direction: False}
        snapshot[name] = section
    rollup = _mapping(snapshot["statusCheckRollup"])
    checks = _mapping(rollup["contexts"])
    checks["pageInfo"] = {"hasNextPage": False}
    rollup["contexts"] = checks
    snapshot["statusCheckRollup"] = rollup
    return snapshot


@pytest.mark.parametrize("kind", ["UnknownContext", None, ""])
def test_handoff_rejects_unknown_ci_variants(handoff_gate: ModuleType, kind: object) -> None:
    """An arbitrary state=SUCCESS must not impersonate a legacy StatusContext."""
    snapshot = _handoff_snapshot()
    snapshot["statusCheckRollup"] = {
        "contexts": {
            "nodes": [{"__typename": kind, "state": "SUCCESS"}],
            "pageInfo": {"hasNextPage": False},
        }
    }
    report = _mapping(handoff_gate.assess(snapshot, {"review-bot"}, {"publisher"}))
    assert report["ready_to_review"] is False
    assert any(str(item).startswith("CI not green:") for item in _list(report["blockers"]))


@pytest.mark.parametrize("head", [None, "", "a" * 39, "g" * 40])
def test_handoff_rejects_invalid_head_identity(handoff_gate: ModuleType, head: object) -> None:
    """Matching malformed review identity cannot certify a concrete current commit."""
    snapshot = _handoff_snapshot()
    snapshot["headRefOid"] = head
    snapshot["reviews"] = {
        "nodes": [
            {
                "id": "review",
                "author": {"login": "review-bot", "__typename": "Bot"},
                "state": "APPROVED",
                "body": "",
                "commit": {"oid": head},
            }
        ]
    }
    report = _mapping(handoff_gate.assess(snapshot, {"review-bot"}, {"publisher"}))
    assert report["ready_to_review"] is False
    assert "Missing or invalid current head identity" in _list(report["blockers"])


@pytest.mark.parametrize("kind", ["CheckRun", "StatusContext"])
def test_handoff_retains_both_native_ci_success_variants(
    handoff_gate: ModuleType, kind: str
) -> None:
    """Actual check-run and legacy status contexts retain original positive behavior."""
    snapshot = _handoff_snapshot()
    snapshot["statusCheckRollup"] = {
        "contexts": {
            "pageInfo": {"hasNextPage": False},
            "nodes": [
                {
                    "__typename": kind,
                    "state": "SUCCESS",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                },
            ],
        }
    }
    report = _mapping(handoff_gate.assess(snapshot, {"review-bot"}, {"publisher"}))
    assert report["ready_to_review"] is True


@pytest.mark.parametrize(
    "connection", ["reviews", "comments", "reviewThreads", "commits", "checks", "thread-comments"]
)
@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {},
        {"hasNextPage": True, "hasPreviousPage": True},
        {"hasNextPage": None, "hasPreviousPage": None},
        {"hasNextPage": 0, "hasPreviousPage": 0},
    ],
)
def test_handoff_requires_explicit_complete_pagination(
    handoff_gate: ModuleType,
    connection: str,
    metadata: object,
) -> None:
    """All queried connections, including each nested thread, require boolean completion."""
    snapshot = _handoff_snapshot()
    if connection == "checks":
        rollup = _mapping(snapshot["statusCheckRollup"])
        section = _mapping(rollup["contexts"])
        section["pageInfo"] = metadata
        rollup["contexts"] = section
        snapshot["statusCheckRollup"] = rollup
    elif connection == "thread-comments":
        snapshot["reviewThreads"] = {
            "pageInfo": {"hasNextPage": False},
            "nodes": [
                {
                    "id": "empty-human-thread",
                    "isResolved": True,
                    "comments": {"nodes": [], "pageInfo": metadata},
                }
            ],
        }
    else:
        section = _mapping(snapshot[connection])
        section["pageInfo"] = metadata
        snapshot[connection] = section
    report = _mapping(handoff_gate.assess(snapshot, {"review-bot"}, {"publisher"}))
    assert report["ready_to_review"] is False
    assert "Incomplete pagination; cannot authorize handoff" in _list(report["blockers"])


def test_handoff_accepts_explicit_complete_nested_empty_connection(
    handoff_gate: ModuleType,
) -> None:
    """An explicitly complete empty human thread remains legitimate, not a hidden skip."""
    snapshot = _handoff_snapshot()
    snapshot["reviewThreads"] = {
        "pageInfo": {"hasNextPage": False},
        "nodes": [
            {
                "id": "empty-human-thread",
                "isResolved": True,
                "comments": {"nodes": [], "pageInfo": {"hasNextPage": False}},
            }
        ],
    }
    report = _mapping(handoff_gate.assess(snapshot, {"review-bot"}, {"publisher"}))
    assert report["ready_to_review"] is True


@pytest.mark.parametrize(
    ("change", "blocker"),
    [
        ("failed-ci", "CI not green: tests"),
        ("pending-review", "Pending review"),
        ("missing-review", "Bot review incomplete on current head: review-bot"),
        ("draft", "PR is still draft"),
        ("pagination", "Incomplete pagination; cannot authorize handoff"),
    ],
)
def test_handoff_cli_reassesses_second_same_head_snapshot(
    handoff_gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    change: str,
    blocker: str,
) -> None:
    """Same SHA is insufficient when the freshly fetched CI/review state is no longer valid."""
    first = _handoff_snapshot()
    second = copy.deepcopy(first)
    if change == "failed-ci":
        second["statusCheckRollup"] = {
            "contexts": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [
                    {
                        "__typename": "CheckRun",
                        "name": "tests",
                        "status": "COMPLETED",
                        "conclusion": "FAILURE",
                    }
                ],
            }
        }
    elif change == "pending-review":
        reviews = _mapping(second["reviews"])
        reviews["nodes"] = [
            {
                "id": "review",
                "author": {"login": "review-bot", "__typename": "Bot"},
                "state": "PENDING",
                "body": "",
                "commit": {"oid": second["headRefOid"]},
            }
        ]
        second["reviews"] = reviews
    elif change == "missing-review":
        second["reviews"] = {"nodes": [], "pageInfo": {"hasNextPage": False}}
    elif change == "draft":
        second["isDraft"] = True
    elif change == "pagination":
        second["comments"] = {"nodes": [], "pageInfo": {"hasNextPage": True}}
    else:
        raise AssertionError(change)
    responses = iter([first, second])
    calls: list[tuple[str, int]] = []

    def fetch(repo: str, number: int) -> dict[str, object]:
        calls.append((repo, number))
        return next(responses)

    monkeypatch.setattr(handoff_gate, "fetch", fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gate",
            "--repo",
            "example/example",
            "--pr",
            "1",
            "--reviewer",
            "review-bot",
            "--handler",
            "publisher",
        ],
    )
    assert handoff_gate.main() == 1
    report = _mapping(json.loads(capsys.readouterr().out))
    assert report["ready_to_review"] is False
    assert report["head"] == first["headRefOid"]
    assert blocker in _list(report["blockers"])
    assert "PR state changed during audit" in _list(report["blockers"])
    assert calls == [("example/example", 1), ("example/example", 1)]


@pytest.mark.parametrize("mode", ["stable-green", "head-change", "becomes-green"])
def test_handoff_cli_requires_stable_ready_assessment(
    handoff_gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    """Stable success remains valid; head changes or newly green unstable state still refuse."""
    first = _handoff_snapshot()
    second = copy.deepcopy(first)
    if mode == "head-change":
        second["headRefOid"] = "b" * 40
    elif mode == "becomes-green":
        first["isDraft"] = True
    responses = iter([first, second])
    calls: list[tuple[str, int]] = []

    def fetch(repo: str, number: int) -> dict[str, object]:
        calls.append((repo, number))
        return next(responses)

    monkeypatch.setattr(handoff_gate, "fetch", fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gate",
            "--repo",
            "example/example",
            "--pr",
            "1",
            "--reviewer",
            "review-bot",
            "--handler",
            "publisher",
        ],
    )
    assert handoff_gate.main() == (0 if mode == "stable-green" else 1)
    report = _mapping(json.loads(capsys.readouterr().out))
    assert report["ready_to_review"] is (mode == "stable-green")
    if mode == "head-change":
        assert "Head changed during audit" in _list(report["blockers"])
    elif mode == "becomes-green":
        assert "PR state changed during audit" in _list(report["blockers"])
    else:
        assert report["blockers"] == []
    assert calls == [("example/example", 1), ("example/example", 1)]


def test_handoff_cli_sanitizes_failed_mock_fetch(
    handoff_gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Error output keeps its original exit2/schema and withholds transport details."""
    calls: list[tuple[str, int]] = []

    def fetch(repo: str, number: int) -> dict[str, object]:
        calls.append((repo, number))
        message = "withheld synthetic transport payload"
        raise ValueError(message)

    monkeypatch.setattr(handoff_gate, "fetch", fetch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gate",
            "--repo",
            "example/example",
            "--pr",
            "1",
            "--reviewer",
            "review-bot",
            "--handler",
            "publisher",
        ],
    )
    failure_exit = 2
    assert handoff_gate.main() == failure_exit
    output = capsys.readouterr().out
    assert json.loads(output) == {"ready_to_review": False, "error": "ValueError"}
    assert "withheld synthetic transport payload" not in output
    assert calls == [("example/example", 1)]
