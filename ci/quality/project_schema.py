"""Project a pinned controller CRD or Kubernetes OpenAPI component for offline kubeconform."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def strict(schema: dict) -> dict:
    """Close structured objects without closing dictionaries or preserved extension payloads."""
    out = dict(schema)
    out.pop("description", None)
    for key in ("properties", "patternProperties"):
        if key in out:
            out[key] = {k: strict(v) for k, v in out[key].items()}
    for key in ("items", "additionalProperties", "not"):
        if isinstance(out.get(key), dict):
            out[key] = strict(out[key])
    for key in ("oneOf", "allOf", "anyOf"):
        if key in out:
            out[key] = [strict(part) for part in out[key]]
    if out.get("properties") and not out.get("x-kubernetes-preserve-unknown-fields"):
        out.setdefault("additionalProperties", False)
    # PrometheusRule's RE2 flag after ^ is not legal JSON Schema regex syntax.
    if out.get("pattern") == "^(?i)(abort|warn)?$":
        out["pattern"] = "^([Aa][Bb][Oo][Rr][Tt]|[Ww][Aa][Rr][Nn])?$"
    if out.get("x-kubernetes-int-or-string") and "type" not in out:
        out["type"] = ["integer", "string"]
    if out.pop("nullable", False):
        return {"anyOf": [out, {"type": "null"}]}
    return out


def crd_projection(document: dict, api: str, kind: str) -> dict:
    """Take the exact served version; graft the already locked ObjectMeta definition."""
    group, version = api.split("/")
    spec = document["spec"]
    if spec["group"] != group or spec["names"]["kind"] != kind:
        message = "CRD does not own requested API"
        raise ValueError(message)
    (schema,) = [
        v["schema"]["openAPIV3Schema"]
        for v in spec["versions"]
        if v["served"] and v["name"] == version
    ]
    meta = json.loads((ROOT / "ci/quality/schemas/service-v1.json").read_bytes())[
        "properties"
    ]
    result = strict(schema)
    result["properties"]["metadata"] = {
        "allOf": [result["properties"]["metadata"], strict(meta["metadata"])]
    }
    return result


def openapi_projection(document: dict, component: str) -> dict:
    """Keep only transitive local components; preserve recursive references without expanding."""
    components = document["components"]["schemas"]
    definitions = {}

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("$ref"), str):
                prefix = "#/components/schemas/"
                ref = value["$ref"]
                if not ref.startswith(prefix):
                    message = "OpenAPI reference is not a local component"
                    raise ValueError(message)
                key = ref[len(prefix) :]
                value["$ref"] = "#/definitions/" + key
                if key not in definitions:
                    definitions[key] = strict(components[key])
                    visit(definitions[key])
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    result = strict(components[component])
    visit(result)
    # OpenAPI describes these custom-marshaled Go unions in prose only. Keep
    # schema-valued branches recursive rather than accepting arbitrary JSON.
    base = "io.k8s.apiextensions-apiserver.pkg.apis.apiextensions.v1.JSONSchemaProps"
    recursive = {"$ref": "#/definitions/" + base}
    for suffix, alternate in {
        "OrBool": {"type": "boolean"},
        "OrArray": {"type": "array", "items": recursive},
        "OrStringArray": {"type": "array", "items": {"type": "string"}},
    }.items():
        if base + suffix in definitions:
            definitions[base + suffix] = {"oneOf": [recursive, alternate]}
    result["definitions"] = definitions
    return result


def main() -> None:
    """Print one stable JSON schema; inputs are local and no cluster is consulted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("api_version")
    parser.add_argument("kind")
    parser.add_argument("--component")
    args = parser.parse_args()
    if args.component:
        result = openapi_projection(json.loads(args.input.read_bytes()), args.component)
    else:
        docs = yaml.safe_load_all(args.input.read_bytes())
        (doc,) = [
            d
            for d in docs
            if d
            and d["kind"] == "CustomResourceDefinition"
            and d["spec"]["names"]["kind"] == args.kind
        ]
        result = crd_projection(doc, args.api_version, args.kind)
    for field, value in (("kind", args.kind), ("apiVersion", args.api_version)):
        result["properties"][field]["enum"] = [value]
    result["$schema"] = "http://json-schema.org/draft-04/schema#"
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
