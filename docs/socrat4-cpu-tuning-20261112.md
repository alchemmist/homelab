> **Superseded operational state:** Moscow became a native-primary host, outside
> Kubernetes, on12November2026. See [acceptance and rollback](moscow-native-primary-20261112.md).
> Historical evidence below is not a current cutover procedure.

# Moscow telemetry CPU tuning — 2026-11-12

## Scope and applied source

Owner approved optimization following investigation of
`SocratNodeResourceContention{node="socrat-4",resource="cpu"}`.
Only the native OpenTelemetry Collector was changed/restarted. No VPN, DNS,
WireGuard, k3s or node restart; no alert threshold/silence, CPU quota, memory cap,
log-filter or persistence change. Host-only migration is NOT performed.

Published source commits:6ebd8377 and60198204 (main). The owning production-agent
play now preserves a Moscow-only drop-in from
`ansible/files/otel/socrat4-cpu.conf`: `Environment=GOMAXPROCS=1`. Base service,
agent.yaml and scrape.yaml are unchanged, verified by SHA256 before and after.
Other hosts retain their existing configuration.

Applied only `ansible/playbooks/otel-socrat4-cpu-tuning.yml`, never the general
installer. Guards: exact hostname,1online CPU, pinned preimages, healthy Collector,
no loaded drop-ins. The first40second controller invocation timed out after
staging the override and before activation. Readback proved the old PID and
GOMAXPROCS2 remained active. Explicit guarded resumption accepted only the exact
reviewed unactivated file; subsequent run completed15tasks,1change,0failures,
0rescues. Runtime GOMAXPROCS1 and new PID verified. Temporary sudo credential
file removed. Private receipts: `/tmp/socrat4-cpu-tuning/`.

## Acceptance and limits

| Observation | Before | After |
|---|---:|---:|
| Sample duration |60s|300s|
| Collector CPU, percent of one core |2.42%|1.99%|
| Host CPU PSI some, interval average |33.80%|35.95%|
| WireGuard RX |1.56MB/s|2.17MB/s|
| Host CPU steal |6.09%|4.42%|
| Exporter queues |0|0|

These unequal-duration samples are NOT a controlled benchmark. Network RX grew
about39%; the lower sampled Collector CPU is not proof of a causal performance
improvement. **CPU contention is not resolved.** The5minute Prometheus ratio at
17:34UTC remained~35.5%, and the warning was still firing. No claim that small
telemetry tuning prevents recurrence.

Functional acceptance: Collector health200, PID stable for5minutes, restart
count0since activation; log and metric sent counters grew; refused counters0;
queues empty. Thanos host metric age~7s; Loki count-only query returned800new
Moscow records over5minutes using indexed `host_name="socrat-4"` (not `node`).
No private log bodies exported.13Python safety/regression tests and both Ansible
syntax checks passed. An existing test's stale4host count was replaced by an
exact comparison of issued role names with the owning bootstrap node registry;
RBAC wildcard and CA-private-key prohibitions remain tested.

Cgroup memory reached~254MiB near the unchanged256MiB cap after restart. Inspection
showed~90MiB anonymous memory and~162MiB file cache, including executable mappings;
OOM/OOM-kill counters0, host MemAvailable~376MiB. This is not a demonstrated
memory saving, and cgroup usage should not be confused with live Go heap. Do not
lower the memory limit/GOMEMLIMIT or discard persistent queues to chase a graph.

Separate DNS recovery follow-up: no `ALERTS` series for
AlertmanagerClusterFailedToSendAlerts at17:34UTC; this does not close CPU contention.

## Rollback

If telemetry regresses, remove ONLY
`/etc/systemd/system/homelab-otel-agent.service.d/20-single-cpu.conf`, daemon-reload
and restart ONLY homelab-otel-agent. Base service still contains GOMAXPROCS2.
Revert the corresponding source drop-in installation to prevent reapplication.
Do not remove storage, checkpoints, credentials or other drop-ins. The scoped
play automatically performs this narrow rollback if activation health fails.

## Substantial next step — separate network change

Do not expect another tiny monitoring adjustment to eliminate the warning.
Evaluate a deliberate Moscow host-only gateway migration or more CPU capacity.
Before host-only execution:

1. Inventory every pod/DaemonSet, listener, native fallback and controller on4.
2. Prove the native VPN candidate preserves ports, fixed targets, credentials,
   fail-closed policy and independent SSH/DNS/management; do not merely start it
   alongside the pod's existing listeners.
3. Prepare a reversible controller/fencing transition that cannot restart the
   pod or stop the native service after k3s is removed. Preserve existing keys.
4. Define maintenance/cutover and rollback acceptance, including real authorized
   VPN data-path validation, mesh/control-plane reachability and alert delivery.
5. Remove the worker role only after the native path is accepted. Never use a
   blanket drain/delete/stop of this transit node as an optimization experiment.

The CPU/packet-processing burden and provider steal remain even without k3s;
its removal is not guaranteed to put PSI below25%. Re-evaluate with comparable
traffic before changing the meaning of the alert.
