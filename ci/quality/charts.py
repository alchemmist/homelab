"""Render local Argo contracts with consumed values; never contact Kubernetes or Helm repos."""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast, override

if TYPE_CHECKING:
    from collections.abc import Hashable, Iterable, Mapping

import yaml

from ci.quality.closed_root_backend import Obj, entries, plain, view
from ci.quality.common import (
    ROOT,
    Finding,
    command,
    digest,
    failure,
    finding,
    report,
    tracked,
)


class ManifestLoader(yaml.SafeLoader):
    """YAML loader that preserves mapping key order."""

    @override
    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool | None = None
    ) -> dict[Hashable, object]:
        """Reject duplicate mapping keys while loading YAML manifests."""
        merge_depth = bool(deep)
        seen: set[Hashable] = set()
        for key, _value in node.value:
            if key.tag == "tag:yaml.org,2002:merge":
                continue
            name = self.construct_object(key, deep=merge_depth)
            if name in seen:
                msg = "Duplicate rendered YAML key"
                raise yaml.YAMLError(msg)
            seen.add(name)
        return cast("dict[Hashable, object]", super().construct_mapping(node, deep=merge_depth))


def _construct_value_scalar(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> object:
    """Read a YAML `value`-tagged scalar node as its plain text (typically "=")."""
    return loader.construct_scalar(node)


# The value scalar ("=") is registered on the safe loader this class extends,
# so every manifest loader inherits the same reviewed behavior.
yaml.SafeLoader.add_constructor("tag:yaml.org,2002:value", _construct_value_scalar)

KUBE_VERSION = "1.36.0"
API_VERSIONS = [
    "monitoring.coreos.com/v1",
    "cert-manager.io/v1",
    "argoproj.io/v1alpha1",
    "traefik.io/v1alpha1",
]


def local_path(value: str) -> Path:
    """Resolve a value path inside the repository, rejecting escapes and misses."""
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT) or not path.exists():
        msg = "Missing or escaping chart/value path"
        raise ValueError(msg)
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


def resolve_values(helm: HelmOverrides, chart: Path, refs: dict[str, ValueRef]) -> list[Path]:
    """Resolve a Helm valueFiles list to local paths, rejecting foreign references."""
    relative = chart.relative_to(ROOT)
    values: list[Path] = []
    for value in helm.get("valueFiles", []):
        if value.startswith("$"):
            ref, subpath = value[1:].split("/", 1)
            if ref not in refs or refs[ref].get("targetRevision") != "main":
                msg = "Unsupported value reference"
                raise ValueError(msg)
            values.append(local_path(subpath))
        else:
            values.append(local_path(str(relative / value)))
    return values


def argocd_targets() -> tuple[list[RenderTarget], set[str]]:
    """Build render targets from the Argocd Application manifests."""
    result: list[RenderTarget] = []
    consumed: set[str] = set()
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
                msg = "Unsupported Helm override: extend the renderer explicitly"
                raise ValueError(msg)
            if not isinstance(helm.get("valuesObject", {}), dict):
                msg = "Helm valuesObject must be a mapping"
                raise TypeError(msg)
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


def targets() -> list[RenderTarget]:
    """Collect every offline render target, Argocd applications plus chart defaults."""
    result, consumed = argocd_targets()
    # Include every unconsumed root, including vendored charts, with chart defaults.
    result = default_targets(result, consumed)
    return sorted(result, key=lambda target: target["id"])


def arguments(target: Mapping[str, object]) -> list[str]:
    """Build the offline-hermetic helm argument vector for one render target."""
    release = plain(target["release"])
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,52}", release):
        msg = "Invalid Helm release name"
        raise ValueError(msg)
    args = ["--kube-version", KUBE_VERSION, "--namespace", plain(target["namespace"])]
    for value in entries(target["values"]):
        args += ["--values", str(value)]
    if view(target.get("inline_values", {})):
        args += ["--values", "-"]
    for parameter in entries(target["parameters"]):
        item = view(parameter)
        if set(item) - {"name", "value", "forceString"}:
            msg = "Unsupported Helm parameter"
            raise ValueError(msg)
        parameter_name = plain(item["name"])
        if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.\[\]\/-]*", parameter_name):
            msg = "Unsafe Helm parameter name"
            raise ValueError(msg)
        flag = "--set-string" if item.get("forceString") else "--set"
        args += [flag + "=" + parameter_name + "=" + str(item["value"])]
    return args


def render(target: RenderTarget) -> list[dict[str, object]] | None:
    """Render one target offline with the pinned helm and checked local loader."""
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


