"""Render local Argo contracts with consumed values; never contact Kubernetes or Helm repos."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NotRequired, TypedDict, cast

import yaml

from ci.quality.common import ROOT, command, digest, failure, finding, report, tracked


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
                msg = "Duplicate rendered YAML key"
                raise yaml.YAMLError(msg)
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
    values = []
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
                msg = "Unsupported Helm override: extend the renderer explicitly"
                raise ValueError(msg)
            if not isinstance(helm.get("valuesObject", {}), dict):
                msg = "Helm valuesObject must be a mapping"
                raise ValueError(msg)
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
                    "namespace": "quality-check",
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
        msg = "Invalid Helm release name"
        raise ValueError(msg)
    args = ["--kube-version", KUBE_VERSION, "--namespace", target["namespace"]]
    for value in target["values"]:
        args += ["--values", str(value)]
    if target.get("inline_values"):
        args += ["--values", "-"]
    for parameter in target["parameters"]:
        if set(parameter) - {"name", "value", "forceString"}:
            msg = "Unsupported Helm parameter"
            raise ValueError(msg)
        if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.\[\]\\/-]*", parameter["name"]):
            msg = "Unsafe Helm parameter name"
            raise ValueError(msg)
        flag = "--set-string" if parameter.get("forceString") else "--set"
        args += [flag + "=" + parameter["name"] + "=" + str(parameter["value"])]
    return args


MANIFEST_CLUSTER_SCOPED_KINDS = frozenset(
    {
        "ClusterRoleBinding",
        "ClusterRole",
        "CustomResourceDefinition",
        "GlobalRole",
        "MutatingWebhookConfiguration",
        "Namespace",
        "PriorityClass",
        "RoleTemplate",
        "ClusterRoleTemplateBinding",
        "StorageClass",
        "ValidatingWebhookConfiguration",
    }
)


def apply_release_namespace(target, docs):
    """Model Helm's install-time namespace assignment for offline lint.

    `helm template` leaves `metadata.namespace` unset whenever a chart relies on
    `.Release.Namespace`; at install time (and in GitOps reconciliation) those
    objects are created in the release namespace. Filling the same namespace
    before kube-linter lets cross-object checks (use-namespace,
    dangling-service, env-value-from) evaluate the real adjacency instead of
    comparing objects that appear namespace-less to objects with explicit
    namespaces. Cluster-scoped kinds keep no namespace, and an explicitly
    set namespace is never overwritten.
    """
    for doc in docs:
        if (
            isinstance(doc, dict)
            and doc.get("kind") not in MANIFEST_CLUSTER_SCOPED_KINDS
            and isinstance(doc.get("metadata"), dict)
            and not doc["metadata"].get("namespace")
        ):
            doc["metadata"]["namespace"] = target["namespace"]
    return docs


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
        docs = [doc for doc in yaml.load_all(process.stdout, Loader=ManifestLoader) if doc]
    except yaml.YAMLError:
        # Invalid rendered YAML is a quality failure, not a successful empty render.
        return None
    return apply_release_namespace(target, docs)


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


RELEASE_PEERS = {
    "monitoring-k3s-0": ("grafana-mcp-0", [("Deployment", "grafana-mcp")]),
    "litellm-2": ("litellm-0", [("Service", "litellm"), ("Deployment", "litellm")]),
    "rustfs-0": ("authentik-0", [("Service", "authentik-server"), ("Deployment", "authentik-server")]),
}


FOUNDATION_STUB = {
    "id": "authentik-foundation",
    "source": "deploy/authentik/foundation.yaml",
}


def authentik_accounts():
    """Use the same namespace-scoped account documents applied by the Ansible role."""
    path = ROOT / "deploy/authentik/foundation.yaml"
    return [
        doc
        for doc in yaml.load_all(path.read_text(), Loader=ManifestLoader)
        if doc and doc["kind"] == "ServiceAccount"
    ]


# A one-shot Job pod never serves traffic through a Service and its lifecycle is
# completion based: readiness does not gate endpoints and liveness resumption is
# the controller's restart responsibility, not a probe decision. Probing a
# completion-based workload with an invented endpoint would be a placeholder
# probe, so its absence is not a defect. Every other probe check (a declared
# probe with a wrong port, an unreadily declared field, serving kinds without
# probes) keeps its full meaning for these kinds and all others.
ONE_SHOT_KINDS = frozenset({"Job", "CronJob"})
ONE_SHOT_EXEMPT_CHECKS = frozenset({"no-liveness-probe", "no-readiness-probe"})

# A pod with hostNetwork: true sends its traffic through the node network
# stack, outside the per-pod CNI datapath. Cluster NetworkPolicies cannot
# isolate that traffic (CNI policy applies to the pod's virtual interface, so
# any policy "selecting" a hostNetwork pod is unverifiable compliance theater
# for the traffic that matters), and its real boundary is the node firewall.
# The non-isolated-pod heuristic assumes pod-network traffic, so presence of
# a hostNetwork contract is structural grounds to drop that check for the
# object; every off-hostNetwork workload keeps the full check.
# Workload specs are matched structurally in the report post-processing.
HOST_BOUNDARY_KINDS = frozenset(
    {"Pod", "Deployment", "DaemonSet", "StatefulSet", "ReplicaSet", "Job", "CronJob"}
)

# OCI runtimes used here (containerd/k3s CRI) do not grant ambient
# capabilities to non-root processes: capabilities.add grants the permitted
# set, but the effective bind capability never carries over, so a non-root
# process cannot bind a port < 1024 without image-level file capabilities
# (setcap) or a rebuilt entrypoint. For a hostNetwork daemon that must own a
# privileged port on the node address, running as root with all capabilities
# dropped except NET_BIND_SERVICE is therefore the narrowest implementable
# identity contract; the validator blanket rule ("run as non-root") is
# unimplementable for it. The exemption below requires that full structural
# contract (hostNetwork + a sub-1024 bind + drop ALL + add only
# NET_BIND_SERVICE + runAsNonRoot explicitly false); any workload without that
# exact narrowing keeps the finding.
PRIVILEGED_BIND_EXEMPT_CHECKS = frozenset({"run-as-non-root"})


def _pod_spec(doc) -> dict | None:
    """Return the pod spec owning the workload doc, if any."""
    if doc.get("kind") not in HOST_BOUNDARY_KINDS:
        return None
    if doc["kind"] == "Pod":
        return doc.get("spec") or None
    return ((doc.get("spec") or {}).get("template") or {}).get("spec") or None


def privileged_bind_contracts(resources) -> set:
    """Set of (kind, namespace, name) with the structural bind contract."""
    contracts = set()
    for doc in resources:
        spec = _pod_spec(doc)
        if not spec or not spec.get("hostNetwork"):
            continue
        for container in spec.get("containers") or ():
            context = container.get("securityContext") or {}
            if context.get("runAsNonRoot") is not False:
                continue
            caps = context.get("capabilities") or {}
            if (caps.get("drop") or []) != ["ALL"] or not "NET_BIND_SERVICE" in (
                caps.get("add") or []
            ):
                continue
            ports = [
                p.get("containerPort")
                for p in container.get("ports") or ()
                if isinstance(p.get("containerPort"), int)
            ]
            if any(port < 1024 for port in ports):
                meta = doc["metadata"]
                contracts.add(
                    (doc["kind"], meta.get("namespace", ""), meta["name"])
                )
    return contracts


def host_boundary_objects(resources) -> set:
    """Set of (kind, namespace, name) whose pod spec declares hostNetwork."""
    boundaries = set()
    for doc in resources:
        spec = _pod_spec(doc)
        if spec and spec.get("hostNetwork"):
            meta = doc["metadata"]
            boundaries.add((doc["kind"], meta.get("namespace", ""), meta["name"]))
    return boundaries


# Checks whose kube-linter semantics cannot be satisfied from a single Helm
# render because the referenced or bound object lives in another reviewed
# source. Registry entries must pin the exact object and rule and carry an
# in-repo evidence pointer; anything outside this set can never be registered.
REGISTRABLE_CHECKS = frozenset(
    {
        "env-value-from",
        "read-secret-from-env-var",
        "dangling-service",
        "dangling-networkpolicy",
        "dangling-networkpolicypeer-podselector",
        "dangling-servicemonitor",
        "access-to-secrets",
        "access-to-create-pods",
        "cluster-admin-role-binding",
        "host-network",
        "host-pid",
        "privileged-ports",
        "writable-host-mount",
        "sensitive-host-mounts",
        "drop-net-raw-capability",
    }
)


ProviderRegistry = dict[tuple[str, str, str, str], dict[str, object]]
Pin = tuple[tuple[str, str, str, str], str]


class Pins:
    """Consumption tracker for the pinned cross-source provider registry."""

    def __init__(self, registry: ProviderRegistry) -> None:
        """Start from a verified registry; track every accepted finding."""
        self.registry = registry
        self.consumed: set[Pin] = set()

    def accepts(
        self, identity: tuple[str, str, str, str], check: str
    ) -> bool:
        """Return whether an exact, verified registry pin covers this finding."""
        entry = self.registry.get(identity)
        if entry is None or check not in entry["checks"]:
            return False
        self.consumed.add((identity, check))
        return True

    def verify_scope(self, consumers: set[str]) -> None:
        """Fail on any registry pin that is unknown, orphaned or partially stale."""
        for key, entry in self.registry.items():
            if entry["consumer"] not in consumers:
                raise ValueError("Registry entry references unknown consumer: " + str(key))
            for check in entry["checks"]:
                if (key, check) not in self.consumed:
                    raise ValueError(
                        "Registry entry matched no " + check + " finding (stale pin): " + str(key)
                    )


def provider_registry() -> ProviderRegistry:
    """Load and verify the pinned cross-source provider and contract registry."""
    entries = {}
    directory = ROOT / "ci/quality/providers"
    paths = sorted(directory.glob("*.yaml"))
    for path in paths:
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Invalid provider registry file: " + path.name)
        for raw in data.get("entries", []):
            entry = {
                "consumer": raw.get("consumer"),
                "kind": raw.get("kind"),
                "namespace": raw.get("namespace"),
                "name": raw.get("name"),
                "checks": tuple(raw.get("checks", ())),
                "evidence": raw.get("evidence"),
            }
            if any(not entry[key] for key in ("consumer", "kind", "namespace", "name", "evidence")):
                raise ValueError("Incomplete provider registry entry in " + path.name)
            if not entry["checks"] or set(entry["checks"]) - REGISTRABLE_CHECKS:
                message = "Non-registrable check in " + path.name + ": " + str(entry["name"])
                raise ValueError(message)
            reference = local_path(str(entry["evidence"]))
            if entry["name"] not in reference.read_text():
                raise ValueError("Evidence does not name the object in " + path.name)
            key = (entry["consumer"], entry["kind"], entry["namespace"], entry["name"])
            if key in entries:
                raise ValueError("Duplicate provider registry entry: " + str(key))
            entries[key] = entry
    return entries


def release_peer_objects(target, selected, renders):
    """Return the exact provider objects another release renders for a target."""
    # These consumers reference objects rendered by a different Helm source.
    # Only the actual provider object is context; it still has its own gate.
    link = RELEASE_PEERS.get(target["id"])
    if not link:
        return []
    peer_id, wanted = link
    peer = next((t for t in selected if t["id"] == peer_id), None)
    if peer is None:
        # A missing declared peer is a configuration error, not a silent skip.
        message = f"Missing release peer target: {peer_id}"
        raise ValueError(message)
    if peer_id not in renders:
        renders[peer_id] = render(peer)
    # The Service and the pods behind it: existence providers are full objects,
    # not synthetic stubs, and stay attributed to their own release.
    return [
        doc
        for doc in renders[peer_id] or []
        if (doc["kind"], doc["metadata"]["name"]) in set(wanted)
    ]


def kube_lint(
    target: RenderTarget,
    resources: list[object],
    peers: tuple[object, ...] = (),
    pins: Pins | None = None,
) -> list[object]:
    """Execute kube_lint."""
    if pins is None:
        pins = Pins(provider_registry())

    def key(doc):
        meta = doc["metadata"]
        return doc["kind"], meta.get("namespace", ""), meta["name"]

    peer_keys = {key(doc) for doc in peers}
    if peer_keys.intersection(map(key, resources)):
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
    value = json.loads(data.stdout)
    if value.get("Reports") is None and data.returncode == 0 and "Summary" in value:
        value["Reports"] = []
    if not isinstance(value.get("Reports"), list):
        msg = "Invalid kube-linter report"
        raise ValueError(msg)
    if data.returncode and not value["Reports"]:
        msg = "kube-linter failed without findings"
        raise RuntimeError(msg)
    return catalogue_findings(target, value["Reports"], peer_keys, pins, resources)


def catalogue_findings(target, reports, peer_keys, pins, resources=()):
    """Post-process one kube-linter report into findings, with real semantics."""
    # Precompute the structural workload contracts once per report.
    boundaries = host_boundary_objects(resources)
    binders = privileged_bind_contracts(resources)
    result = []
    for item in reports:
        obj = item["Object"]["K8sObject"]
        kind = obj["GroupVersionKind"]["Kind"]
        identity = (kind, obj.get("Namespace", ""), obj["Name"])
        if kind in ONE_SHOT_KINDS and item["Check"] in ONE_SHOT_EXEMPT_CHECKS:
            continue
        # hostNetwork traffic never traverses the CNI pod datapath: a cluster
        # NetworkPolicy cannot isolate it, so the isolation check has no
        # implementable subject. The node firewall owns that boundary.
        if item["Check"] == "non-isolated-pod" and identity in boundaries:
            continue
        # Narrowest root contract for a privileged-port on-address bind (see
        # PRIVILEGED_BIND_EXEMPT_CHECKS above): unimplementable as non-root
        # under this CRI, every other root workload keeps the finding.
        if item["Check"] in PRIVILEGED_BIND_EXEMPT_CHECKS and identity in binders:
            continue
        # Peers are checked and attributed in full by their own release.
        peer = identity
        if peer in peer_keys:
            continue
        # A pinned, evidence-verified out-of-band provider or node contract.
        if pins.accepts((target["id"], *peer), item["Check"]):
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
) -> list[object]:
    """Return schema availability and strict validation findings for one object."""
    findings: list[object] = []
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
        msg = "No local chart targets"
        raise ValueError(msg)
    findings = []
    inventory = []
    renders = {}
    pins = Pins(provider_registry())
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
        peers = release_peer_objects(target, selected, renders)
        if target["id"] == "authentik-0" and authentik_accounts():
            # Do not discard the foundation accounts' own lint diagnostics.
            findings.extend(kube_lint(FOUNDATION_STUB, authentik_accounts(), pins=pins))
            peers = peers + authentik_accounts()
        findings.extend(kube_lint(target, resources, peers, pins=pins))
        seen = set()
        for resource in resources:
            if (
                not isinstance(resource, dict)
                or not {"apiVersion", "kind", "metadata"} <= resource.keys()
            ):
                msg = "Rendered output is not a Kubernetes object"
                raise ValueError(msg)
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
                schema_findings(target=target, resource=resource, key=key, validate=validate)
            )
            findings.extend(policy_findings(target=target, resource=resource, key=key))
    # No orphaned entries: every registry pin must still match a real finding
    # of its consumer target, or it is removed rather than left in place.
    consumers = {target["id"] for target in selected} | {"authentik-foundation"}
    pins.verify_scope(consumers)
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
