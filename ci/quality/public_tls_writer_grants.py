"""Find direct RBAC mutation grants for one pinned TLS Secret; never request Secrets.

Positive findings only. A clean result is not writer approval: admission,
impersonation, RBAC escalation, workloads, non-RBAC authorizers and the
ability to modify a Certificate or its controller are outside this scan.
"""

import argparse
import json
import sys

KINDS = {"Role", "RoleBinding", "ClusterRole", "ClusterRoleBinding"}
MUTATIONS = {"create", "update", "patch", "delete", "deletecollection"}


def grants(namespace: str, name: str, objects: list[dict]) -> list[dict]:
    """Require a complete RBAC list from the caller, not a filtered set of bindings."""
    roles = {}
    bindings = []
    for obj in objects:
        kind = obj["kind"]
        if obj["apiVersion"] != "rbac.authorization.k8s.io/v1" or kind not in KINDS:
            raise ValueError("unexpected RBAC input")
        meta = obj["metadata"]
        ns = meta["namespace"] if kind in {"Role", "RoleBinding"} else None
        if ns not in (None, namespace):
            continue
        if kind.endswith("Binding"):
            bindings.append((kind, ns, meta["name"], obj))
        else:
            key = kind, ns, meta["name"]
            if key in roles:
                raise ValueError("duplicate role observation")
            roles[key] = obj.get("rules", [])  # use effective rules for aggregated roles
    found = []
    for kind, ns, binding, obj in bindings:
        ref = obj["roleRef"]
        rk = ref["kind"]
        if ref["apiGroup"] != "rbac.authorization.k8s.io" or not (
            rk == "ClusterRole" or (ns and rk == "Role")
        ):
            raise ValueError("invalid role reference")
        rules = roles.get((rk, ns if rk == "Role" else None, ref["name"]))
        if rules is None:
            raise ValueError("incomplete role reference")
        verbs = set()
        for r in rules:
            if not {"", "*"}.intersection(r.get("apiGroups", [])) or not {
                "secrets",
                "*",
            }.intersection(r.get("resources", [])):
                continue
            names = r.get("resourceNames", [])
            if names and name not in names:
                continue
            allowed = MUTATIONS if "*" in r["verbs"] else MUTATIONS.intersection(r["verbs"])
            # create and collection deletion are authorized without a resource name.
            verbs.update(allowed - {"create", "deletecollection"} if names else allowed)
        if verbs and obj.get("subjects"):
            found.append(
                {
                    "binding": [kind, ns, binding],
                    "role": [rk, ref["name"]],
                    "verbs": sorted(verbs),
                    "subjects": [
                        {k: s[k] for k in ("kind", "namespace", "name") if k in s}
                        for s in obj["subjects"]
                    ],
                }
            )
    return sorted(found, key=lambda row: (row["binding"][0], row["binding"][2]))


def main():
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
