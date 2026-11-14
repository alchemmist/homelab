# Moscow cloud-init and HOME0 Prometheus memory — 2026-11-14

## Scope and root causes

Owner authorized privileged Moscow diagnosis/repair and investigation of page
faults. Power warning on socrat-1 is explicitly acknowledged; leave it and its
alert rule unchanged. Never publish cloud user-data or passwords.

### Moscow: repeated initialization of active swap

Private privileged reads identify provider `/etc/cloud/cloud.cfg` bootcmd:
`dd if=/dev/zero of=/swap.img bs=1MiB count=512`, `mkswap`, `chmod`, `swapon`.
The bootcmd module runs every boot, not once. It succeeded initially and failed
on later November 9 boots: active swap rejects rewriting with `Text file busy`
and repeated activation with `Device or resource busy`. This is not evidence of
a present WireGuard, k3s or network initialization failure.

The 512-MiB swap file is already active and persisted in fstab/systemd. Two
identical fstab rows were observed; no fstab cleanup is part of this repair.
No other system/instance bootcmd owner was found. Provider user-data contains
account configuration and is retained privately, not copied into this document.

`scripts/cloud-init-swap-repair.py` guards the exact provider commands, active
swap, expected size and persistent definition. It adds only
`/etc/cloud/cloud.cfg.d/99-homelab-preserve-swap.cfg` with `bootcmd: []`.
Systemd/fstab retains swap activation; do not recreate or reformat active swap.
It validates only `cloud-init single --name bootcmd --frequency always`, verifies
swap inode/mtime/size and unchanged provider config/fstab, then resets only the
two stale service failed flags. It does not start all provisioning stages,
reboot, touch SSH/users/passwords/networking, or erase historical cloud-init
result files. Historical `cloud-init status` may therefore still describe the
old boot failure, even after the corrected module succeeds. A future reboot is
not performed or claimed accepted here.

Private root before/intent/acceptance receipts:
`/var/lib/homelab-recovery/20261114-cloud-init-swap/`. One-shot: never blindly replay.

### HOME0: cgroup ceiling, not host-wide swap thrashing

A major page fault requires loading a page through I/O. It can be an mmap-backed
TSDB file, not just anonymous memory returning from swap. The generic alert
checks >500 major faults/s for 15 minutes; it does not measure swap alone.

Observed before repair:

- Node has about 7 GiB MemAvailable and no swap-in/out in the 5-minute metric
  window and bounded vmstat sample; swap allocated is not the same as swapping.
- Process sample attributes roughly 589 major faults/s to Prometheus, not the
  sampled k3s-server or OTel processes; host 5-minute rate is around 940/s.
- Prometheus cgroup `memory.max=3221225472` (3 GiB), current usage at the ceiling,
  anonymous usage about 2.76 GB, file cache about 394 MB, millions of memory.max
  events, substantial direct reclaim and file refaults. No OOM kill recorded.
- Prometheus CR/StatefulSet declare 8-GiB limit, but CREATE-time admission still
  injects the old 3072-MiB limit and 2048-MiB request. This explains why Argo
  Healthy and chart values did not reveal the real pressure. cgroup counters
  establish actual reclaim pressure, not merely a speculative interpretation of
  node page-fault counts.
- Short-window query inner-evaluation means are ~36 ms on Prometheus, queue
  means ~21 microseconds; this is not a full latency or loss acceptance.

Correct only the Prometheus profile's two RAM scalars in the existing native
admission policy, with UID/resourceVersion/expression tests. Preserve every
other profile, CPU/ephemeral/GPU setting and the existing binding. Native server
Pod dry-run verifies replacement admission. Correct the running Pod through the
native resize subresource with UID/RV/resource tests and NotRequired memory
restart policy; do not evict or restart it or edit the StatefulSet.

Target: **3-GiB request / 8-GiB limit**. The authoritative budget catalog request
is adjusted 4→3 GiB while retaining its existing 8-GiB ceiling. The upstream
operator template request is not changed because that could trigger a rollout;
as documented in resource-budgets, actual Pod resources belong to admission.
The old 2-GiB request is below the current ~2.6-GiB anonymous baseline. A full
4-GiB request would exceed current node reservations by about 18 MiB, so it is
not applied blindly. A 3-GiB request fits: preflight projects 32,270,974,976
requested bytes of 33,326,227,456 allocatable, leaving 1,055,252,480 bytes.
This is scheduler accounting, not a guarantee against simultaneous workload peaks.

