"""Monitoring ownership contracts; no image, data path, TLS or selector migration."""

import hashlib
import json
import subprocess
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NS = "cattle-monitoring-system"
CLUSTER = {
    "ClusterRole",
    "ClusterRoleBinding",
    "CustomResourceDefinition",
    "MutatingWebhookConfiguration",
    "ValidatingWebhookConfiguration",
}
COMPONENTS = (
    "prometheus",
    "alertmanager",
    "prometheus-operator",
    "node-exporter",
    "kube-state-metrics",
)
yaml.SafeLoader.add_constructor(
    "tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node)
)
OWNERS = {
    "grafana": ("charts/grafana", "kube-prometheus-stack"),
    "loki": ("charts/loki", "loki"),
    "tempo": ("charts/tempo", "tempo"),
    "pyroscope": ("charts/pyroscope", "profiling"),
    "monitoring-k3s": ("charts/monitoring-k3s", "monitoring-k3s"),
}

OWNERS.update({name: ("charts/" + name, "kube-prometheus-stack") for name in COMPONENTS})


@cache
def render(path, release) -> list[dict[str, object]]:
    """Render a monitoring chart with helm and return its claimable documents."""
    text = subprocess.check_output(
        ["helm", "template", release, str(ROOT / path), "-n", NS, "--include-crds"],
        text=True,
    )
    docs: list[dict[str, object]] = [
        d
        for d in yaml.safe_load_all(text)
        if d and not (d["metadata"].get("annotations") or {}).get("helm.sh/hook")
    ]
    return docs


def _mapping(value: object) -> dict[str, object]:
    """Return the assert-verified mapping view of a parsed YAML value."""
    assert isinstance(value, dict)
    result: dict[str, object] = value
    return result


def _documents(value: object) -> list[dict[str, object]]:
    """Return the assert-verified list-of-documents view of a parsed YAML value."""
    assert isinstance(value, list)
    documents: list[dict[str, object]] = value
    return documents


def _mapping_path(document: dict[str, object], *keys: str) -> dict[str, object]:
    """Walk nested mappings of a parsed document and return the final mapping."""
    value: object = document
    for key in keys:
        value = _mapping(value)[key]
    return _mapping(value)


def _text(value: object) -> str:
    """Return the assert-verified string view of a parsed YAML value."""
    assert isinstance(value, str)
    return value


def key(d) -> str:
    """Return the ownership identity key of a rendered document."""
    return "/".join(
        [
            d["kind"],
            "" if d["kind"] in CLUSTER else d["metadata"].get("namespace", NS),
            d["metadata"]["name"],
        ]
    )


def digest(d) -> str:
    """Return the stable sha256 digest of a rendered document."""
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def normalized(source) -> dict[str, object]:
    """Normalize a rendered document for owner comparison."""
    d: dict[str, object] = json.loads(json.dumps(source))
    name = _mapping(d["metadata"])["name"]
    if d["kind"] == "Deployment" and name == "kube-prometheus-stack-grafana":
        _mapping_path(d, "spec", "template", "metadata", "annotations").pop("checksum/config", None)
        spec = _mapping_path(d, "spec", "template", "spec")
        for c in _documents(spec["containers"]):
            c["env"] = [
                e
                for e in _documents(c.get("env", []))
                if not _text(_mapping(e)["name"]).startswith("GF_AUTH_")
            ]
    if d["kind"] == "ConfigMap" and name == "kube-prometheus-stack-grafana":
        data = _mapping(d["data"])
        data["grafana.ini"] = _text(data["grafana.ini"]).replace(
            "[auth.anonymous]\nenabled = false", "[auth.anonymous]\nenabled = true"
        )
    if d["kind"] == "Deployment" and name in ("otel-loki", "otel-tempo"):
        spec = _mapping_path(d, "spec", "template", "spec")
        for v in _documents(spec["volumes"]):
            if v["name"] == "config":
                _mapping(v["configMap"])["name"] = "otel-backends"
    return d


