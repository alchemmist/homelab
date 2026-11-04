# Metadata-only logging coverage acceptance

`scripts/logging-coverage.py` complements (does not replace) the existing
`otel-log-delivery-matrix.py`. It performs only Kubernetes GETs and Loki instant
metric queries. It never calls a log-stream/range endpoint, prints kubectl stderr,
or saves source log bodies. Do not attach TLS files, raw pod inventory, journal
output or HTTP errors to evidence. Treat source identities in the report as
operational metadata; distribute only through the approved evidence channel.

## Run

Run on an existing trusted admin host with read-only Kubernetes access and the
existing native Loki mTLS files. Do not copy credentials into this checkout.
The default certificate directory is `/var/lib/homelab-otel/tls`; file names are
`ca.crt`, `client.crt`, `client.key`. The default Loki origin is
`https://10.250.0.3:3100`; verified TLS is mandatory. No dependency installation
is needed (Python standard library).

Create a private, independently reviewed host registry, for example:

```json
[
  {"host":"node1","unit":"k3s.service","exists":true,"emission":"expected"},
  {"host":"node1","unit":"example-idle.service","exists":true,"emission":"silent"}
]
```

This is an example, **not** the homelab inventory. Build the real registry from
all managed hosts' enabled/running service metadata and Ansible declarations,
including non-Kubernetes machines. Do **not** mark every installed, enabled or
running unit as an expected emitter: installation/running state is not evidence
that a unit writes logs in the observation window. Retain inactive units as
`exists: true, emission: unknown`; do not silently remove them from inventory.
`expected` needs a reviewed application-specific emission expectation.

Alternatively pass `--host-inventory /private/path/service-facts.json` instead
of `--hosts`. This accepts normalized, metadata-only Ansible `service_facts`
snapshots (not full Ansible output):

```json
[
  {"host":"node1","services":{
    "k3s.service":{"source":"systemd","state":"running","status":"enabled"},
    "idle.service":{"source":"systemd","state":"stopped","status":"disabled"}
  }}
]
```

Use the canonical `host_name` emitted by the collector, not an SSH inventory
alias unless identical. Gather service facts on every managed systemd host using
existing approved read-only inventory access; retain only the host identity and
`ansible_facts.services` mapping, never full task output or credentials. This
mode includes all inventoried systemd `.service` units (including inactive ones),
marks existence true and **all emission expectations unknown**. It does not SSH,
install software or mutate hosts. Non-systemd entries are excluded; supplement
those sources through the explicit registry. Reconcile snapshot age, missing or
unreachable hosts, transient units and application-specific expectations manually.
Neither mode proves inventory completeness.

A host entry's `exists` is an operator
attestation, not an SSH probe. Omit or set null when unconfirmed. `silent` requires
an independent documented reason; absence in Loki never establishes silence.
An empty registry does not establish host coverage.

```sh
python3 scripts/logging-coverage.py --hosts /private/path/host-units.json \
  --output /private/path/coverage-before.json
python3 -m unittest discover -s tests -p 'test_logging_coverage.py'
python3 -m unittest discover -s tests -p 'test_otel_log_delivery_matrix.py'
```

Output must not already exist; creation mode is 0600. Summary stdout contains
counts only. Queries are exactly four (Kubernetes and host, each for 10 minutes
and one hour), with concurrency two, no retries, 15-second HTTP timeouts, 8 MiB
response and 10,000-series limits per query. Kubernetes GETs have 15-second server
and 20-second subprocess timeouts. Failures/partial responses fail closed with
sanitized errors. A server-side configured query timeout should additionally
bound backend work. Run at a quiet enough cadence to avoid query load.

## Interpretation and acceptance gates

* `exists`: controller metadata was inventoried, including zero-replica workloads
  and Jobs/CronJobs without current pods. Inventory all namespaces; no service
  allowlist hides missing workloads. Container inventory includes init and
  ephemeral containers, including completed pods returned by the API.
* `emits`: positive recent Loki count for the exact pod/container or host/unit;
  this proves delivery, not source-side logging completeness.
* `verified`: every matching recent series has nonempty canonical `host_name`
  and `service_name`, exact source identity (namespace/pod/container for Kubernetes;
  host/unit for host sources), and a valid `severity` (`trace/debug/info/warn/error/fatal/unknown`). Explicit
  `unknown` is valid; missing severity is not silently interpreted as info.
* `silent`: only an explicit registry emission expectation, with no recent count.
* `unknown`: no recent matched evidence; includes one-hour-old delivery, stopped
  init containers, idle services, missing metadata and possible broken collection.
  Investigate; do not call these verified or broken based only on this report.

`fresh` means a positive count within ten minutes, not the Loki evaluation
 timestamp. `deliveredInHour` distinguishes stale evidence. `legacyObserved`
means at least one recent matching series fails the canonical contract, including
mixed valid/incomplete series. `canonical` is true only when all matching positive
recent series satisfy it, so a valid row cannot mask missing host metadata.
Kubernetes pod/container and systemd identity are extracted from structured
metadata into temporary aggregation labels; they need not be indexed labels.
Legacy host `service_name == unit` remains accepted for matching. Older streams
without exact pod/container metadata cannot be attributed and remain unknown,
not falsely declared absent. Canonical and legacy matching is deliberately
separate from existence. Unknown severity satisfies schema only, not accurate
severity extraction; review severity distributions separately.

The tool deliberately leaves `fullCoverageAccepted` and `hostInventoryComplete`
false. It cannot independently prove a host registry complete, infer expected
emission for every application, attribute controller ownership, verify deleted
pods, or prove logging survives restart/rotation. Acceptance requires a reviewer
to reconcile all controllers with their pods (including scaled-to-zero and
completed Jobs), all host units, and each unknown/silent source with independently
reviewed expectations. Preserve old and new reports, timestamp, revision and
counts; do not include bodies. Compare before/after with workload churn noted.

## Separate restart and rotation gates (not run by this tool)

No restarts, rotation or live changes are authorized in the implementation phase.
Following separately approved rollout, capture a baseline, then perform these as
**two distinct checks** on a disposable canary, not app databases or metrics:

1. **Restart:** record canary identity and restart timestamp; use the approved
   rollout mechanism to restart only the chosen collector/canary. Confirm counts
   for an independently known emitting source before and after recovery. Record
   interruption duration, identity changes, counts, and acceptance or unknown.
2. **Rotation:** on a disposable source with approved rotation mechanism, record
   metadata-only file identity/size and rotation timestamp; confirm emission
   before and after the boundary and after collector position recovery. Do not
   truncate or rotate production application/DB files for this test. Record any
   duplicate/loss measurement limitations; positive counts alone do not prove
   exactly-once delivery.

Attach separate signed results; `restartCheck` and `rotationCheck` remain
`not_run` in automated reports. Rollout must also supply measured disk headroom,
retention enforcement, collector health and Grafana UI checks from their owning
runbooks; this verifier neither mutates nor certifies those components.
