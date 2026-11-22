"""Render local Argo contracts with consumed values; never contact Kubernetes or Helm repos."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NotRequired, TypedDict, cast

import yaml
from common import ROOT, command, digest, failure, finding, report, tracked


class ManifestLoader(yaml.SafeLoader):
    """YAML loader that preserves mapping key order."""

    def construct_mapping(self, node, deep=False):
        """Reject duplicate mapping keys while loading YAML manifests."""
        seen = set()
        for key, _value in node.value:
            if key.tag == "tag:yaml.org,2002:merge":
                continue
            name = self.construct_object(key, deep=deep)
            if name in seen:
                raise yaml.YAMLError("Duplicate rendered YAML key")
            seen.add(name)
        return super().construct_mapping(node, deep=deep)


ManifestLoader.add_constructor("tag:yaml.org,2002:value", ManifestLoader.construct_scalar)

KUBE_VERSION = "1.36.0"
API_VERSIONS = [
    "monitoring.coreos.com/v1",
    "cert-manager.io/v1",
    "argoproj.io/v1alpha1",
    "traefik.io/v1alpha1",
]


def local_path(value):
    """Execute local_path."""
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT) or not path.exists():
        raise ValueError("Missing or escaping chart/value path")
    return path


class HelmParameter(TypedDict, total=False):
    """Name/value pair Helm passes through `--set-string` or `--set`."""

    name: str
    value: str
    forceString: bool


class HelmOverrides(TypedDict, total=False):
    """Helm value overrides the offline renderer explicitly supports."""

    valuesObject: dict[str, object]
    releaseName: str
    valueFiles: list[str]
    parameters: list[HelmParameter]


class ValueRef(TypedDict, total=False):
    """Value reference pinned by an Argocd Application source."""

    targetRevision: str


class ObjectMeta(TypedDict, total=False):
    """Metadata fields used for rendered-object identity."""

    namespace: str
    name: str


class RenderedObject(TypedDict):
    """Mandatory keys of every rendered Kubernetes object."""

    apiVersion: str
    kind: str
    metadata: dict[str, object]


class RenderTarget(TypedDict):
    """One chart render target consumed by the quality renderer."""

    id: str
    source: str
    inline_values: NotRequired[dict[str, object]]
    chart: Path
    namespace: str
    release: str
    values: list[Path]
    parameters: list[HelmParameter]


def resolve_values(
    helm: HelmOverrides, chart: Path, refs: dict[str, ValueRef]
) -> list[Path]:
    """Resolve a Helm valueFiles list to local paths, rejecting foreign references."""
    relative = chart.relative_to(ROOT)
    values = []
    for value in helm.get("valueFiles", []):
        if value.startswith("$"):
            ref, subpath = value[1:].split("/", 1)
            if ref not in refs or refs[ref].get("targetRevision") != "main":
                raise ValueError("Unsupported value reference")
            values.append(local_path(subpath))
        else:
            values.append(local_path(str(relative / value)))
    return values


def argocd_targets() -> tuple[list[RenderTarget], set[str]]:
    """Build render targets from the Argocd Application manifests."""
    result: list[RenderTarget] = []
    consumed = set()
    for path in sorted((ROOT / "deploy/argocd/apps").glob("*.yaml")):
        app = yaml.safe_load(path.read_text())
        spec = app["spec"]
        sources = spec.get("sources", [spec.get("source", {})])
        refs = {s["ref"]: s for s in sources if "ref" in s}
        for index, source in enumerate(sources):
            if not source.get("path"):
                continue  # A registered external chart is not downloaded by offline CI.
            chart = local_path(source["path"])
            if not (chart / "Chart.yaml").is_file():
                continue  # Plain-manifest Application, checked by source/ownership contracts.
            consumed.add(str(chart.relative_to(ROOT)))
            helm = source.get("helm", {})
            if set(helm) - {"releaseName", "valueFiles", "parameters", "valuesObject"}:
                raise ValueError("Unsupported Helm override: extend the renderer explicitly")
            if not isinstance(helm.get("valuesObject", {}), dict):
                raise ValueError("Helm valuesObject must be a mapping")
            result.append(
                {
                    "id": app["metadata"]["name"] + f"-{index}",
                    "source": path.relative_to(ROOT).as_posix(),
                    "chart": chart,
                    "namespace": spec["destination"].get("namespace", "default"),
                    "release": helm.get("releaseName", app["metadata"]["name"]),
                    "inline_values": helm.get("valuesObject", {}),
                    "values": resolve_values(helm, chart, refs),
                    "parameters": helm.get("parameters", []),
                }
            )
    return result, consumed


def default_targets(result: list[RenderTarget], consumed: set[str]) -> list[RenderTarget]:
    """Add render targets with chart defaults for every unconsumed root Chart.yaml."""
    for name in tracked():
        if Path(name).name != "Chart.yaml":
            continue
        chart = ROOT / Path(name).parent
        if str(chart.relative_to(ROOT)) not in consumed:
            result.append(
                {
                    "id": "defaults-" + str(chart.relative_to(ROOT)).replace("/", "-"),
                    "source": name,
                    "chart": chart,
                    "namespace": "default",
                    "release": "quality-check",
                    "values": [],
                    "parameters": [],
                }
            )
    return result


def targets():
    """Execute targets."""
    result, consumed = argocd_targets()
    # Include every unconsumed root, including vendored charts, with chart defaults.
    result = default_targets(result, consumed)
    return sorted(result, key=lambda target: target["id"])


def arguments(target):
    """Execute arguments."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,52}", target["release"]):
        raise ValueError("Invalid Helm release name")
    args = ["--kube-version", KUBE_VERSION, "--namespace", target["namespace"]]
    for value in target["values"]:
        args += ["--values", str(value)]
    if target.get("inline_values"):
        args += ["--values", "-"]
    for parameter in target["parameters"]:
        if set(parameter) - {"name", "value", "forceString"}:
            raise ValueError("Unsupported Helm parameter")
        if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.\[\]\\/-]*", parameter["name"]):
            raise ValueError("Unsafe Helm parameter name")
        flag = "--set-string" if parameter.get("forceString") else "--set"
        args += [flag + "=" + parameter["name"] + "=" + str(parameter["value"])]
    return args