`scripts/prometheus-memory-repair.py` refuses unknown budgets, unsupported or
restart-requiring resize, insufficient node reservations or a prior receipt.
It stages alongside the existing tested `check-resource-budget.py` to account
for regular/init/sidecar/Pod-level requests. Server validates both patches before
mutation. An admission behavioral-check failure rolls back the expression before
Pod mutation. Any subsequent failure is retained for inspection, not auto-replayed.
Private receipts on socrat-0:
`~/.cache/homelab-recovery/20261114-prometheus-memory/`.

No data deletion, retention/compaction/scrape changes, extra scraper, cache drop,
swapoff, warning suppression or database migration is part of this change.

## Preflight and validation

43 tests passed covering guard failures, indentation-independent CEL scope,
resource UID/RV tests, unchanged non-RAM settings, restart refusal, capacity,
existing budget logic and monitoring storage guards. Both host preflights passed.
The first Prometheus preflight refused unsupported indentation **before mutation**;
parser was hardened for the actual renderer and regression-tested.

Applied and post-change evidence is appended only after actual execution.

## Applied acceptance

Source repair `493de518`; admission-propagation hardening `80ce10ab`.

Moscow repair completed: corrected bootcmd module exit=0; original swap inode,
mtime and size preserved, swap remains active, fstab/provider config unchanged.
Both cloud-init units are now inactive/Result=success rather than failed; k3s
agent remains active. The two systemd-failure alerts cleared. Historical
cloud-init result files were not rewritten to pretend the old boot succeeded.
No full provisioning replay or reboot was performed.

The first memory apply correctly rolled admission back before Pod mutation when
an immediate future-Pod check still saw old settings. Independently verified
exact policy spec restoration and unchanged live Pod budgets. Hardening adds a
bounded 20-second dry-run convergence check and a single explicitly guarded retry
only after the prior exact rollback/no-Pod-mutation receipt. On the reviewed retry,
recorded admission responses were **2Gi/3Gi, then 3Gi/8Gi**, demonstrating actual
cache propagation rather than assuming that an API patch was immediately active.
The retry changed only the two approved RAM scalars; a full spec comparison
confirmed no unrelated admission policy change.

In-place resize accepted and effective runtime independently verified:

- same Pod UID `0eac998e-c6a5-40b0-8627-fb27737de9a8`;
- same container IDs, start times and restart counts for all four containers;
- same Prometheus PID 1442661, Ready=true;
- actual cgroup `memory.max=8589934592` (8 GiB), request 3 GiB;
- first 5-second process sample ~61.8 major faults/s versus ~589/s before;
- no new cgroup memory.max events in that sample;
- cgroup memory PSI avg10 about 0.07% after versus 5.62% before;
- later independent all-process sample: host ~0.2 major faults/s, no swap in/out;
- at 12:30 UTC node 5-minute major-fault rate ~4.14/s versus ~940/s before,
  swap-in ~0.119 pages/s, swap-out zero. `NodeMemoryMajorPagesFaults` cleared
  without changing its threshold, expression or duration.

Short-window mean query evaluation improved from ~36 to ~24 ms, queue means
remained negligible. The samples support repair of the observed cgroup cache
thrashing; they are not long-term capacity or workload-peak guarantees. The
reservation preflight at apply left about 1.02 GB allocatable request headroom;
future added workloads still require a separate budget check.

The old scrape guard examined only the Prometheus CR and therefore could accept
8-GiB intent despite 3-GiB runtime. It now also reads actual admitted Pods and
container runtime status in the existing Ansible preflight. New tests reject
chart-8/Pod-3, spec-8/runtime-3 and missing runtime. Read-only live check passes.
No legacy Helm install or broad monitoring-role replay was performed.

Validation: **82 tests passed, 1 skipped, 12 subtests passed** across the repair,
budget, resource rollout and Prometheus guard suites. A broader ownership suite
has a separate pre-existing Grafana `public-web-grafana-policy` fixture hash
mismatch. Reproduced independently with HEAD test/fixture and unchanged HEAD
chart/deploy inputs; not masked or updated as part of this repair. YAML parsing
of the updated task/catalog passed; full legacy role execution was not used.

A separate concurrent socrat-5 migration source commit `8c919024` quiesces n8n
and PR Agent. At final inspection socrat-5 is Ready/SchedulingDisabled and n8n
Deployment desired replicas=0. The resulting n8n unavailable alert is distinct
from this memory repair; do not reverse that independent source intent. The
remaining observed alerts were on-battery (explicitly acknowledged by owner) and
n8n unavailable. All six nodes report Ready; this is not a claim that every
application is serving during the separate migration.
