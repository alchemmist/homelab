import json
import sys
from typing import Protocol, TypedDict


CLAIM_PREFIX = "prometheus-kube-prometheus-stack-prometheus-db"
POD_PREFIX = "prometheus-kube-prometheus-stack-prometheus-"


class _Condition(Protocol):
    def __bool__(self) -> bool: ...


class _ObjectMeta(TypedDict, total=False):
    name: str


class _PodSpec(TypedDict, total=False):
    nodeName: str


class _Pod(TypedDict, total=False):
    metadata: _ObjectMeta
    spec: _PodSpec


class _ClaimRef(TypedDict, total=False):
    name: str


class _MatchExpression(TypedDict, total=False):
    key: str
    values: list[str]


class _SelectorTerm(TypedDict, total=False):
    matchExpressions: list[_MatchExpression]


class _RequiredAffinity(TypedDict, total=False):
    nodeSelectorTerms: list[_SelectorTerm]


class _NodeAffinity(TypedDict, total=False):
    required: _RequiredAffinity


class _VolumeSpec(TypedDict, total=False):
    claimRef: _ClaimRef
    nodeAffinity: _NodeAffinity


class _Volume(TypedDict, total=False):
    spec: _VolumeSpec


class _RelocatePayload(TypedDict, total=False):
    pods: list[_Pod]
    volumes: list[_Volume]
    desired: str
    relocate: object


def live_node(pods: list[_Pod], volumes: list[_Volume]):
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


def claim_name(volumes: list[_Volume]):
    for volume in volumes:
        claim = volume.get("spec", {}).get("claimRef") or {}
        name = str(claim.get("name", ""))
        if name.startswith(CLAIM_PREFIX):
            return name
    return None


def decide(desired_node: str | None, current_node: str | None, relocate: _Condition):
    if current_node in (None, "", desired_node):
        return "proceed"
    if relocate:
        return "proceed"
    return "refuse"


def evaluate(payload: _RelocatePayload):
    pods = payload.get("pods") or []
    volumes = payload.get("volumes") or []
    current = live_node(pods, volumes)
    action = decide(payload.get("desired"), current, bool(payload.get("relocate")))
    return {"action": action, "node": current, "claim": claim_name(volumes)}


def main():
    json.dump(evaluate(json.load(sys.stdin)), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