API_SEGMENT_COUNT = 2


def schema_name(resource: Mapping[str, object]) -> str:
    """Map a rendered object to its reviewed offline schema file name."""
    api = plain(resource["apiVersion"]).split("/")
    version = api[0].split(".")[0] + "-" + api[1] if len(api) == API_SEGMENT_COUNT else api[0]
    return plain(resource["kind"]).lower() + "-" + version + ".json"


def policies(resource: Mapping[str, object]) -> list[tuple[str, str]]:
    """Apply the Homelab ownership/data/image contracts to one rendered object."""
    # Generic Kubernetes best practices belong to kube-linter, not a parallel implementation.
    # These are additional Homelab ownership/data/image contracts.
    kind = str(resource.get("kind"))
    spec = view(resource.get("spec", {}))
    pod: Obj | None = None
    if kind in {"Deployment", "DaemonSet", "StatefulSet", "Job", "ReplicaSet"}:
        pod = view(view(spec.get("template", {})).get("spec", {}))
    elif kind == "CronJob":
        job = view(view(spec.get("jobTemplate", {})).get("spec", {}))
        pod = view(view(view(job.get("template", {})).get("spec", {})))
    elif kind == "Pod":
        pod = spec
    errors: list[tuple[str, str]] = []
    if pod is not None:
        for container in itertools.chain(
            entries(pod.get("containers", [])), entries(pod.get("initContainers", []))
        ):
            item = view(container)
            if not re.fullmatch(r".+@sha256:[0-9a-f]{64}", str(item.get("image", ""))):
                errors.append(
                    (
                        "image-digest",
                        plain(item["name"]) + ": immutable image digest is missing",
                    )
                )
    if kind == "ClusterRoleBinding" and view(resource.get("roleRef", {})).get("name") == (
        "cluster-admin"
    ):
        errors.append(
            (
                "cluster-admin-binding",
                "Cluster admin requires an explicit owner-reviewed exception",
            )
        )
    if kind == "PersistentVolume" and spec.get("persistentVolumeReclaimPolicy") != "Retain":
        errors.append(("pv-retain", "Persistent data volume does not explicitly retain data"))
    return errors


RELEASE_PEERS = {
    "monitoring-k3s-0": ("grafana-mcp-0", "Deployment", "grafana-mcp"),
    "litellm-2": ("litellm-0", "Service", "litellm"),
    "rustfs-0": ("authentik-0", "Service", "authentik-server"),
}


def authentik_accounts() -> list[dict[str, object]]:
    """Use the same namespace-scoped account documents applied by the Ansible role."""
    path = ROOT / "deploy/authentik/foundation.yaml"
    return [
        doc
        for doc in yaml.load_all(path.read_text(), Loader=ManifestLoader)
        if doc and doc["kind"] == "ServiceAccount"
    ]


def kube_lint(
    target: Mapping[str, object],
    resources: Iterable[dict[str, object]],
    peers: Iterable[dict[str, object]] = (),
) -> list[Finding]:
    """Run kube-linter for one target, attributing findings only to checked objects."""

    def key(doc: dict[str, object]) -> tuple[object, object, object]:
        meta = view(doc["metadata"])
        return doc["kind"], meta.get("namespace", ""), meta["name"]

    peer_keys = {key(doc) for doc in peers}
    if peer_keys.intersection(key(doc) for doc in resources):
        msg = "Ambiguous cross-release lint resource"
        raise ValueError(msg)
    data = command(
        [
            "kube-linter",
            "lint",
            "-",
            "--format",
            "json",
            "--config",
            "ci/quality/kube-linter.yaml",
        ],
        stdin=yaml.safe_dump_all([*resources, *peers]),
        allowed=(0, 1),
    )
    value = view(json.loads(data.stdout))
    if value.get("Reports") is None and data.returncode == 0 and "Summary" in value:
        value["Reports"] = []
    reports = value["Reports"]
    if not isinstance(reports, list):
        msg = "Invalid kube-linter report"
        raise TypeError(msg)
    if data.returncode and not reports:
        msg = "kube-linter failed without findings"
        raise RuntimeError(msg)
    result: list[Finding] = []
    for item in reports:
        entry = view(item)
        obj = view(view(entry["Object"])["K8sObject"])
        # Peers are checked and attributed in full by their own release.
        gvk = view(view(obj["GroupVersionKind"]))
        identity_key = (gvk["Kind"], obj.get("Namespace", ""), obj["Name"])
        if identity_key in peer_keys:
            continue
        identity = json.dumps(obj, sort_keys=True)
        rule = "kube-linter-" + plain(entry["Check"])
        # Hash diagnostics for semantic identity, but never echo possible env/Secret values.
        context = plain(target["id"]) + identity + plain(view(entry["Diagnostic"])["Message"])
        threatening = (
            plain(entry["Check"])
            + ": "
            + plain(obj["Name"])
            + " (rendered object; inspect locally)"
        )
        result.append(finding(rule, plain(target["source"]), 1, threatening, context))
    return result


