# socrat-1 loss without drain — the second drill, 21 November 2026

**Verdict: control, PostgreSQL replication, monitoring readiness and Thanos 5m history reading were restored or kept without manual intervention. External access was not continuous. Telegram delivery is unverified:** the node returned before the rule's for-duration. This is a separate experience, not a continuation of the 30-minute window and not a check of an arbitrary single-node loss. For comparison — [the first drill](socrat-1-loss-20261121.md).

## Conditions that distinguish this run

- Before GO at 13:36:39 UTC six nodes Ready; the API via `0`, TCP between etcd `0↔2` and DNS from n8n were verified. All seven chosen roles really ran on `1`. No drain; the operator powered the node off and back. The portable data stays on the NFS of node `0`; this is not a storage-failure test.
- Primary `pg-critical-2` is already on `5`, synchronous streaming replicas on `0` and `1`, a zero lag in the initial cut. A replica loss is expected here, **not** a promotion, unlike the first run. No PostgreSQL changes or manual primary switch.
- The GitOps change `3424b0a2`: [a temporary second Alertmanager](../../../deploy/storage/alertmanager-nfs/cutover.values.yaml), mandatory host spread, a separate retained RWO PVC per ordinal. Both saw two members, Prometheus discovered both addresses. This is a surviving-member check, **not proof** that a singleton StatefulSet moves off an unavailable node.
- [The Pyroscope startup probe](../../../charts/pyroscope/templates/backend.yaml): a 4s request timeout, 120 attempts with a 5s period instead of 36 attempts. This gives time for a cold start, it does not declare the pod ready earlier. Before the power-off, the historical profile matched by total and character count; Loki and Tempo returned historical and fresh data. For 5m the initial result was `900`, the negative controls empty. Five Argo applications Synced/Healthy, the cascade schedule enabled.

## Chronology by independent probes (UTC; Moscow = UTC+3)

The time means the first observation unless stated otherwise. Between cuts, the state could have changed earlier. The last Lease is not the exact button-press time.

| UTC | Observation |
|---|---|
| 13:47:56 | The last update of Lease `1` before the power-off. |
| 13:48:12–30 | The first timeouts of external HTTP probes on part of the routes. At 13:48:28–30 all three names (Grafana, Authentik, Open WebUI) with no HTTP answer both via ordinary DNS and via a forced HOME. `000` is a curl result without an HTTP code, not a server `503`. |
| 13:48:13 / 13:48:28 | A strict Thanos 5m query first ended with a probe error, then returned an empty result. Do not interpret either as block deletion. |
| 13:48:44–13:49:18 | The external paths recovered non-simultaneously. The first `200` of the chat via DNS at 13:48:44; at 13:49:00 Grafana already gave `302`, but Authentik via DNS had not yet answered. By 13:49:18 both paths give Authentik `200`, chat `200`, Grafana `302`. When checking from `0`, the HOME VIP was on `0`. |
| 13:48:51 / 13:48:58 | `unreachable` with NoSchedule/NoExecute; the first cut Ready=Unknown. The DB at 2/3, the primary the former one. |
| 13:49:10 / 13:49:28 | A direct Alertmanager check on `0`: ready, one visible member. On the primary a quorum streaming replica `pg-critical-3` was kept. The first cut `KubeNodeNotReady` Pending. |
| 13:53:51 | The computed expiry of the 300s `unreachable` tolerance; this is the waiting boundary, not a readiness moment. |
| 13:54:14 | On `0`, Loki, Pyroscope, Shelf 5m and Store 5m are ready. A strict sampling of the historical 5m again gave `900` **before `1` returned**. |
| 13:54:29 | On `0`, Tempo and Compactor 5m are also ready. All six moved roles ready about ~6min33s from the last Lease (~5min38s from the taint). The five-minute-from-loss benchmark is still not reached. |
| 13:58:14 / 13:58:29 | The last Unknown / first Ready cut of `1`; from the last Lease to the first Ready about ~10min33s. Again two Alertmanager members, the etcd metric returned from two observed members with a leader to three. |
| 13:58:44 / 13:58:59 | PostgreSQL again 3/3, both replicas visible in `pg_stat_replication`; then Pending stopped being observed. `Firing` was not observed. |
| 14:01–14:03 | All six nodes Ready, both Alertmanagers ready on different hosts, the other six roles ready on `0`. The primary on `5`, both replicas streaming/quorum, a lag of 0 bytes in the check. This is a recovery cut, not a promise of permanent placement. |

