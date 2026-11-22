# format-quorum findings: approval/evidence still required

**PR #494 disposition:** no workload policy or runtime changes are safe from the
available source evidence. The findings are not waived; the PR's owner decision
for this service remains open. The chart renders the real single-writer service
and its three persistent data volumes, so guessed probes, identities, writable
paths, isolation peers or resource floors could break production behavior.

## Current rendered workload

The production Application consumes `charts/format-quorum` plus
`deploy/format-quorum/values.yaml`. It renders one `Recreate` Deployment on
`socrat-5`, using the existing image digest, the three existing claims, and a
read-only handoff-verification init container when `requireExistingData` is
true. The application container has requests of `100m` CPU and `256Mi` memory,
and a `1Gi` memory limit; the init container has no resource declaration.
There is no explicit service account, container security context, or probe.
The production env keeps `PUBLISH_ENABLED=0` and existing app paths intact.

The stateful move receipt (`docs/vm105-stateful-20261116.md`) establishes that
all three volumes contain compiler binaries, tests, and configuration history,
and that ordinary formatter/config/test GETs returned 200 after that move. It
does not establish the image's numeric UID, writable scratch paths, quorum
health semantics, CPU/memory startup floors, or API/network dependencies.
The chart's init container only reads its marker files; its mount is read-only.
That does not determine the main process's data-directory ownership or runtime
writes.

## Exact remaining decisions

1. **Default service account:** establish from the image/application contract
   that neither the server nor any child process needs Kubernetes API
   credentials; then use a dedicated account with token automount disabled and
   test the rendered account/token settings. No such source contract is present
   in this repository, so disabling credentials is not presumed behavior-safe.
2. **Non-root (two containers):** provide the image's supported numeric UID/GID
   and verify that identity can read the handoff markers and operate on all
   existing data mounts. Do not assume a named image user, `fsGroup`, or a
   blanket ownership migration.
3. **Read-only root filesystem (two containers):** identify every runtime
   scratch/config/cache/temp write path for the actual image and decide which
   explicit writable mounts are appropriate. The three persistent paths are
   business data, not generic scratch space. Verify representative formatter,
   test retrieval, compiler/config retrieval, and restart behavior before
   enforcing read-only root filesystems.
4. **Liveness/readiness:** specify a real health signal and semantics for
   quorum readiness versus process liveness. The existing HTTP-200 smoke checks
   do not prove that a probe on `/` detects loss of usable quorum or distinguish
   transient initialization from a restart-worthy failure. Supply an app-backed
   positive/negative probe test before adding either probe.
5. **Network isolation:** identify exact ingress clients (including ingress and
   monitoring) and egress dependencies used by normal formatting and data
   access. Prove the peer selectors against a composed offline inventory, then
   exercise allowed and denied flows. No guessed default-deny policy is safe.
6. **Resources:** retain the existing main-container requests. Provide measured
   init and application CPU/memory floors from representative startup and
   formatting/test workloads. The init currently only checks three marker files,
   but no measurement supports assigning it a numeric request/limit, and no
   runtime measurement supports changing the existing main values. Limits and
   requests are not invented to satisfy lint.

Until those specific answers/evidence are available, leave these blocking
findings visible. In particular, do not change replica count, Recreate/single-
writer behavior, claims, image, node placement, application env, or publication
state to improve scan output.

## Scoped offline render check

From the repository root, the production render was checked without contacting
Kubernetes or a chart repository:

```sh
helm template format-quorum charts/format-quorum \
  --namespace format-quorum -f deploy/format-quorum/values.yaml
```

The rendered inventory was three PVCs, one Service, one Deployment and one
Ingress. Parsing that render confirmed the two containers, read-only init
mounts, current main-container requests/limit, and absence of the unsettled
security/probe/resource declarations listed above. This is a baseline/decision
check, not a claim that the manifest findings are fixed or that runtime behavior
was tested.