def contract_hash(target: RenderTarget) -> str:
    """Hash a target's complete source, values and parameters for replay identity."""
    # A previously broken render is accepted ONLY while its entire source stays identical.
    parts = [target["id"], json.dumps(target["parameters"], sort_keys=True)]
    if target.get("inline_values"):
        parts.append(json.dumps(target["inline_values"], sort_keys=True))
    for path in sorted(target["chart"].rglob("*")):
        if path.is_file():
            if not path.resolve().is_relative_to(ROOT):
                msg = "Chart dependency escapes repository"
                raise ValueError(msg)
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
) -> list[Finding]:
    """Return schema availability and strict validation findings for one object."""
    findings: list[Finding] = []
    if not validate:
        return findings
    path = ROOT / "ci/quality/schemas" / schema_name(resource)
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


def policy_findings(*, target: RenderTarget, resource: RenderedObject, key: str) -> list[Finding]:
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


def context_peers(
    target: RenderTarget,
    selected: list[RenderTarget],
    renders: dict[str, list[dict[str, object]] | None],
) -> list[dict[str, object]]:
    """Collect the provider objects a consumer must see without owning their findings."""
    # These consumers reference objects rendered by a different Helm source.
    # Only the actual provider object is context; it still has its own gate.
    peers: list[dict[str, object]] = []
    link = RELEASE_PEERS.get(target["id"])
    if link:
        peer_id, kind, name = link
        peer = next(t for t in selected if t["id"] == peer_id)
        if peer_id not in renders:
            renders[peer_id] = render(peer)
        rendered = renders[peer_id]
        peers = [
            doc
            for doc in rendered or []
            if doc["kind"] == kind and plain(view(doc["metadata"])["name"]) == name
        ]
    return peers


def object_findings(
    *,
    target: RenderTarget,
    resources: Iterable[object],
    validate: bool,
) -> tuple[list[Finding], list[str]]:
    """Validate every rendered object for schema, identity and Homelab policy."""
    findings: list[Finding] = []
    inventory: list[str] = []
    seen: set[str] = set()
    for resource in resources:
        if (
            not isinstance(resource, dict)
            or not {"apiVersion", "kind", "metadata"} <= resource.keys()
        ):
            msg = "Rendered output is not a Kubernetes object"
            raise ValueError(msg)
        rendered = cast("RenderedObject", resource)
        key = identity_key(target=target, resource=rendered)
        if key in seen:
            findings.append(
                finding(
                    "duplicate-object",
                    target["source"],
                    1,
                    "Duplicate rendered object identity",
                    key,
                )
            )
        seen.add(key)
        inventory.append(schema_name(resource))
        findings.extend(
            schema_findings(target=target, resource=rendered, key=key, validate=validate)
        )
        findings.extend(policy_findings(target=target, resource=rendered, key=key))
    return findings, inventory


def check(*, validate: bool = True) -> tuple[list[Finding], int, list[str]]:
    """Render every offline target and check it fully for schema and policy drift."""
    selected = targets()
    if not selected:
        msg = "No local chart targets"
        raise ValueError(msg)
    findings: list[Finding] = []
    inventory: list[str] = []
    renders: dict[str, list[dict[str, object]] | None] = {}
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
        peers = context_peers(target, selected, renders)
        if target["id"] == "authentik-0":
            peers = authentik_accounts()
            # Do not discard the foundation accounts' own lint diagnostics.
            foundation: dict[str, object] = {
                "id": "authentik-foundation",
                "source": "deploy/authentik/foundation.yaml",
            }
            findings.extend(kube_lint(foundation, peers) if peers else [])
        findings.extend(kube_lint(target, resources, peers))
        object_findings_results = object_findings(
            target=target, resources=resources, validate=validate
        )
        findings.extend(object_findings_results[0])
        inventory.extend(object_findings_results[1])
    return findings, len(selected), sorted(set(inventory))


def main() -> int:
    """Render and check every offline chart target, writing the manifests report."""
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
