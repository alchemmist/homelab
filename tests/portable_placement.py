"""Exact scheduling contract for portable home workloads."""


def home_affinity() -> dict[str, object]:
    """Allow only the two home nodes, preferring socrat-0."""

    def term(*nodes: str) -> dict[str, object]:
        return {
            "matchExpressions": [
                {
                    "key": "kubernetes.io/hostname",
                    "operator": "In",
                    "values": list(nodes),
                }
            ]
        }

    return {
        "nodeAffinity": {
            "requiredDuringSchedulingIgnoredDuringExecution": {
                "nodeSelectorTerms": [term("socrat-0", "socrat-1")]
            },
            "preferredDuringSchedulingIgnoredDuringExecution": [
                {"weight": 100, "preference": term("socrat-0")}
            ],
        }
    }
