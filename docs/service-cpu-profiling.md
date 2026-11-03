# Service CPU profiling (Pyroscope)

- **CPU flame graph + CPU timeline:**
  <https://grafana.socrat.alchemmist.xyz/d/service-cpu-profiling>
- **Request/span waterfall:**
  <https://grafana.socrat.alchemmist.xyz/d/lms-performance>

These are deliberately different views. The waterfall explains request latency,
RPC/DB timing and ancestry. The flame graph aggregates sampled function stacks:
width is sampled CPU time, not chronological wall-clock duration. The timeline
below it selects when that CPU was consumed. A strictly chronological per-sample
flame chart, browser main-thread profile, off-CPU profile and allocation profile
are **not** provided by this initial CPU dashboard.

## Current coverage

**Enabled: LMS backend (CPython 3.12).** `pyroscope-io==1.4.0` samples GIL-held,
on-CPU Python stacks at 49 Hz and uploads every 15 seconds. It runs in the
application process without a privileged node agent, host PID namespace or
`SYS_PTRACE`. The non-root/capability-dropped Linux smoke test exported profiles
successfully. Profiles show real `Site.response`, `render_navigation`, HTTP
handler and database functions. No local-variable values, request/user tags,
HTTP payloads or allocation objects are collected. C-extension internals, waiting
threads and Python code running without the GIL are not fully represented;
these sampled CPU totals are not total pod CPU. Overhead has not been benchmarked
under a representative production load; 49 Hz is a conservative starting point,
not a measured guarantee.

**Not automatically enabled:** all other services, browsers, runner/student code,
GPU kernels and native processes. The Pyroscope backend is shared and the
Service dropdown discovers instrumented services, but another service only
appears after an explicitly reviewed runtime-specific integration. Do not infer
that installing a datasource profiles every service in the cluster.

## Use

1. Open the CPU dashboard; `lms-backend` is selected from available CPU profiles.
2. Select a recent interval containing traffic (or a saved absolute interval).
3. Click a stack in **Flame Graph** to focus; use **Top Table** to inspect
   **Self** versus **Total** CPU. Search for a function such as
   `render_navigation`.
4. Use the timeline to identify intervals; compare different intervals via the
   time picker. This is interval comparison, not a provisioned differential view.
5. The header link returns to request tracing to investigate I/O/latency.

There are no datasource selectors. The single Service selector is intentional:
this backend supports more than one explicitly instrumented service.

## Deployment and access

- Argo app `profiling`, chart `charts/profiling`, namespace
  `cattle-monitoring-system`.
- Pyroscope **2.4.2**, digest-pinned multiarchitecture image, v2 filesystem
  storage, one replica with a persistent 5 GiB `local-path` PVC, 7-day retention.
- Non-root, read-only root filesystem, dropped capabilities, no service-account
  token; 1 GiB memory / 1 CPU ceiling, GOMEMLIMIT 768 MiB.
- ClusterIP only: **no public ingress, external IP or NodePort**. NetworkPolicy
  admits port 4040 only from selected LMS and Grafana pods/namespaces. Egress is
  DNS only; internal single-process components connect within the pod. No
  telemetry statistics or Pyroscope self-profile push.
- Grafana UID `pyroscope` comes from a separate labelled ConfigMap watched by
  the existing datasource sidecar. The Loki/Tempo mTLS Secret and its credential
  refresh are unchanged; this is not a second OTel trace collector/sampler.
- The existing Grafana administrative network/access policy applies. Treat
  function names and paths as internal code metadata even without request data.
- A single local-path replica is not HA or an off-node backup. PVC contents
  survive pod restarts, not loss of the storage node; no automatic destructive
  prune or PVC deletion is configured. The size request is not a filesystem
  quota on local-path storage; monitor actual disk usage.

## Opt-in, extension and rollback

LMS defaults **off** (`profiling.enabled: false` in chart defaults). Production
opts in in `deploy/lms/values.yaml`; this sets `LMS_PROFILING_ENABLED=1` and an
explicit internal `LMS_PROFILING_ENDPOINT`. Application settings are validated;
SDK startup failure logs a generic error without making the LMS unavailable.
SDK import and background sampler are absent when disabled. Profile export
failures cannot be interpreted as success: check actual profile arrival.

To stop LMS profiling, set `profiling.enabled: false` in production values and
sync/roll out LMS; retain the Pyroscope PVC for analysis. Removing a Grafana
panel does not disable sampling.

To add a service, first choose its runtime integration (Python SDK, Go SDK/pprof,
Java integration, etc.), confirm labels contain only low-cardinality service
metadata, bound sample rate/resources and expand the NetworkPolicy to exactly
that service's namespace/pod selectors. Do not grant all namespaces, host PID
access or privileged eBPF access as an implicit prerequisite. Instrumenting
another Python service requires installing the pinned SDK there; setting an
environment variable alone is not enough.

## Verification

```sh
helm lint charts/profiling
helm lint charts/lms -f deploy/lms/values.yaml
uv run --python 3.13 --with pytest --with pyyaml --with jinja2 --with cryptography \
  python -m pytest -q tests/test_cpu_profiling.py tests/test_lms_observability.py
LMS_CHECKOUT=/path/to/lms node scripts/lms-grafana-cpu-canary.mjs
```

The browser check opens the **bare dashboard**, verifies a native Pyroscope
stack dataframe with nontrivial rows, switches to Top Table, finds a real
`render_navigation` function, switches back to Flame Graph and renders the CPU
timeline. It rejects JavaScript exceptions and datasource failures.

An optional explicit traffic check:

```sh
python3 scripts/lms-cpu-profile-verify.py --create-canary-session \
  --output /tmp/lms-cpu-profile-result.json
```

This creates a synthetic 5-minute teacher session, performs sequential GETs of a
real lesson for 20 seconds at no more than 10 requests/second, and deletes the
identity (cascading sessions) in `finally`. It never uses an actual user's
identity or submits solutions. Do not run it when the LMS/database node is
unavailable. No session value or raw profile is persisted. It is a bounded
functional canary, **not** an overhead or load-capacity benchmark.

If a node outage interrupts cleanup, investigate the node and delete only the
reserved synthetic identity after the database is available. Its issuer is
`urn:homelab:lms-cpu-canary`, name `CPU profile canary`; no real Authentik users
have that issuer. Use `Store.connect()` and delete the matching row in `users`:
`ON DELETE CASCADE` removes its sessions. Session TTL still limits access even
if the profile row has not yet been removed. Do not delete real teacher accounts
or bypass authentication to make a profile check pass.
