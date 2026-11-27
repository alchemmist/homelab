"""Find direct RBAC mutation grants for one pinned TLS Secret; never request Secrets.

Positive findings only. A clean result is not writer approval: admission,
impersonation, RBAC escalation, workloads, non-RBAC authorizers and the
ability to modify a Certificate or its controller are outside this scan.
"""

import argparse
import json
import sys
from collections.abc import Mapping
from typing import TypedDict, cast

from services.public_entry.tls_issuance import _mapping, _text

KINDS = {"Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding"}
MUTATIONS = {"create", "update", "patch", "delete", "deletecollection"}
NAMESPACED_KINDS = {"Role", "RoleBinding"}
API_GROUP = "rbac.authorization.k8s.io"
MSG_UNEXPECTED_RBAC_INPUT = "unexpected RBAC input"
MSG_DUPLICATE_ROLE = "duplicate role observation"
MSG_INVALID_ROLE_REFERENCE = "invalid role reference"
MSG_INCOMPLETE_ROLE_REFERENCE = "incomplete role reference"
MSG_EXPECTED_STRING_LIST = "expected a list of strings"
MSG_EXPECTED_RULES = "expected a list of rule mappings"
MSG_EXPECTED_SUBJECTS = "expected a list of binding subject mappings"

Object = dict[str, object]
RoleKey = tuple[str, str | None, str]
Rule = Mapping[str, object]


class _Grant(TypedDict):
    """One direct binding grant, with only literal RBAC identities."""

    binding: list[str | None]
    role: list[str]
    verbs: list[str]
    subjects: list[Object]


def _strlist(value: object) -> list[str]:
    """Narrow one reviewed RBAC list slot (apiGroups/resources/verbs)."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(MSG_EXPECTED_STRING_LIST)
    return cast("list[str]", value)


def _rules(value: object) -> list[Rule]:
    """Narrow observed role rules to rule mappings (effective aggregated rules included)."""
    if not isinstance(value, list) or not all(isinstance(rule, dict) for rule in value):
        raise TypeError(MSG_EXPECTED_RULES)
    return cast("list[Rule]", value)


def _subjects(value: object) -> list[Object]:
    """Narrow a binding's subjects to mappings of literal subject identities."""
    if not isinstance(value, list) or not all(isinstance(subject, dict) for subject in value):
        raise TypeError(MSG_EXPECTED_SUBJECTS)
    return cast("list[Object]", value)


def _rbac_parts(
    namespace: str, objects: list[Object]
) -> tuple[dict[RoleKey, list[Rule]], list[tuple[str, str | None, str, Object]]]:
    """First pass: validate each object, then split observed roles from bindings."""
    roles: dict[RoleKey, list[Rule]] = {}
    bindings: list[tuple[str, str | None, str, Object]] = []
    for obj in objects:
        kind = obj["kind"]
        if obj["apiVersion"] != "rbac.authorization.k8s.io/v1" or not (
            isinstance(kind, str) and kind in KINDS
        ):
            raise ValueError(MSG_UNEXPECTED_RBAC_INPUT)
        meta = _mapping(obj["metadata"])
        name = _text(meta["name"])
        ns = _text(meta["namespace"]) if kind in NAMESPACED_KINDS else None
        if ns not in (None, namespace):
            continue
        if kind.endswith("Binding"):
            bindings.append((kind, ns, name, obj))
        else:
            key = kind, ns, name
            if key in roles:
                raise ValueError(MSG_DUPLICATE_ROLE)
            roles[key] = _rules(obj.get("rules", []))  # use effective rules for aggregated roles
    return roles, bindings


def _secret_verbs(name: str, rules: list[Rule]) -> set[str]:
    """Reduce one role's rules to the mutation verbs granted on the pinned Secret."""
    verbs: set[str] = set()
    for rule in rules:
        if not {"", "*"}.intersection(_strlist(rule.get("apiGroups", []))) or not {
            "secrets",
            "*",
        }.intersection(_strlist(rule.get("resources", []))):
            continue
        names = _strlist(rule.get("resourceNames", []))
        if names and name not in names:
            continue
        allowed = (
            MUTATIONS
            if "*" in _strlist(rule["verbs"])
            else MUTATIONS.intersection(_strlist(rule["verbs"]))
        )
        # create and collection deletion are authorized without a resource name.
        verbs.update(allowed - {"create", "deletecollection"} if names else allowed)
    return verbs


def grants(namespace: str, name: str, objects: list[Object]) -> list[_Grant]:
    """Require a complete RBAC list from the caller, not a filtered set of bindings."""
    roles, bindings = _rbac_parts(namespace, objects)
    found: list[_Grant] = []
    for kind, ns, binding, obj in bindings:
        ref = _mapping(obj["roleRef"])
        rk = _text(ref["kind"])
        if ref["apiGroup"] != API_GROUP or not (rk == "ClusterRole" or (ns and rk == "Role")):
            raise ValueError(MSG_INVALID_ROLE_REFERENCE)
        rules = roles.get((rk, ns if rk == "Role" else None, _text(ref["name"])))
        if rules is None:
            raise ValueError(MSG_INCOMPLETE_ROLE_REFERENCE)
        verbs = _secret_verbs(name, rules)
        subject_rows = obj.get("subjects")
        if verbs and subject_rows:
            found.append(
                {
                    "binding": [kind, ns, binding],
                    "role": [rk, _text(ref["name"])],
                    "verbs": sorted(verbs),
                    "subjects": [
                        {
                            key: subject[key]
                            for key in ("kind", "namespace", "name")
                            if key in subject
                        }
                        for subject in _subjects(subject_rows)
                    ],
                }
            )
    return sorted(found, key=lambda row: (row["binding"][0], row["binding"][2]))


def main() -> int:
    """Parse CLI arguments and report explicit RBAC mutation grants on stdin."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace")
    parser.add_argument("source_name")
    args = parser.parse_args()
    try:
        rows = grants(args.namespace, args.source_name, json.load(sys.stdin)["items"])
    except (KeyError, ValueError, TypeError, AttributeError):
        print("Incomplete or invalid RBAC input.", file=sys.stderr)
        return 1
    print(json.dumps({"directMutationGrants": rows, "writerApproved": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
