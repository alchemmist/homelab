# socrat-5 runtime cutover attempt — 20 November 2026

## Outcome

**Not migrated.** Runtime remains on SSD at its original path. No destination
runtime directory, fstab entry, runtime bind or startup drop-in was created.
No application dataset was removed or restored. Host node was not rebooted.

Owner authorized proceeding over SSH without a fresh hypervisor capacity check;
physical backing capacity remains unverified, not a hard access prerequisite.

## Live checks and maintenance actions

- All three native etcd endpoint status requests succeeded with common leader
  and term33. Independent authorized TLS /readyz on node0/1/5 passed. The first
  generic /readyz request transiently failed etcd-readiness; direct checks passed.
- Node5 cordoned; 50 running CRI containers at initial preflight. No Running
  Job-owned Pods observed before maintenance.
- Attempted local container quiescence with K3s reconciliation temporarily paused
  (SIGSTOP on node5 server process), leaving containerd available for CRI calls.
  This also pauses the local API server: it is NOT an acceptable production
  migration method for this combined server process and must not be replayed.
- First attempt hit default short CRI client deadline; reconciliation resumed.
  Second attempt used longer CRI timeout but sandbox stop did not complete within
  the maintenance attempt. Paused process resumed and maintenance helper stopped.
- Readiness/lease interruption caused node NotReady and application/container
  restarts; LMS Pod replacement observed. Do not describe this as no-impact.
- Node returned Ready and was uncordoned. All API /readyz checks passed again.
- One-shot remote helper explicitly retired (immediate refusal and no executable
  permission) to prevent replay. Private root receipts retain intermediate logs.

## Acceptance limits

At the intermediate recovery check Grafana, n8n and most application Pods had
returned Ready; Rancher, DeeperSeeker and publisher were still recovering.
Final recovery status must be appended separately, not inferred from Node Ready.
Unrelated concurrent postgres/CNPG working-tree changes and new postgres join
Pod were observed and not modified as part of this maintenance.

## Revised requirement

Use a reviewed **complete** shutdown/boot-time migration procedure that does not
freeze the combined K3s API/kubelet process while CRI sandbox cleanup is active.
A service stop alone does not prove shims have stopped. Do not replace this with
manual snapshot deletion, forced Pod deletion, blanket killall/network cleanup,
or a live runtime copy represented as a cold consistent copy.

Before retry, verify application recovery and design/test the stop sequence.
Consider a boot-time one-shot before K3s after explicit reboot approval and
independent recovery/access assessment; that is not authorized/executed here.

## Recovery fixes published through Git

- `54a070d6`: allow Rancher cold startup up to 600 seconds while retaining
  readiness/liveness checks; publisher encoder installation replaces its pinned
  binary atomically so a repeated init does not write into a mode0555 file.
- `d43c0634`: Rancher proxy Deployment now reconciles in wave0 alongside backend,
  rather than wave-1 waiting for backend health before backend fixes can apply.
- Changes published from a clean detached worktree based on fresh origin/main;
  unrelated dirty worktree and concurrent CNPG/postgres changes preserved.
- Only Rancher/openhands Applications refreshed. The stuck Rancher operation
  terminated via its native operation-state mechanism so the new source revision
  could reconcile; no blanket sync/prune, image override, PVC deletion or secret
  rotation. Helm render passed with the actual kube-version1.36.5.
- Exact publisher ephemeral encoder file temporarily restored owner-write for
  init retry; no PVC touched. Git fix supersedes the one-off workaround.
- DeeperSeeker process and VPN start, but deep readiness returns upstream401
  invalid authorization. Credentials were not reset/rotated or printed, MFA not
  bypassed. External account reauthorization may be needed; cause not proven.

## Final runtime check

- Node5 Ready and schedulable; k3s active; migration unit inactive and retired.
- Rancher and OpenHands Argo Applications Synced/Healthy. New Rancher Pod Ready
  without restarts after ~3 minutes, validating the extended cold-start budget.
- 41 node5 Pods Ready at final snapshot. DeeperSeeker remains unready on external
  authorization401. A new concurrent Umami rollout was also still progressing
  at the snapshot; do not claim full cluster acceptance.
- Runtime findmnt still /dev/sda1; HDD runtime destination absent.
- Final df: SSD64GiB used/25GiB available (73%); HDD6.8GiB used. This change
  in root usage is not evidence of migration or a measured manual cleanup.

Later acceptance observation: Umami reached Ready and Synced/Healthy. Rancher
backend and public proxy Deployments both 1/1 Available, operation Succeeded and
source Synced, but Application aggregate health subsequently reported Degraded
without an unhealthy resource shown in the resource list. Do not erase this
status or claim complete Argo health acceptance; further aggregation diagnosis
remains open. Native workload readiness is positive, not proof of browser SSO.