def test_existing_resources_have_one_service_owner_and_preserved_payload() -> None:
    fixture = json.loads((ROOT / "tests/fixtures/monitoring-split-contract.json").read_text())
    actual = {}
    for owner, (path, release) in OWNERS.items():
        for d in render(path, release):
            k = key(d)
            assert k not in actual, "Duplicate owner: " + k
            actual[k] = (owner, d)
    for d in render("deploy/platform/grafana/public-entry", "grafana-public-entry"):
        assert key(d) not in actual
        actual[key(d)] = ("grafana", d)
    for k, expected in fixture.items():
        if expected["owner"] in ("prometheus-stack", "retired-shared-config"):
            continue
        owner, d = actual[k]
        assert owner == expected["owner"], k
        assert digest(normalized(d)) == expected.get("normalizedSha256", expected["sha256"]), k


def test_grafana_native_sso_and_no_anonymous_access_are_declarative() -> None:
    v = yaml.safe_load((ROOT / "charts/grafana/values.yaml").read_text())["grafana"]
    assert v["admin"]["existingSecret"] == "socrat-grafana-admin"
    assert v["grafana.ini"]["auth.anonymous"]["enabled"] is False
    assert v["env"]["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
    assert v["env"]["GF_AUTH_GENERIC_OAUTH_ENABLED"] == "true"
    assert v["env"]["GF_AUTH_GENERIC_OAUTH_AUTO_LOGIN"] == "true"
    assert v["env"]["GF_AUTH_GENERIC_OAUTH_ROLE_ATTRIBUTE_STRICT"] == "true"
    assert v["env"]["GF_AUTH_OAUTH_ALLOW_INSECURE_EMAIL_LOOKUP"] == "false"
    assert "GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET" not in v["env"]
    assert v["grafana.ini"]["auth.generic_oauth"]["client_secret"] == (
        "$__file{/etc/grafana/secrets/authentik/client-secret}"
    )
    mount = v["extraSecretMounts"][0]
    assert mount["secretName"] == "socrat-authentik-grafana"
    assert mount["mountPath"] == "/etc/grafana/secrets/authentik"
    assert mount["items"] == [{"key": "client-secret", "path": "client-secret"}]
    assert "GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET" not in v.get("envValueFrom", {})
    docs = render("charts/grafana", "kube-prometheus-stack")
    deployment = next(
        d
        for d in docs
        if d["kind"] == "Deployment" and d["metadata"]["name"] == "kube-prometheus-stack-grafana"
    )
    spec = _mapping_path(deployment, "spec", "template", "spec")
    volumes = {item["name"]: item for item in _documents(spec["volumes"])}
    assert (
        _mapping(volumes["authentik-oauth-secret"]["secret"])["secretName"]
        == "socrat-authentik-grafana"
    )
    grafana_config = next(
        d
        for d in docs
        if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "kube-prometheus-stack-grafana"
    )
    assert (
        "client_secret = $__file{/etc/grafana/secrets/authentik/client-secret}"
        in _mapping(grafana_config["data"])["grafana.ini"]
    )
    assert v["deploymentStrategy"]["type"] == "Recreate"
    assert v["nodeSelector"] == {"kubernetes.io/hostname": "socrat-5"}
    dependency = yaml.safe_load((ROOT / "charts/grafana/charts/grafana/Chart.yaml").read_text())
    assert dependency["version"] == "14.5.0"


def test_each_backend_owns_its_config_without_changing_config_bytes() -> None:
    for name in ("loki", "tempo"):
        docs = render("charts/" + name, name)
        config = next(d for d in docs if d["kind"] == "ConfigMap")
        assert _mapping(config["metadata"])["name"] == "otel-" + name + "-config"
        assert (
            _text(_mapping(config["data"])[name + ".yaml"])
            == (ROOT / f"deploy/monitoring/otel/{name}.yaml").read_text()
        )
        dep = next(d for d in docs if d["kind"] == "Deployment")
        spec = _mapping_path(dep, "spec", "template", "spec")
        volumes = {v["name"]: v for v in _documents(spec["volumes"])}
        assert (
            _mapping(volumes["config"]["configMap"])["name"] == _mapping(config["metadata"])["name"]
        )
        assert _mapping(volumes["tls"]["secret"])["secretName"] == "otel-tls-backends"
        assert (
            _mapping(volumes["data"]["hostPath"])["path"] == "/var/lib/private/homelab-otel-" + name
        )
        assert not any(d["kind"] in ("Certificate", "Secret") for d in docs)


def test_prometheus_components_preserve_release_names_and_matching_labels() -> None:
    for name in COMPONENTS:
        a = yaml.safe_load((ROOT / f"deploy/argocd/apps/{name}.yaml").read_text())
        source = a["spec"]["source"]
        assert source["path"] == "charts/" + name
        assert source["helm"]["releaseName"] == "kube-prometheus-stack"
        assert source["helm"]["parameters"] == []
    v = yaml.safe_load((ROOT / "charts/prometheus/values.yaml").read_text())[
        "kube-prometheus-stack"
    ]
    assert v["grafana"] == {"enabled": False}
    assert v["alertmanager"]["enabled"] is False
    assert (
        v["prometheus"]["prometheusSpec"]["ruleSelector"]["matchLabels"]["release"]
        == "kube-prometheus-stack"
    )
    assert (
        v["prometheus"]["prometheusSpec"]["alertingEndpoints"][0]["name"]
        == "kube-prometheus-stack-alertmanager"
    )


def test_retired_aggregate_owners_and_charts_are_not_reintroduced() -> None:
    for name in (
        "kube-prometheus-stack",
        "prometheus-stack",
        "otel-backends",
        "profiling",
    ):
        assert not (ROOT / f"deploy/argocd/apps/{name}.yaml").exists()
    for name in ("otel-backends", "profiling"):
        assert not (ROOT / f"charts/{name}").exists()
    assert not (ROOT / "deploy/platform/kube-prometheus-stack").exists()
    for name in ("grafana", "loki", "tempo", "pyroscope", *COMPONENTS):
        app = yaml.safe_load((ROOT / f"deploy/argocd/apps/{name}.yaml").read_text())
        assert app["spec"]["syncPolicy"]["automated"].get("enabled") is not False
        assert app["spec"]["syncPolicy"]["automated"]["prune"] is False
        assert app["spec"]["syncPolicy"]["automated"]["selfHeal"] is True


def test_legacy_monitoring_installer_fails_before_roles_under_gitops() -> None:
    play = yaml.safe_load((ROOT / "ansible/playbooks/monitoring.yml").read_text())[1]
    guard = play["pre_tasks"][0]
    assert guard["ansible.builtin.include_role"] == {
        "name": "monitoring_stack",
        "tasks_from": "gitops-guard.yml",
    }
    assert guard["tags"] == ["always"]
    tasks = yaml.safe_load((ROOT / "ansible/roles/monitoring_stack/tasks/main.yml").read_text())
    assert tasks[0]["ansible.builtin.import_tasks"] == "gitops-guard.yml"
    checks = yaml.safe_load(
        (ROOT / "ansible/roles/monitoring_stack/tasks/gitops-guard.yml").read_text()
    )
    assert len(checks) == 1
    assert "ansible.builtin.fail" in checks[0]
    assert "prometheus" in checks[0]["ansible.builtin.fail"]["msg"]
    assert "alertmanager" in checks[0]["ansible.builtin.fail"]["msg"]
    assert checks[0]["tags"] == ["always"]


def test_existing_rancher_postdelete_finalizers_are_declared_not_ignored() -> None:
    app = yaml.safe_load((ROOT / "deploy/argocd/apps/rancher.yaml").read_text())
    assert app["metadata"]["finalizers"] == [
        "resources-finalizer.argocd.argoproj.io",
        "post-delete-finalizer.argocd.argoproj.io",
        "post-delete-finalizer.argocd.argoproj.io/cleanup",
    ]
