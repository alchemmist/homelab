# Authentik: intermittent login latency and the November 22 outage

## Two distinct failure modes (UTC)

At 09:36:45 the `socrat-5` K3s cloud controller lost its lease after API timeouts and etcd client Range/deadline errors; K3s exited with status 1. It returned to active at 09:38:32. The node became NotReady and hosts `pg-critical-2`, the Authentik database primary. Authentik logged connection refusal to the RW Service; all three web replicas were at one point unavailable and the public endpoint returned 503. The database engine itself was not shown to have crashed. The initial cause of the control-plane timeout and the precise incident-time proxy rules are not established. Do not change etcd membership on this evidence.

Separately, while all three replicas were Ready, both blackbox probes repeatedly exceeded their 3 s deadline. In the hour sampled at 09:53 they succeeded 76% and 74% of the time. This is not an end-user failure rate. The public flow executor also exhibited multi-second latency. CPU reservation and longer liveness grace do not remove the database round trips.

## Read-only controls on the running system, approximately 10:27–10:30 UTC

From each actual web pod, use its normal database identity and verify-full TLS, keeping the verified host name constant and varying the dial address. Do not print a DSN, SQL parameters, cookies or credentials. Use read-only transactions and bounded statement/connect timeouts. Measure connection setup, eight sequential `SELECT 1` commands over one connection, and eight pipelined commands. Compare the Service IP with the current primary pod IP, alternating the order. Six rounds; median milliseconds, not tail estimates:

| Authentik node | TLS+DB setup (Service / direct) | 8 sequential (Service / direct) | 8 pipelined (Service / direct) |
|---|---:|---:|---:|
| socrat-5 (primary local) | 19 / 19 | 2 / 2 | 1 / 1 |
| socrat-0 | 415 / 426 | 515 / 598 | 73 / 84 |
| socrat-1 | 380 / 391 | 539 / 565 | 68 / 76 |

Bypassing Service translation did not resolve the latency. Pipelining removed most of the remote time without changing the operations or server. The same trivial read on the same primary was fast locally. This identifies **cross-node round trips multiplied by serial work** as a substantial latency mechanism, not a slow SQL plan. It does not prove packet loss, CPU starvation or a specific failing link. The Flannel VXLAN uses `wg-socrat`; the 1↔5 WireGuard path deliberately relays via 0 (see `wireguard-1-5-router-repair-20261116.md`). Do not undo the relay on speculation.

Four anonymous localhost GETs to the login flow executor per replica, interleaved with liveness GETs, all returned 200. Ranges: 1.35–2.21 s on 5; 2.42–4.03 s on 0; 2.47–5.29 s on 1. Larger values were observed earlier. Django counters advanced concurrently with background probes; their deltas are **not** exact per-login query counts. In this version Django pooling is explicitly disabled in the upstream implementation; a `use_pool` toggle is not a demonstrated fix.

A second, quieter matrix used five rounds and the actual PostgreSQL pods with the same client TLS verification. Median time in ms for eight serial reads:

| Web node → DB node | 0 (replica) | 1 (replica) | 5 (primary) |
|---|---:|---:|---:|
| 0 | 3 | 30 | 105 |
| 1 | 48 | 1 | 161 |
| 5 | 93 | 149 | 3 |

This predicts better read locality for two of three web nodes with a primary on 0, not guaranteed login or commit latency after promotion. Times vary materially between windows. Do not route authentication reads to asynchronous replicas or all web traffic to one node.

## Proposed change and acceptance (not executed)

1. Collect a comparable peak-hour baseline: per-node verified-TLS SQL round trips and public anonymous login-flow latency/status. Record blackbox success, Ready endpoint count, primary identity, replication lag and commit latency. Monitor actual IdP-issued test sessions separately if a dedicated nonprivileged test account exists.
2. Verify recent recoverable backup, WAL archival, replay and synchronous quorum; establish a maintenance window and rollback owner. Use the supported CNPG planned switchover to `pg-critical-3` on `socrat-0`, not manual promotion. Keep the RW Service, certificate verification, `synchronous_commit`, quorum and three web failure domains unchanged. Expect a brief reconnect. Do not do this during an active node/etcd incident.
3. Repeat the same tests through the RW Service, including anonymous flow, read/write commit timing and receiver-side status from each location. Proposed initial gate: no 5xx or timeouts in a 30 min observation, login-flow p95 <3 s from each source, all replicas Ready, quorum and archival healthy. Confirm at comparable peak for 24 h. If latency worsens or replication degrades, stop and use controlled switchback only once the previous primary is healthy and caught up.
4. If node 5 remains the outlier, improve the physical path or add a separate low-latency failure domain near the primary. A connection pool can reduce handshakes but not sequential query RTTs. Investigate the 09:36 etcd/API lease failure separately: correlate voter RTT, WAL fsync, API deadlines and host pressure. Do not declare HA based on successful steady-state probes alone.
