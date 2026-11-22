# VPS public IPv4 migration — 2026-11-05

Current socrat-2 public address: **109.120.141.97**. Previous address:
`176.98.185.59`. Private address `10.250.0.2`, node identity, VPN credentials,
client identifiers and persistent application data remain unchanged.

## Applied

- Updated Ansible inventory, public DNS renderer/listener, WireGuard node/admin
  endpoints, authenticated TCP transport and its narrow direct-UDP guard.
  Applied host changes on socrat-0/1/2/3 with private preimages; no node reboot,
  k3s restart or wholesale firewall flush.
- Updated public edge chart values, NetBird STUN binding/advertisement and the
  Telegram webhook IP. Retargeted the native Collector's one VPS blackbox job;
  captured bundle generation now resolves this target from owned chart values.
- Updated RustFS auth egress policy source to the new public address.
- Updated only seven `hosts.address` fields in the primary 3x-ui SQLite database
  and seven in the retained legacy database. Both have private fresh preimages.
  In-transaction comparisons proved all other database fields unchanged;
  SQLite quick_check passed. No restore, credential rotation or client recreation.
- Recreated only the 3x-ui pod twice. The first restart did not fix subscription
  addresses: an initial settings/inbounds audit missed the separate hosts table.
  After the exact database address change, the second recreation cleared cached
  subscription data. No image change or database replacement.
- Updated the generated Mac WireGuard profile file without changing keys.
  Updating a file is NOT evidence that the GUI-imported profile was updated.
- REG.RU accepted ns2 glue address replacement with `109.120.141.97`; ns1 and
  both nameserver names stayed unchanged. Parent publication was initially
  pending; final direct checks of x.nic.xyz and y.nic.xyz both returned the NEW
  ns2 glue. Google DoH also returned the new ns2 A record.

## Verification

- Real authenticated Trojan TLS/WebSocket client ran on a HOME node and used
  the literal NEW public IP, not a local VPS hairpin. HTTPS requests to
  example.com, telegram.org and chatgpt.com returned 200.
- All 15 primary plain subscriptions: 79 links, 74 new-IP destinations,
  5 other existing destinations, ZERO old-IP destinations, no parse failures.
  All 15 JSON subscriptions valid, ZERO old-IP occurrences.
- Both authoritative entrances serve both current public A addresses for all
  15 public application names. HTTPS/TLS checks: **30/30 passed**.
  LMS intentionally returns 303 to `/auth/login`; VPN panel intentionally
  returns 302 to its same-host Authentik start path. Checker validates these
  paths/hosts, not an arbitrary successful redirect.
- Telegram getWebhookInfo from the VPS: new IP configured, pending updates 0.
  A historical last_error remained; no new Telegram message delivery is claimed.
- NetBird combined server reloaded only its STUN URI change. External UDP STUN
  transaction passed; unauthenticated TURN allocation not offered.
- Collector activation pinned pod UID, exact container ID/imageRef, projected
  config SHA and full binary SHA. Same pod; Prometheus, sidecar and reloader
  container IDs and restart counts unchanged. collector.yaml bytes unchanged.
  35-second window: 665242 metric points and 2000 logs exported, zero observed
  failed/refused deltas, queue 0 at that sample. Later instantaneous queue
  samples can be nonzero; this is not an unlimited reliability proof.
- New-IP probe_success=1; old VPS availability alert cleared after series aged
  out. Loki self-monitoring still up=1. No alerts silenced or thresholds relaxed.
- Focused initial tests: 53 run, 51 passed; two WireGuard-admin-client assertions
  already fail identically in the original checkout (DNS tag/template drift).
  Final isolated pytest environment: **160 passed, 4 skipped, 128 subtests passed**
  across the focused inventory, DNS, NetBird, native scrape and ingress suites.
  The historical additive-DNS fixture normalizes only the approved VPS address
  (including the static independent relay); all other records remain compared.
  No full-suite claim.

## Remaining acceptance / client actions

1. Parent glue change is verified. Existing recursive caches may still need
   their TTL to expire (parent advertises 3600s).
2. Refresh phone subscriptions and reconnect. Existing imported literal-IP
   profiles cannot be remotely rewritten; manual configurations need the new IP.
3. Verify GUI-imported Mac WireGuard endpoint, not only its generated file.
4. Removed only the STUN Deployment's exported Rancher publicEndpoints annotation
   from desired values: it pinned an obsolete pod name and caused metadata drift.
   Runtime listener uses the new IP; external STUN passed. NetBird is now
   Synced/Healthy. No blanket prune.
5. RustFS remains Healthy/OutOfSync for other resources; only the two relevant
   egress NetworkPolicies were applied. Final live spec audit found ZERO old-IP
   references in NetworkPolicies, Services, Deployments, StatefulSets, DaemonSets
   and Ingresses. Do not blanket sync unrelated foundation changes.
6. Direct SSH to new IP:22 passed with the existing pinned host key. Local
   diagnostic alias updated, old host-key identity retained (no trust bypass).

Completed emergency backups remain under the owner's private Mac Backups
folder. The full rootfs stream was cancelled at operator request; its `.partial`
file is NOT a complete backup. Critical archive, SQLite copies, PostgreSQL dump
and native etcd snapshot had completed independently. Do not delete them as part
of an IP change. Secrets and private preimages must never be committed.
