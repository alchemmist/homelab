# Open Terminal manifest findings

The offline manifest audit identifies Open Terminal's rendered Deployment as the
source for findings in `open-terminal`. The audit's 12 findings are not a license
to change its runtime contract: the API key, persistent workspace, browser cleanup
sidecar and init guard are intentional. No credential transport, workspace mount,
network access, identity, or storage behavior was changed for this review.

## Cross-release policy peer

`open-terminal-isolation` admits only pods matching `app: open-webui`. That peer is
owned by the separate `open-webui` Helm release, so a per-release lint can label
it dangling without seeing its target. The scoped test
`test_terminal_ingress_peer_matches_the_separate_webui_release` renders both
charts independently and verifies that the peer matches both the WebUI Deployment
pod-template labels and Deployment selector. Keep the narrow selector; do not
broaden ingress to clear the per-release diagnostic.

## Residual decisions

The other diagnostics need runtime-specific evidence or owner approval; they are
not safely fixed by guessing. In particular:

- The image declares a named user, not a numeric UID. Before setting `runAsNonRoot`
  or a numeric `runAsUser`, verify the image's effective UID and the main process'
  write requirements for `/home/user`, temporary paths, and browser runtime files.
  Verify the init guard and cleanup sidecar separately.
- Before setting `readOnlyRootFilesystem`, establish every required writable path
  for the main process, migration init container, and cleanup sidecar, then test
  startup, browser testing, and workspace persistence with those paths writable.
- The migration init container needs explicit CPU/memory requests. Obtain measured
  floors from representative migration-guard execution before setting values;
  do not copy the main workload's requests by assumption.
- The API key is deliberately sourced from the existing Kubernetes Secret through
  the environment variable expected by Open Terminal. Keep this behavior unless
  upstream support for a file-based API key and rotation has been verified and
  approved; do not expose the secret or weaken authorization to clear a lint rule.
- The main workload already has TCP startup, readiness, and liveness probes. The
  browser-cleanup sidecar has no independent health endpoint; before adding sidecar
  probes, verify the watchdog's actual failure semantics and restart behavior.
- The workload's egress policy intentionally allows public HTTP/HTTPS (excluding
  private and link-local ranges) for terminal tasks. Do not replace that service
  requirement with a default-deny or guessed peer list. A narrower design requires
  an explicit destination contract and positive/negative network tests.

These are residual technical decisions, not proposed exceptions or authorization
to modify policy. Required acceptance is an offline positive/negative render test
plus a disposable runtime test covering startup, workspace writes, API-key
rotation, browser cleanup, and rollback. No production rollout or cluster
operation is part of this work.
