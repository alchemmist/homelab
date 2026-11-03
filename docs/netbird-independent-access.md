# Current NetBird administrative access: four routing peers, two relays

Live continuation: 2026-11-03. Supersedes the historical
[single-gateway deployment](netbird-single-gateway.md).
**Data-plane redundancy is deployed; full WireGuard-replacement/HA acceptance is not complete.**

## Actual topology

- Five approved connected peers: one existing owner Mac and four persistent
  `machine-socrat-{0,1,2,3}` agents on the existing nodes. No VM purchases.
- One Network, `wireguard-internal`, four exact host resources:
  `socrat-0=10.250.0.1/32`, `socrat-1=.3/32`, `socrat-2=.2/32`, `socrat-3=.5/32`.
- One native **group-based** router: API destination group `netbird-node-agents`
  contains exactly the four node agents; `peer_groups` references that group,
  masquerade enabled, equal metric 80. This is native route selection, not two
  duplicate resource IDs or manual crossed-gateway tricks.
- Existing inter-node `wg-socrat`, server keys and AllowedIPs were not changed.
  NetBird is human ingress, not a replacement for the server transport.
- Own-node traffic uses native peer **INPUT**, remote addresses use resource
  **FORWARD/SNAT**. Both are required on every possible routing peer.
- Seven enabled policies: four admin resources, one admin INPUT for exact node
  agents, one pilot routed SSH resource, one pilot own-node INPUT TCP 2222.
  Admin source remains genuine JWT `netbird-internal-admins`, owner only.
  The pilot INPUT destination group contains only socrat-2. No All-device grants,
  fake JWT groups, broad prefixes, reverse admin policy or Tim admin membership.
- Each machine enrolled with a one-use short-lived key, then restarted from its
  persistent identity with setup-key environment removed. Enrollment keys were
  revoked and their temporary Kubernetes Secrets deleted.
- socrat-3 was independently offline at initial staging. It received no key while
  offline, then was enrolled only after it returned Ready and host checks passed.

## Independent transport processes

Pinned official standalone relay 0.82.0 runs on:

| Placement | Advertised URI | Trusted TLS |
| --- | --- | --- |
| socrat-2 | `rels://netbird-relay-vps.socrat.alchemmist.xyz:443` | Dedicated existing issuer/certificate; public DNS is VPS-only |
| socrat-0 | `rels://netbird.socrat.alchemmist.xyz:443` | Existing exact-host certificate; dedicated exact `/relay` ingress |

Each relay is nonroot, read-only, capability-free, without host network, service
account token, TURN or STUN, with a 64Mi limit; observed VPS memory usage was about 9Mi.
Only its dedicated transport HMAC secret is copied from the server runtime;
management/PAT/IdP/client credentials are not copied. Existing STUN stays on socrat-2.
Both relay processes exchanged authenticated bidirectional random payloads;
the home relay was verified through both public TLS entrances. This verifies
transport, not a complete physical-site outage or unlimited cached credentials.

**Native 0.82 configuration trap:** setting `server.relays.addresses` disables
combined local relay defaults. `CombinedConfig.Relay` has `yaml:"-"`, so adding a
root `relay:` stanza cannot preserve the combined relay. An initial assumption
that it could was rejected by an actual WebSocket test, corrected with the
standalone home relay, and recorded in the private append-only correction journal.
Only `server.relays` is advertised now, with the existing default 12h relay
credential TTL; the ignored stanza was removed. Five-minute application bearer
policy and OIDC/session settings were not inflated.

**Self-readiness trap:** native relay `/health` tests its advertised public TLS
WebSocket path. Traefik 3.7 filters EndpointSlice `Serving`, so
`publishNotReadyAddresses` alone does not bootstrap it. Each dedicated singleton
Service uses native ClusterIP LB plus `publishNotReadyAddresses`. Native `/health`
remains the readiness probe; no TLS verification or health check is bypassed.
Before Ready the endpoint is intentionally routable for its self-check; relay
HMAC remains enforced. The VPS NetworkPolicy uses its actual CNI bridge subnet
`10.42.0.*`, not socrat-0's `10.42.2.*`. The home policy additionally admits only
reviewed ingress node sources and kube-system Traefik pods.

## Mac bootstrap DNS and SSH

Old split DNS for `socrat.alchemmist.xyz` used internal WG resolvers. With NetBird
down this also prevented resolving NetBird itself. After native macOS admin
consent, three **exact** resolver exceptions were installed for management, VPS
relay and Authentik, using public resolvers. Internal application DNS remains
unchanged. Root-only before-state/evidence is under
`/var/root/.local/state/netbird-bootstrap-dns/`.