def render(target):
    """Execute render."""
    args = [
        "helm",
        "template",
        target["release"],
        str(target["chart"]),
        "--include-crds",
        *arguments(target),
    ]
    for version in API_VERSIONS:
        args += ["--api-versions", version]
    process = command(
        args, stdin=json.dumps(target.get("inline_values", {})), allowed=(0, 1), timeout=180
    )
    if process.returncode:
        return None
    try:
        return [item for item in yaml.load_all(process.stdout, Loader=ManifestLoader) if item]
    except yaml.YAMLError:
        return None  # Invalid rendered YAML is a quality failure, not a successful empty render.


def schema_name(resource):
    """Execute schema_name."""
    api = resource["apiVersion"].split("/")
    version = (api[0].split(".")[0] + "-" + api[1]) if len(api) == 2 else api[0]
    return resource["kind"].lower() + "-" + version + ".json"


def policies(resource):
    """Execute policies."""
    # Generic Kubernetes best practices belong to kube-linter, not a parallel implementation.
    # These are additional Homelab ownership/data/image contracts.
    kind = resource.get("kind")
    spec = resource.get("spec", {})
    pod = None
    if kind in {"Deployment", "DaemonSet", "StatefulSet", "Job", "ReplicaSet"}:
        pod = spec.get("template", {}).get("spec", {})
    elif kind == "CronJob":
        pod = spec.get("jobTemplate", {}).get("spec", {}).get("template", {}).get("spec", {})
    elif kind == "Pod":
        pod = spec
    errors = []
    if pod is not None:
        for container in pod.get("containers", []) + pod.get("initContainers", []):
            if not re.fullmatch(r".+@sha256:[0-9a-f]{64}", container.get("image", "")):
                errors.append(
                    (
                        "image-digest",
                        container["name"] + ": immutable image digest is missing",
                    )
                )
    if kind == "ClusterRoleBinding" and resource.get("roleRef", {}).get("name") == "cluster-admin":
        errors.append(
            (
                "cluster-admin-binding",
                "Cluster admin requires an explicit owner-reviewed exception",
            )
        )
    if kind == "PersistentVolume" and spec.get("persistentVolumeReclaimPolicy") != "Retain":
        errors.append(("pv-retain", "Persistent data volume does not explicitly retain data"))
    return errors