## What is proven and what is not

| Area | Conclusion and check limit |
|---|---|
| Control plane | `/readyz` via `0` succeeded in **38/38** Ready=Unknown cuts. The etcd metric and the API availability are compatible with a working `0/2` quorum; readings once per ~15s do not rule out short failures between them. With two remaining votes there is no margin for another failure. |
| PostgreSQL | The primary did not change. A direct SQL on the primary showed `not pg_is_in_recovery()` and `transaction_read_only=off`; the replica on `0` stayed available. This is not an end-to-end confirmed application write via `pg-critical-rw`. |
| User login | There was a brief external break **without** a DB failover. PostgreSQL failover by itself does not explain all the network pauses in the two experiences. The HOME VIP was later found on `0`; the exact cause (VIP/ARP, routing, ingress, another segment) the data does not establish. A fresh MFA login and a user opening an existing chat were not confirmed in this run. |
| Loki and Tempo | Readiness on `0` is proven during the loss of `1`. **After the return** Loki gave the exact old line and real fresh logs, Tempo — a completed historical trace and fresh traces. This is not a check of continuous ingestion every minute of the outage. |
| Pyroscope and Shelf | In the first experience, readiness with `1` powered off was not reached/noticed. Here both roles are ready on `0` already at 13:54:14. An improvement is observed, but it does not prove the causality of the probe change. There is no separate confirmation of a new profile's ingestion or a new Shelf block in this window. |
| Thanos | The return of `900` via the chosen Store 5m is proven during the outage. After it, `sum(count_over_time(up[1h]))` was repeated at Unix `1792785600` with `partial_response=false`, resolution `5m` and a filter of the specific Store; a nonexistent Store and raw-only (`0s`) returned empty. The Compactor being Ready does not prove a compaction pass. |
| Notifications | The surviving Alertmanager was polled directly and stayed available. Over 38 Unknown cuts the rule was observed Pending in 36, Firing — never. The node returned before the 15-minute for-duration. **Neither a firing delivery nor a resolved one to Telegram was accepted by this experience; this is not evidence of a delivery failure.** The previously observed bot response timeout on `/start` is a separate incident. |

## Observation and further actions

Local sources: `samples.jsonl` (the API via `0`, nodes, pods, endpoints, events, SQL, Prometheus/Thanos), `web.tsv` (ordinary DNS and a forced HOME), `detail.jsonl` (the direct status and alerts of the surviving Alertmanager, send metrics, replication, LAN probes), `observations.txt` (the obtaining of operator marks). On the workstation the directory is given in `/tmp/socrat-loss2-latest`; these are temporary artifacts, not an archive. A skipped poll is not equal to a failure. Only aggregates are left in Git, without message contents, log bodies, credentials, real trace IDs or profile symbols.

1. **Bring it to the recipient:** a separate agreed window longer than the rule's for-duration plus grouping/delivery. Correlate Prometheus Firing → an alert on the surviving Alertmanager → n8n → the real Telegram time → resolved after the return. Do not shorten the production rule to retroactively "accept" this experience. After the check, separately decide the fate of the temporary second member; do not delete the retained PVC.
2. **Analyze the external pause:** simultaneously record the VIP/keepalived transition, the TCP/TLS/HTTP labels via LAN, HOME and ordinary DNS from an independent external point. Separately record a fresh login and access to an existing chat. Do not consider an HTTP redirect a working user session.
3. **Prove the applications work in the window itself:** check the old and new logs/traces/profiles, a standard Shelf ingestion and a safe consistent write via the RW service. Analyze separately the delays from Lease to taint, from taint to eviction and from creation to Ready; do not shorten the tolerances of all writers without protection from a second active instance.
4. **Do not spread the acceptance:** a pod returning to `1` after recovery is separate Descheduler work, not part of an emergency RTO. The OTel enqueue-loss problem is not closed. The loss of `0` (the NFS server), the loss of two nodes, LMS and the local certification runner were not checked by this experience.
