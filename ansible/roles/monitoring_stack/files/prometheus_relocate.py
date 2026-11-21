import json
import sys


CLAIM_PREFIX = "prometheus-kube-prometheus-stack-prometheus-db"
POD_PREFIX = "prometheus-kube-prometheus-stack-prometheus-"


def live_node(pods, volumes):
    """Execute the live_node operation."""
    for pod in pods:
        name = pod.get("metadata", {}).get("name", "")
        if not name.startswith(POD_PREFIX):
            continue
        node = pod.get("spec", {}).get("nodeName")
        if node:
            return node
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
                    return expr["values"][0]
    return None


def claim_name(volumes):
    """Execute the claim_name operation."""
    for volume in volumes:
        claim = volume.get("spec", {}).get("claimRef") or {}
        name = str(claim.get("name", ""))
        if name.startswith(CLAIM_PREFIX):
            return name
    return None


def decide(desired_node, current_node, relocate):
    """Execute the decide operation."""
    if current_node in (None, "", desired_node):
        return "proceed"
    return "refuse"


def evaluate(payload):
    """Execute the evaluate operation."""
    pods = payload.get("pods") or []
    volumes = payload.get("volumes") or []
    current = live_node(pods, volumes)
    action = decide(payload.get("desired"), current, bool(payload.get("relocate")))
    return {"action": action, "node": current, "claim": claim_name(volumes)}


def main():
    """Execute the main operation."""
    json.dump(evaluate(json.load(sys.stdin)), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