def authentik_accounts():
    """Use the same namespace-scoped account documents applied by the Ansible role."""
    path = ROOT / "deploy/authentik/foundation.yaml"
    return [
        doc for doc in yaml.load_all(path.read_text(), Loader=ManifestLoader)
        if doc and doc["kind"] == "ServiceAccount"
    ]


def kube_lint(target, resources, peers=()):
    """Execute kube_lint."""
    def key(doc):
        meta = doc["metadata"]
        return doc["kind"], meta.get("namespace", ""), meta["name"]

    peer_keys = {key(doc) for doc in peers}
    if peer_keys.intersection(map(key, resources)):
        raise ValueError("Ambiguous cross-release lint resource")
    data = command(
        [
            "kube-linter",
            "lint",
            "-",
            "--format",
            "json",
            "--config",
            "quality/kube-linter.yaml",
        ],
        stdin=yaml.safe_dump_all([*resources, *peers]),
        allowed=(0, 1),
    )
    value = json.loads(data.stdout)
    if value.get("Reports") is None and data.returncode == 0 and "Summary" in value:
        value["Reports"] = []
    if not isinstance(value.get("Reports"), list):
        raise ValueError("Invalid kube-linter report")
    if data.returncode and not value["Reports"]:
        raise RuntimeError("kube-linter failed without findings")
    result = []
    for item in value["Reports"]:
        obj = item["Object"]["K8sObject"]
        # Peers are checked and attributed in full by their own release.
        if (obj["GroupVersionKind"]["Kind"], obj.get("Namespace", ""), obj["Name"]) in peer_keys:
            continue
        identity = json.dumps(obj, sort_keys=True)
        rule = "kube-linter-" + item["Check"]
        # Hash diagnostics for semantic identity, but never echo possible env/Secret values.
        context = target["id"] + identity + item["Diagnostic"]["Message"]
        result.append(
            finding(
                rule,
                target["source"],
                1,
                f"{item['Check']}: {obj['Name']} (rendered object; inspect locally)",
                context,
            )
        )
    return result


def contract_hash(target):
    """Execute contract_hash."""
    # A previously broken render is accepted ONLY while its entire source stays identical.
    parts = [target["id"], json.dumps(target["parameters"], sort_keys=True)]
    if target.get("inline_values"):
        parts.append(json.dumps(target["inline_values"], sort_keys=True))
    for path in sorted(target["chart"].rglob("*")):
        if path.is_file():
            if not path.resolve().is_relative_to(ROOT):
                raise ValueError("Chart dependency escapes repository")
            parts += [str(path.relative_to(ROOT)), digest(path.read_bytes().hex())]
    for path in target["values"]:
        parts += [str(path.relative_to(ROOT)), digest(path.read_bytes().hex())]
    return digest("\0".join(parts))


def identity_key(target: RenderTarget, resource: RenderedObject) -> str:
    """Build the semantic identity used for duplicate and schema findings."""
    return "|".join(
        str(v)
        for v in [
            target["id"],
            resource["apiVersion"],
            resource["kind"],
            resource["metadata"].get("namespace", target["namespace"]),
            resource["metadata"].get("name"),
        ]
    )


def schema_findings(
    *, target: RenderTarget, resource: RenderedObject, key: str, validate: bool
) -> list[object]:
    """Return schema availability and strict validation findings for one object."""
    findings: list[object] = []
    if not validate:
        return findings
    path = ROOT / "quality/schemas" / schema_name(resource)
    if not path.exists():
        return [
            finding(
                "schema-unavailable",
                target["source"],
                1,
                f"{resource['apiVersion']}/{resource['kind']}: no reviewed offline schema",
                key,
            )
        ]
    process = command(
        [
            "kubeconform",
            "-strict",
            "-output",
            "json",
            "-kubernetes-version",
            KUBE_VERSION,
            "-schema-location",
            str(path),
        ],
        stdin=json.dumps(resource),
        allowed=(0, 1),
    )
    if process.returncode:
        findings.append(
            finding(
                "kubernetes-schema",
                target["source"],
                1,
                f"{resource['kind']}: strict Kubernetes schema validation failed",
                key + digest(json.dumps(resource, sort_keys=True)),
            )
        )
    return findings


def policy_findings(*, target: RenderTarget, resource: RenderedObject, key: str) -> list[object]:
    """Return Homelab ownership/data/image policy findings for one object."""
    return [
        finding(rule, target["source"], 1, message, key + "|" + message)
        for rule, message in policies(resource)
    ]


