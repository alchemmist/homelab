"""Project a pinned controller CRD or Kubernetes OpenAPI component for offline kubeconform."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _mapping(obj: object) -> dict[str, object]:
    """Runtime narrowing of one schema node to its mapping form."""
    if not isinstance(obj, dict):
        message = "expected a schema mapping"
        raise TypeError(message)
    return obj


def strict(schema: dict[str, object]) -> dict[str, object]:
    """Close structured objects without closing dictionaries or preserved extension payloads."""
    out = dict(schema)
    out.pop("description", None)
    for key in ("properties", "patternProperties"):
        if key in out:
            out[key] = {k: strict(_mapping(v)) for k, v in _mapping(out[key]).items()}
    for key in ("items", "additionalProperties", "not"):
        field = out.get(key)
        if isinstance(field, dict):
            out[key] = strict(field)
    for key in ("oneOf", "allOf", "anyOf"):
        if out.get(key):
            out[key] = [strict(_mapping(part)) for part in _mapping(out[key])]
    if out.get("properties") and not out.get("x-kubernetes-preserve-unknown-fields"):
        out.setdefault("additionalProperties", False)
    wrapped = _kubernetes_statements(out)
    return wrapped if wrapped is not None else out


def _sequence(obj: object) -> list[object]:
    """Runtime narrowing of one schema node to its list form."""
    if not isinstance(obj, list):
        message = "expected a schema list"
        raise TypeError(message)
    return obj


def _kubernetes_statements(out: dict[str, object]) -> dict[str, object] | None:
    """Normalize invalid regexes as reviewed; wrap nullable unions when present."""
    # PrometheusRule's RE2 flag after ^ is not legal JSON Schema regex syntax.
    if out.get("pattern") == "^(?i)(abort|warn)?$":
        out["pattern"] = "^([Aa][Bb][Oo][Rr][Tt]|[Ww][Aa][Rr][Nn])?$"
    if out.get("x-kubernetes-int-or-string") and "type" not in out:
        out["type"] = ["integer", "string"]
    if out.pop("nullable", False):
        return {"anyOf": [out, {"type": "null"}]}
    return None


def crd_projection(document: dict[str, object], api: str, kind: str) -> dict[str, object]:
    """Take the exact served version; graft the already locked ObjectMeta definition."""
    group, version = api.split("/")
    spec = _mapping(document["spec"])
    if spec["group"] != group or _mapping(spec["names"])["kind"] != kind:
        message = "CRD does not own requested API"
        raise ValueError(message)
    (schema,) = [
        _mapping(_mapping(_mapping(v)["schema"])["openAPIV3Schema"])
        for v in _sequence(spec["versions"])
        if _mapping(v)["served"] and _mapping(v)["name"] == version
    ]
    meta = json.loads((ROOT / "ci/quality/schemas/service-v1.json").read_bytes())["properties"]
    result = strict(schema)
    properties = _mapping(result["properties"])
    properties["metadata"] = {
        "allOf": [properties["metadata"], strict(_mapping(_mapping(meta)["metadata"]))]
    }
    return result


def _visit(value: object, components: dict[str, object], definitions: dict[str, object]) -> None:
    """Rewrite local component references into strict JSON Schema definitions."""
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            prefix = "#/components/schemas/"
            if not ref.startswith(prefix):
                message = "OpenAPI reference is not a local component"
                raise ValueError(message)
            key = ref[len(prefix) :]
            value["$ref"] = "#/definitions/" + key
            if key not in definitions:
                definitions[key] = strict(_mapping(components[key]))
                _visit(definitions[key], components, definitions)
        else:
            for child in value.values():
                _visit(child, components, definitions)
    elif isinstance(value, list):
        for child in value:
            _visit(child, components, definitions)


def openapi_projection(document: dict[str, object], component: str) -> dict[str, object]:
    """Keep only transitive local components; preserve recursive references without expanding."""
    components = _mapping(_mapping(document["components"])["schemas"])
    definitions: dict[str, object] = {}
    result = strict(_mapping(components[component]))
    _visit(result, components, definitions)
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
        _mapping(_mapping(result["properties"])[field])["enum"] = [value]
    result["$schema"] = "http://json-schema.org/draft-04/schema#"
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
