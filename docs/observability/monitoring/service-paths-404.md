# #404: distinguish Service lag, API outages and Telegram egress

Deployment order: merge the scrape-target fix (#445) first. No automatic restart,
netfilter reset, etcd membership change, or change to SPI's direct endpoint.

From the **same running** probes in `automation` compare `socrat_service_path_state`
by `source` every 15s. `service_only_failed` means direct HTTP `/healthz` on all ready
IPv4 backends succeeded, Service HTTP failed, and the EndpointSlice versions did not
change across the pair. Three consecutive such samples warn; no endpoints, DNS,
discovery, changing endpoints and backend failure are distinct, not divergence.
These probes share SPI's DNS and bot egress restrictions, not its identity/credentials.
Control reads from socrat-3 have a separate narrowly scoped identity. Check per-target
`socrat_control_path_state` for `ready` and `read` (`authorization` is not a TCP failure).
Check probe scrape freshness before treating silence as healthy. No secret or Telegram
traffic is needed. Informer delivery is **not** proven by reading the static API canary.

When paths diverge, preserve UTC, source pod UID, current Slice resourceVersion and
ready addresses; correlate kube_node_status_condition (Ready), API .41, the last
successful IPv4 kubeproxy_sync_proxy_rules_last_timestamp_seconds, and both probe
outcomes. Before restarting anything, owner captures only matching ClusterIP/port
and referenced chain counters (`iptables-save -c -t nat`/`filter` filtered locally),
`ip rule`, and route lookups for relay `91.189.82.238` and mesh `10.250.0.2`.
Never dump tokens, endpoint subscriptions, whole rulesets or journals in issues.

## Owner-only historical evidence

Read the system journals once, with host-key verification and normal owner privileges:
`journalctl --utc --since '2026-11-21 12:13 UTC' --until '2026-11-21 12:26 UTC' -u k3s.service`
on 5, 1 and 2; on 1 add NetworkManager and wireguard-tcp-transport units. Summarize
time, source, event and uncertainty. Compare 12:15:22, 12:15:41, 12:23:21, 12:24:28.
If not retained, mark as unavailable. Alertmanager firing is not a receiver delivery receipt.
For bot compare 13:13:34 UTC separately; no historic socket route is known.

## Controlled acceptance, not production fault injection

1. Disposable K3s cluster of the production version: three test voters, separate
   non-voting API, worker with persistent client, Service and backends returning A/B.
   Verify all voters, each API's TLS/readiness, fresh read/watch and response A.
2. In the **test API's private network only**, make one voter connection first
   refuse and then silently time out in separate trials. Restore baseline between
   trials. Switch readiness from A to B; record timestamps for committed value,
   fresh API read, watch, Slice, proxy sync and first B from the same client UID.
   Two healthy voters and B within 60s without restart are required. If healthy
   routes fail, investigate transport; if reachable but API sticks, investigate
   datastore selection; if watch advances but rules lag, inspect active netfilter.
   No production tuning without a failing-before/passing-after case.
3. Validate no-ready-endpoint and endpoint turnover on the test Service. On production
   observe a normal bot rollout with both probes present and inspect Service path
   recovery before changing SPI. Return SPI to DNS in a **separate** release after
   its durable delivery tests pass. If divergence returns, revert SPI only.
4. For non-Kubernetes desktop apps that really need Happ, inventory owner/DNS/launch,
   use an isolated guest without host sockets, credentials, DNS or routing authority.
   Compare host route/rule snapshots before/after three guest VPN cycles, relay TCP
   continuity and guest egress/kill-switch behavior. Disable host autostart only
   after owner acceptance. Rollback stops guest, never reenables whole-host VPN.
   For Kubernetes consumers use `docs/network/vpn-egress/service-vpn-egress.md`, not a desktop VM.

### Scrape activation is not just Argo Sync

The native OTel receiver in the Prometheus pod owns collection; the legacy
Prometheus selectors are deliberately retired. Do not enable them. Reconcile
`otel-cluster-config` with the updated native scrape builder using the existing
owner's private captured bundle and guarded Collector-only reload/restart procedure.
Diff before applying: preserve auth/TLS, all other jobs, pipelines and data.
Only the API keep rule from #445 and one `socrat-service-path` job are expected
for this work. Abort on unrelated changes. Verify fresh `up` for both headless
per-source targets and three API targets, plus six successful ready/read series;
GitOps Healthy alone does not satisfy acceptance.

The disposable harness is `scripts/lab/service-failover-404.py --local-disposable`.
Use a dedicated local Docker VM with cached `rancher/k3s:v1.36.5-k3s1` and
`nginx:1.27-alpine`, registry access for the stock K3s system images and sufficient
RAM for four servers. No host kubeconfig, host ports, host-directory mounts or
external cluster credentials. Its temporary K3s containers need privileged mode
**inside the disposable VM**. Never point this at a shared production daemon.
It checks that traffic actually hit the fault rule, fails closed if it cannot
identify the active peer and cleans up the randomly named containers/network.

For the host witness, run `python3 scripts/lab/happ-host-witness.py 180` **on socrat-1**
while the owner performs three guest-only cycles. It reads both policy/table sets,
checks the selected relay and mesh routes, requires an original established relay
TCP tuple to remain present and connects to the mesh etcd TCP port without sending
data. Failure is a stop condition, not permission to rewrite routes. Also verify
etcd quorum externally and app DNS/egress inside the guest. Sampling cannot prove
there were no sub-second route transitions. If drift is unrelated, inspect locally.
For the November baseline the package `happ-desktop-bin` was installed, the TUN
was absent, only standard IPv4 rules were visible and a relay TCP session existed.
A package is not proof of an app needing guest migration. No change to host startup
until the owner identifies desktop consumers (the named Kubernetes services are NL).

The current single-replica Recreate bot cannot legitimately publish nine ready
backends. `unsupported_cardinality` is an inconclusive measurement, not health;
inspect the selector and endpoints rather than sampling arbitrary addresses. A
conflicting existing native scrape job is also a stop condition: diff it against
the last approved job, then explicitly migrate the known old configuration. Do
not let an older bundle overwrite administrator changes. At deployment verify
both headless DNS entries and the Service ClusterIP used by the narrow pre-DNAT
policy, especially after Service recreation.

### Bot button latency (2026-11-22)

The bot now prefers the `pg-common` writer's node, using normal pod networking.
Only the bot pod maps `api.telegram.org` to `socrat-telegram-relay` (reserved
ClusterIP `10.43.0.213`). The relay on `socrat-2` forwards TCP to the fixed
public Telegram endpoint. TLS terminates at Telegram, not at the relay. The
control pod still measures its original direct path; the bot sidecar measures
its effective path. When checking latency, correlate `received` and
`pressed_edit_accepted` by callback operation; neither is a client-side timer.
For rollback, set `telegramRelay.routeBot: false` in `deploy/socrat-bot/values.yaml`:
this restores the original hostNetwork placement and direct Telegram DNS. Leave
the private relay deployed until the bot rollback is healthy. No DB move needed.
