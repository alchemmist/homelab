"""Render local Argo contracts with consumed values; never contact Kubernetes or Helm repos."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys

import yaml

from common import ROOT, command, digest, failure, finding, report, tracked


class ManifestLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
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
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT) or not path.exists():
        raise ValueError("Missing or escaping chart/value path")
    return path


def targets():
    result = []
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
            if set(helm) - {"releaseName", "valueFiles", "parameters"}:
                raise ValueError("Unsupported Helm override: extend the renderer explicitly")
            values = []
            for value in helm.get("valueFiles", []):
                if value.startswith("$"):
                    ref, relative = value[1:].split("/", 1)
                    if ref not in refs or refs[ref].get("targetRevision") != "main":
                        raise ValueError("Unsupported value reference")
                    values.append(local_path(relative))
                else:
                    values.append(local_path(str(chart.relative_to(ROOT) / value)))
            result.append(
                {
                    "id": app["metadata"]["name"] + f"-{index}",
                    "source": path.relative_to(ROOT).as_posix(),
                    "chart": chart,
                    "namespace": spec["destination"].get("namespace", "default"),
                    "release": helm.get("releaseName", app["metadata"]["name"]),
                    "values": values,
                    "parameters": helm.get("parameters", []),
                }
            )
    # Include every unconsumed root, including vendored charts, with chart defaults.
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
    return sorted(result, key=lambda target: target["id"])


def arguments(target):
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,52}", target["release"]):
        raise ValueError("Invalid Helm release name")
    args = ["--kube-version", KUBE_VERSION, "--namespace", target["namespace"]]
    for value in target["values"]:
        args += ["--values", str(value)]
    for parameter in target["parameters"]:
        if set(parameter) - {"name", "value", "forceString"}:
            raise ValueError("Unsupported Helm parameter")
        if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.\[\]\\/-]*", parameter["name"]):
            raise ValueError("Unsafe Helm parameter name")
        flag = "--set-string" if parameter.get("forceString") else "--set"
        args += [flag + "=" + parameter["name"] + "=" + str(parameter["value"])]
    return args


def render(target):
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
    process = command(args, allowed=(0, 1), timeout=90)
    if process.returncode:
        return None
    try:
        return [item for item in yaml.load_all(process.stdout, Loader=ManifestLoader) if item]
    except yaml.YAMLError:
        return None  # Invalid rendered YAML is a quality failure, not a successful empty render.


def schema_name(resource):
    api = resource["apiVersion"].split("/")
    version = (api[0].split(".")[0] + "-" + api[1]) if len(api) == 2 else api[0]
    return resource["kind"].lower() + "-" + version + ".json"


def policies(resource):
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


def kube_lint(target, resources):
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
        stdin=yaml.safe_dump_all(resources),
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
    # A previously broken render is accepted ONLY while its entire source stays identical.
    parts = [target["id"], json.dumps(target["parameters"], sort_keys=True)]
    for path in sorted(target["chart"].rglob("*")):
        if path.is_file():
            if not path.resolve().is_relative_to(ROOT):
                raise ValueError("Chart dependency escapes repository")
            parts += [str(path.relative_to(ROOT)), digest(path.read_bytes().hex())]
    for path in target["values"]:
        parts += [str(path.relative_to(ROOT)), digest(path.read_bytes().hex())]
    return digest("\0".join(parts))


def check(*, validate=True):
    selected = targets()
    if not selected:
        raise ValueError("No local chart targets")
    findings = []
    inventory = []
    for target in selected:
        source = target["source"]
        lint = command(["helm", "lint", str(target["chart"]), *arguments(target)], allowed=(0, 1))
        resources = render(target)
        if lint.returncode or resources is None:
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
        if resources is None:
            continue
        findings.extend(kube_lint(target, resources))
        seen = set()
        for resource in resources:
            if (
                not isinstance(resource, dict)
                or not {"apiVersion", "kind", "metadata"} <= resource.keys()
            ):
                raise ValueError("Rendered output is not a Kubernetes object")
            key = "|".join(
                str(v)
                for v in [
                    target["id"],
                    resource["apiVersion"],
                    resource["kind"],
                    resource["metadata"].get("namespace", target["namespace"]),
                    resource["metadata"].get("name"),
                ]
            )
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
            if validate:
                path = ROOT / "quality/schemas" / schema_name(resource)
                if not path.exists():
                    findings.append(
                        finding(
                            "schema-unavailable",
                            source,
                            1,
                            f"{resource['apiVersion']}/{resource['kind']}: no reviewed offline schema",
                            key,
                        )
                    )
                else:
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
                                source,
                                1,
                                f"{resource['kind']}: strict Kubernetes schema validation failed",
                                key + digest(json.dumps(resource, sort_keys=True)),
                            )
                        )
            for rule, message in policies(resource):
                findings.append(finding(rule, source, 1, message, key + "|" + message))
    return findings, len(selected), sorted(set(inventory))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema-inventory", action="store_true")
    parser.add_argument("--record-debt")
    args = parser.parse_args()
    output = ROOT / "reports/manifests.json"
    try:
        findings, count, inventory = check(validate=not args.schema_inventory)
        if args.schema_inventory:
            print(json.dumps(inventory))
            return 0
        return report(
            "manifests",
            findings,
            count,
            output,
            record_reason=args.record_debt,
        )
    except Exception as error:
        failure(output, error)
        print(
            f"charts: {type(error).__name__}; no fallback or live access",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
