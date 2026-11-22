# Cats manifest findings: remaining decisions

The Cats chart uses an explicit release-scoped ServiceAccount with API-token
mounting disabled. The app has no demonstrated Kubernetes API requirement; the
pull secret remains explicitly declared on the Pod. This resolves the
`default-service-account` finding without adding RBAC.

The following six manifest findings remain intentionally unresolved pending
owner decisions/evidence. Do not add placeholder probes, guessed NetworkPolicy
peers, or guessed scheduling/runtime settings merely to silence the scanner.

| Finding(s) | Required decision or evidence |
|---|---|
| `no-liveness-probe`, `no-readiness-probe` | Identify a verified health signal for the deployed Cats image and confirm its behavior for healthy, starting, and failed states. Decide whether probe failure should restart the process and/or remove it from Service endpoints. |
| `non-isolated-pod` | Identify the actual ingress clients that must reach the Cats Service (including the controller/data-plane source identity as represented by the cluster) and any required egress dependencies. Approve a concrete allowlist and test both expected successful and denied traffic before adding policy enforcement. |
| `no-anti-affinity` | Decide whether a strict or preferred replica-spread requirement is appropriate with current eligible nodes and the existing node exclusion. Confirm the desired availability-versus-pending-Pod behavior when an eligible node is unavailable. The existing soft topology-spread constraint is not equivalent to anti-affinity. |
| `no-read-only-root-fs`, `run-as-non-root` | Verify the exact pinned image's numeric UID/GID and runtime write requirements (including temporary/cache paths) before setting a non-root identity or read-only root. Validate startup and normal serving against the image, then add only the required writable mounts. |

No cluster operations or rollout validation were performed. These are source-only,
offline chart changes/tests.
