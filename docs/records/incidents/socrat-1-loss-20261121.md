# Socrat: a sudden loss of socrat-1 without drain — 21 November 2026

**Verdict: a partial success, not a full fault-tolerance acceptance.** Control via `0` stayed available. PostgreSQL switched to `5`, the user returned to Authentik and Grafana while `1` was still unavailable. The Thanos 5m history was read again from `0`. But some singleton services did not become ready before the node returned; the delivery of a real alert to Telegram is unconfirmed. This is a check of the loss of **only `1`**, not `0`, not any one and not two nodes.

## What was prepared and where the source of truth is

- Three voting etcd — `0/1/2`, the control plane also on `5` without etcd. On losing `1`, both remaining votes are needed. DNS is spread over `0/3`; two Query and two monitoring probes are kept as exceptions, not a general doubling policy. The Metrics Server, operators, proxies and service jobs were untied from a mandatory placement on `1` where this was verified (#184–197).
- Standardly on `1`, one instance each: Loki, Tempo, Pyroscope, Alertmanager, Shelf/Store/Compactor for Thanos 5m. `0` is also allowed for them. **Allowed nodes are not a replica count.** Raw and 1h were not moved. The 5m roles are separate, Store mounts the directory read-only.
- The data is on NFS, which **serves `0`**. The PVCs `tempo-s1-candidate`, `loki-s1-candidate`, `pyroscope-s1-candidate`, `thanos-5m-s1-candidate` (only `active/`) and `alert-state-nfs-alertmanager-kube-prometheus-stack-alertmanager-0` are **production**, not scratch. The old local copies and archives are kept; do not run a writer on them after new records. `Retain` is not a backup.
- Migrations: stopping the writers → an independent cold archive/restore → a tree comparison → one writer → the old and new data at the application level. For Loki the transition was interrupted twice without launching a writer on an unverified target. For 5m the cascade was also stopped; the free space was checked on the **filesystem of the active NFS**, the size counted without the old copy. Details: [Alertmanager](../../../deploy/storage/alertmanager-nfs/README.md), [Tempo](../../../deploy/storage/tempo-drill/README.md), [Loki](../../../deploy/storage/loki-drill/README.md), [Pyroscope](../../../deploy/storage/pyroscope-drill/README.md), [Thanos 5m](../../../deploy/storage/thanos-5m-drill/README.md).
- Before the drill, changes in `main` had already been returning the old `hostPath` (#278 and merge #320 `82c5d7a0`). `Synced` then **did not mean the right volume**. The last restoration before the experience: `5770dac7` (stop), `c79c6965` (verified identical trees, 12 paths), `432e90cd` (resuming the schedule). Before the power-off, seven real pods were Ready on `1`, not pre-placed on `0`.

## Chronology (UTC, Moscow = UTC+3)

Direct API reads via `0` and cuts roughly every 15 seconds; external HTTP probes checked ordinary DNS and a forced HOME. The times are the first observations, not the exact hardware-event time. Routing to login, Kubernetes status, a successful SQL and a user confirmation are different verification levels.

| UTC | Observation |
|---|---|
| 12:40:17 | The last Lease update from `1` before the loss. There is no exact button-press time. |
| 12:41:39–40 | `unreachable` with `NoExecute`/`NoSchedule`, `Ready=Unknown`. The other five nodes Ready. The API `/readyz` via `0` passed in all cuts of the loss interval. |
| 12:41:55–12:42:17 | The user lost Grafana and Authentik. The HOME VIP is already on `0`; Grafana on `5` gave `302`, but Authentik on `0` was not Ready and returned `503`. On `pg-critical-rw` the old endpoint on `1` is not ready. The DB switch began, `pg-critical-2` was chosen as the target. |
| 12:42:25–12:43:20 | The first observation of a new primary on `5`; the write endpoint is ready. Direct SQL: not in recovery, `transaction_read_only=off`. A production test transaction was not performed. The replica on `0` continued streaming. |
| 12:43:00–20 | The user could not open Open WebUI. The pod on `5` stayed Running, but without a ready endpoint; then `/` returned `200`, later `/health` and `/api/config` also `200`. Opening a chat/sending a message is unconfirmed. |
| 12:44:11 / 12:44:55 / 12:45:26 | The first external `200` of the Authentik login page / a user confirmation via Authentik was recorded / via Grafana. The `302` of Grafana itself was not earlier counted as recovery. There is a correlation with the DB, the single cause of the applications' idleness is not proven. |
| 12:46:39–12:47:10 | The 300 seconds of unavailability tolerance after the taint expired. Replacements appeared on `0`. The first strict 5m read in the sampling — `12:46:55`, a separate repeat confirmed `900` and negative controls. |
| 12:56:55 | In Prometheus `KubeNodeNotReady` was first observed **Firing**, previously Pending from `12:41:55`. This is **not** proof of delivery. |
| 13:00:55 | `1` Ready again (from the last Lease ≈20min38s, not the agreed maximum 30 minutes). Do not count the processes that came alive after this as success during the loss. |
| 13:01:25 | The alert stopped being observed as Firing. There are no confirmations of receiving a firing **or** resolved from the addressee in this drill. |
| 13:01:05–13:07:10 | The former primary returned as a replica: `pg_rewind` from the common checkpoint, 599 MB had to be copied; 13:06:53 completed, 13:06:54 streaming on timeline 4, at 13:07:10 the sampling shows 3/3. The primary stayed on `5`; both replicas were checked via `pg_stat_replication`. |

## What actually worked while 1 was powered off

| Component | Result and proof boundary |
|---|---|
| Control, DNS, login | The API via `0` worked, the etcd readings matched two surviving members, DNS from n8n resolved the Kubernetes Service. One request to the etcd metric ended with an error, this is not an API failure. The HOME VIP moved; a direct public VPS login from the workstation gave a timeout and did so before the drill too. |
| PostgreSQL | A new write-available primary within ~2–3 minutes from the last Lease, without a manual promote. This is not zero downtime, not a check of client-transaction retries and not proof of no losses at each application's level. |
| Thanos Store / Compactor 5m | The Store on `0` Ready and the control historical query through a **specific** Store gave `900`; raw-only and an absent Store are empty. The Compactor Ready on `0` by 12:47:10. A new block or a compaction pass in this window is not proven. |
| Loki / Tempo | Both pods Ready on `0` by 12:47:10. Recovery about ~7 minutes from the last Lease, **later than the proposed 5-minute benchmark**. There is no paired check of the exact history and a new record during the outage itself. The later checks after the return are separate. |
| Pyroscope | The replacement started on `0`, but in the valid cuts before `1` returned it was not Ready. The first Ready on `0` at 13:01:10. The presence of a process does not prove the availability of profiles. |
| Thanos Shelf 5m | A ready replacement on `0` was not observed. At 13:01:10 Ready again on `1`. The Store working with a shared history is not proof of the Shelf working or of block upload. |
| Alertmanager / Telegram | The singleton StatefulSet stayed Terminating on the unavailable `1`; a ready replacement on `0` was not observed. After the return, Ready again on `1`. Before the drill, the test route delivered Telegram; in **this** drill an end-to-end delivery is not proven. |

Artifacts: a local log of cuts, HTTP statuses, warnings and user marks; the raw data is not versioned. Some polls had timeouts — a skipped cut is not equal to a vanished pod. Do not save into Git log bodies, trace IDs, profile symbols, credentials. Before the drill there were OTel metric enqueue failures even with all nodes Ready. You cannot promise the continuity of all telemetry from this experience. LMS data/DB, the local Docker certification runner, the loss of `0` and the simultaneous loss of two nodes are outside the acceptance.

## Automatic return after the drill

On a node's recovery, the standard scheduler **does not evict** healthy pods from `0`. An official [Descheduler: chart and operation](../../../charts/descheduler/README.md), [Argo owner](../../../deploy/argocd/apps/descheduler.yaml), version 0.36.0 for Kubernetes 1.36, was added. Commits `7bd877d2` (dry-run) and `1cf4cb95` (schedule). This is a GitOps upstream installation, not a homegrown controller and not an emergency failover mechanism.

A CronJob every 5 minutes, at most one actual eviction per pass per cluster; `nodeFit`, pod age ≥15 minutes, PDB and profile constraints. The pod age is **not** a stability timer of a recovering node. Only a *declared preference* is considered, a return to a specific host is not guaranteed. The common profile excludes PVC/local storage and a number of system namespaces; a separate permission — only verified NFS Deployments. Alertmanager and CloudNativePG are not managed by these profiles. Restarting a singleton gives another brief break, and the schedule itself does not check the health of the previous application.

Verified returns to `1`: Tempo — a real control run at 13:17, after which the old/fresh Tempo and Loki data were read; Store 5m — **the standard schedule 13:20**, `900` was received again; Compactor 5m — **13:25**, a new pod Ready. Loki — **13:30**, a standard eviction and a new Ready pod on `1`. At this cut Pyroscope is still Ready on `0`; an expected next pass is not a result. To check progress, look at `Evicted pod` / `totalEvicted` in the completed Job's log and a **new Ready pod on the target node**, not the eviction-attempt line.

## What to fix and how to close it

1. **Alert delivery without `1` is the main open criterion.** Design an independent path or an agreed HA Alertmanager. Do not force-delete a StatefulSet on an unavailable node without fencing. On a repeat, obtain the real firing and resolved time at the addressee.
2. **Separate waiting and start:** 300 seconds after the taint already exhaust the 5-minute RTO. Agree on the RTO from the loss moment, then check the settings only for specific roles; do not shorten the tolerations of all writers and do not create two active writers.
3. **Pyroscope and Shelf:** analyze readiness, events and revision changes; prove a new profile query and the Shelf's standard work *before* the node returns. Do not confuse it with a control Store read.
4. **Application dependencies and monitoring:** repeat a fresh MFA login, reading an existing chat and a safe consistent write check via `pg-critical-rw`; separate the absence of ingress, readiness and DB availability. Analyze the OTel overflow separately. Monitor the `main` changes by the render result: the active PVC and both allowed nodes must be preserved.