def library_consumer(target: RenderTarget, selected: list[RenderTarget]) -> RenderTarget | None:
    """Require a declared, exact-version locked dependency of an inventoried application."""
    chart = target["chart"]
    meta = yaml.safe_load((chart / "Chart.yaml").read_bytes())
    if meta.get("type", "application") != "library":
        return None
    # A Helm library is not installable. Lint it directly and verify a real,
    # inventoried default install of its parent (not a generated dummy Pod).
    parent = chart.parent.parent
    consumers = [t for t in selected if t["chart"] == parent and t["id"].startswith("defaults-")]
    if chart.parent.name == "charts" and len(consumers) == 1:
        declared = yaml.safe_load((parent / "Chart.yaml").read_bytes()).get("dependencies", [])
        locked = yaml.safe_load((parent / "Chart.lock").read_bytes())["dependencies"]
        if any(dep["name"] == meta["name"] for dep in declared) and any(
            dep["name"] == meta["name"] and dep["version"] == meta["version"] for dep in locked
        ):
            return consumers[0]
    message = "Library chart lacks an inventoried, exact-version locked consumer"
    raise ValueError(message)


def check(*, validate=True):
    """Execute check."""
    selected = targets()
    if not selected:
        raise ValueError("No local chart targets")
    findings = []
    inventory = []
    renders = {}
    for target in selected:
        source = target["source"]
        lint = command(
            ["helm", "lint", str(target["chart"]), *arguments(target)],
            stdin=json.dumps(target.get("inline_values", {})),
            allowed=(0, 1),
            timeout=180,
        )
        consumer = library_consumer(target, selected)
        effective = consumer or target
        if effective["id"] not in renders:
            renders[effective["id"]] = render(effective)
        resources = renders[effective["id"]]
        if lint.returncode or resources is None or (consumer and not resources):
            findings.append(
                finding(
                    "helm-lint-render",
                    source,
                    1,
                    target["id"]
                    + ": lint/render failed; inspect locally without publishing Secret values.",
                    target["id"] + contract_hash(target),
                )
            )
        if resources is None or consumer:
            # Each real parent's complete cached render goes through the normal
            # schema, identity, policy and kube-linter checks under its own ID.
            continue
        peers = []
        if target["id"] == "monitoring-k3s-0":
            # The health Service selects the separately managed Grafana MCP Deployment.
            peer = next(t for t in selected if t["id"] == "grafana-mcp-0")
            if peer["id"] not in renders:
                renders[peer["id"]] = render(peer)
            peers = [doc for doc in renders[peer["id"]] or [] if doc["kind"] == "Deployment"]
        if target["id"] == "authentik-0":
            peers = authentik_accounts()
            # Do not discard the foundation accounts' own lint diagnostics.
            foundation = {"id": "authentik-foundation", "source": "deploy/authentik/foundation.yaml"}
            findings.extend(kube_lint(foundation, peers) if peers else [])
        findings.extend(kube_lint(target, resources, peers))
        seen = set()
        for resource in resources:
            if (
                not isinstance(resource, dict)
                or not {"apiVersion", "kind", "metadata"} <= resource.keys()
            ):
                raise ValueError("Rendered output is not a Kubernetes object")
            resource = cast("RenderedObject", resource)
            key = identity_key(target=target, resource=resource)
            if key in seen:
                findings.append(
                    finding(
                        "duplicate-object",
                        source,
                        1,
                        "Duplicate rendered object identity",
                        key,
                    )
                )
            seen.add(key)
            inventory.append(schema_name(resource))
            findings.extend(
                schema_findings(
                    target=target, resource=resource, key=key, validate=validate
                )
            )
            findings.extend(policy_findings(target=target, resource=resource, key=key))
    return findings, len(selected), sorted(set(inventory))


def main():
    """Execute main."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema-inventory", action="store_true")
    args = parser.parse_args()
    output = ROOT / "reports/manifests.json"
    try:
        findings, count, inventory = check(validate=not args.schema_inventory)
        if args.schema_inventory:
            print(json.dumps(inventory))
            return 0
        return report("manifests", findings, count, output)
    except (OSError, RuntimeError, TypeError, ValueError, yaml.YAMLError) as error:
        failure(output, error)
        print(
            f"charts: {type(error).__name__}; no fallback or live access",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