`scripts/netbird-macos-bootstrap-dns.py` plans by default; `--apply` explicitly
requires macOS root, backs up existing exact files, and refuses blind replay.
No broad resolver, hosts-file, SSH key, known_hosts or application permission edit.
Existing aliases retain strict authenticated host keys and point to WG addresses;
explicit public-IP SSH recovery remains available independently of NetBird.

## Actual failure tests and limits

Every stopped workload was restored and read back Ready. Tests stopped exact
NetBird workloads, **not physical hosts, home power, the WAN or Kubernetes**.

| Test | Actual observation |
| --- | --- |
| socrat-0 NetBird agent plus management/Signal server stopped | Four rounds of new strict SSH sessions to nodes 1/2/3 passed across about 52 seconds; selected routing peer became socrat-3. Existing Mac remained usable; management status was disconnected. |
| Only node2 NetBird agent left; agents0/1/3 and management stopped | Four new SSH sessions to socrat-2 passed over about 43 seconds. Source was the Mac NetBird address; route was `utun100`. VPS relay remained available. This test preceded standalone home-relay deployment. |
| Node2 agent, VPS relay and STUN stopped; Mac down/up | `up` succeeded and the home relay became available without VPS STUN. Initial SSH attempts failed; by the third round all nodes0/1/3 succeeded. Strict immediate-availability assertion **failed**; eventual recovery was observed. Exact convergence timing was not captured, so no numerical RTO or zero-downtime claim. |
| Management/Signal stopped, then Mac down/up | **Cold start failed**: bounded `up` timed out, state `LoginFailed`, new SSH to node2 failed. Restoring management and reconnecting recovered access. This is the outstanding control-plane SPOF, not an accepted outage outcome. |
| Restored normal deployment | Five connected peers; four routing peers; seven policies; both relays Ready. Strict SSH passed to all four nodes via WG addresses and separately their NetBird addresses. Private Grafana trusted-TLS health returned 200; this is connectivity, not new personal app-role acceptance. |

A CLI Signal-connected flag remained true during a confirmed stopped server;
that cached flag is **not evidence** that Signal was available. Actual stopped
pods, new SSH sessions, relay transport checks and restoration readbacks are the
primary evidence.

### Not claimed

- Authentik or community management/Signal active-active HA.
- A cold/restarted client can start without management; the actual negative test
  proves that it currently cannot.
- New OIDC/MFA login, new device approval, JWT membership refresh or prompt
  revocation while management/IdP is unavailable.
- Data-plane survival beyond credential/session limits or after every endpoint
  changes; tests concern an existing authorized device and bounded outages.
- Physical node/site power-loss acceptance, all possible router-loss combinations,
  separate Tim/nonadmin-device acceptance, or full disaster recovery.

**Therefore do not retire the old administrative WireGuard access yet.** True
cold-start resilience needs a separately verified recoverable/failover control
plane and IdP dependency design, or a deliberately retained independent recovery
path. Existing encrypted/decryption-verified backups are not full DR acceptance.

## Exposed legacy client key

The disclosed client private key is compromised and is never repeated or reused.
Its profile address `.7` maps to `tim-phone` in inventory, while the owner Mac is
`.4`; the actual device ownership must be confirmed before a controlled rotation.
No `.7` peer was silently removed or relabeled, no unrelated key was rotated,
and legacy access was not removed based only on successful connectivity tests.

## Durable source and private evidence

- `scripts/netbird-redundant-access.py`: offline four-node opt-in manifests,
  native group-router body and separate admin/pilot INPUT bodies. It does not
  establish real JWT provenance: live activation separately checked genuine
  `issued: jwt`, exact membership and existing approved owner.
- `scripts/netbird-independent-relay.py` (default VPS, `--home` home): offline
  bounded manifests and native advertised relay settings; never creates secrets.
- `scripts/netbird-host-peer.py`: historical two-host default preserved; admitting
  other reviewed existing nodes requires explicit `admin_mesh=True`.
- DNS durable patches were authored as `0eb93c9` and `847518c`; concurrent main
  integrated the relay patch as `f372b0f`. Exact DNS source/test content was checked
  before integration; the original commit hash need not be an ancestor.
- `tests/test_netbird_redundant_access.py`: pinning, scope, default deny, INPUT
  separation, TLS/self-health bootstrap and control-DNS regression coverage.
- Private remote journal `~/.local/state/netbird-internal-stage/journal/` includes
  independent-access stage/final readback, relay-before/correction records and
  each outage before/restore guard. Mac evidence records include the failed
  immediate cold-reconnect assertion and failed management-less cold start.

Historical activation/retirement scripts are one-shot migrations, **not** general
reconciliation or rollback. Do not replay them, scale a group from stale snapshots,
restore a full runtime blindly, or revoke an identity from only its friendly name.
