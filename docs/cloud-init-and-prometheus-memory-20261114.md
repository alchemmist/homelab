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
