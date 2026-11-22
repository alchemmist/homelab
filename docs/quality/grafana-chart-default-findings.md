# Vendored Grafana chart default findings

## Scope and disposition

`charts/grafana/charts/grafana` is the vendored Grafana community chart 14.5.0,
used as a dependency by the Grafana service chart. The PR #494 finding inventory
also evaluates the dependency's upstream-default render as its own target. This
is not a separate deployed release. The actual Grafana service settings remain
owned by `charts/grafana` and must not be changed to make the dependency's
standalone default render appear to be an approved installation.

No manifest change is made for the 15 standalone-default findings pending the
specific owner decision below. This is not a waiver or a claim that the findings
are fixed. Changing upstream defaults would alter the behavior of the real
Grafana dependency as well as the hypothetical standalone render.

## Required owner decision

Approve maintaining a downstream defaults overlay/fork for the vendored chart,
with explicit values for a real standalone namespace, resource requests, probe
semantics, and credential delivery; or confirm that the standalone-default
render is intentionally unsupported and should no longer be an independent
manifest target. Until then, do not invent a namespace or resource floors, add
probes without validating the intended process/sidecars, change secret-to-env
behavior, or pin image digests without verified registry provenance. Any
approved overlay must be checked against the actual Grafana service render and
its SSO, PVC, sidecar, and RBAC contracts.

Outstanding findings (15):

- image digest: 2
- missing liveness/readiness probes: 1 each
- non-isolated pod: 2
- secret read through environment: 2
- unset CPU/memory requests: 2 each
- missing namespace: 3

## Offline checks

At the task base, `helm lint charts/grafana/charts/grafana` succeeds. Helm renders
10 objects both with an explicit `grafana` namespace and with no namespace; the
no-namespace render leaves namespaced objects without `metadata.namespace`, as
expected for a reusable chart. These checks validate chart syntax/rendering only;
they do not resolve the pending default-policy decision or establish runtime
behavior. No cluster or production operation was performed.
