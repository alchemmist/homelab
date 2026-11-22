# Venice manifest follow-up at `dc4ee377`

This note covers only `venice-api` and `venice-agent-lab` manifest findings from
PR #494. Changes here are offline/render-tested; no cluster acceptance is claimed.

## Closed safely

- `venice-api`: replaced its implicit `default` ServiceAccount with a release-named
  ServiceAccount and disabled token automount both there and on the Pod. The
  application has no Kubernetes API use in its chart contract.
- `venice-agent-lab`: set the release namespace explicitly on all namespaced
  ServiceAccount, StatefulSet, Role, RoleBinding, and NetworkPolicy objects.
  The worker and controller remain in the same release namespace; RBAC resource
  names and verbs and the deny-all policy are unchanged.

## Residual decisions — not approved by this change

- **venice-api image identity / writable paths:** before setting a UID or
  read-only root filesystem, identify the pinned image's supported numeric UID
  and prove writes needed by the browser bridge. Preserve `/data/profile`,
  `/dev/shm`, the cookie mount and any actual scratch paths. Require a candidate
  render plus disposable positive/negative write and restart checks. No identity
  or mount changes are made here.
- **venice-api credential delivery:** the bridge currently consumes `API_KEY`
  as an environment variable, while its cookie file is mounted read-only.
  Approve a file-based credential change only after application support and
  secret rotation/restart behavior are proven; retain the existing secret/key
  contract in the meantime.
- **venice-api probes:** choose a meaningful liveness endpoint and prove that its
  failure semantics distinguish a dead process from unavailable upstream browser
  or egress dependencies. Existing readiness `/` is retained; no synthetic
  liveness check or probe port is introduced.
- **venice-api network isolation:** specify permitted ingress callers (including
  the existing LiteLLM path) and required browser/candidate egress endpoints,
  then test both allowed and denied paths in a disposable environment. Do not
  use a guessed deny/allow policy or broaden access to production agents.
- **venice-agent-lab worker probes:** worker runs `sleep infinity` as a deliberately
  idle execution container. Before adding probes, define a real readiness signal
  and liveness failure/restart semantics for the future controller's exec worker;
  process-existence probes would not establish task readiness. The chart remains
  an undeployed draft, with no fabricated namespace (namespace comes from the
  release) and no activation implied.
