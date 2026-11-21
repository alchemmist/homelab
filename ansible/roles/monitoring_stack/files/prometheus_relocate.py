import json
import sys
from typing import cast


CLAIM_PREFIX = "prometheus-kube-prometheus-stack-prometheus-db"
POD_PREFIX = "prometheus-kube-prometheus-stack-prometheus-"


def live_node(pods, volumes) -> str | None:
    for pod in pods:
        name = pod.get("metadata", {}).get("name", "")
        if not name.startswith(POD_PREFIX):
            continue
        node = pod.get("spec", {}).get("nodeName")
        if node:
            return cast("str", node)
    for volume in volumes:
        claim = volume.get("spec", {}).get("claimRef") or {}
        if not str(claim.get("name", "")).startswith(CLAIM_PREFIX):
            continue
        terms = (
            volume.get("spec", {})
            .get("nodeAffinity", {})
            .get("required", {})
            .get("nodeSelectorTerms", [])
        )
        for term in terms:
            for expr in term.get("matchExpressions", []):
                if expr.get("key") == "kubernetes.io/hostname" and expr.get("values"):
                    return cast("str", expr["values"][0])
    return None


def claim_name(volumes) -> str | None:
    for volume in volumes:
        claim = volume.get("spec", {}).get("claimRef") or {}
        name = str(claim.get("name", ""))
        if name.startswith(CLAIM_PREFIX):
            return name
    return None


def decide(desired_node, current_node, relocate) -> str:
    if current_node in (None, "", desired_node):
        return "proceed"
    return "refuse"


def evaluate(payload) -> dict[str, object]:
    pods = payload.get("pods") or []
    volumes = payload.get("volumes") or []
    current = live_node(pods, volumes)
    action = decide(payload.get("desired"), current, bool(payload.get("relocate")))
    return {"action": action, "node": current, "claim": claim_name(volumes)}


def main() -> int:
    json.dump(evaluate(json.load(sys.stdin)), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
