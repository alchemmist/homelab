# Current access architecture: one NetBird gateway, existing WireGuard mesh

Live migration: 2026-11-03. Supersedes the initial two-gateway admin ingress.
User explicitly requested simplifying the working deployment to one gateway.

```text
Owner/admin device -- NetBird + Authentik/MFA -- socrat-0 -- wg-socrat -- other nodes
                                                   |
                                              own WG address
                                               native INPUT
```

## Current state

- Dashboard: **2 peers** — owner Mac and `machine-socrat-0`.
- **One Network**, `wireguard-internal`, one router (`socrat-0`), four host
  resources: `10.250.0.1/32`, `.2/32`, `.3/32`, `.5/32`. Resource names map to the
  real node names rather than misleading last-octet numbering.
- Inter-node WireGuard remains unchanged. No LAN/Pod/Service/default prefixes.
- Genuine JWT `netbird-internal-admins` remains the full-node source. Tim is not
  added. Four directed resource policies advertise/administer the node addresses.
- Gateway own address is **local INPUT, not FORWARD**. A fifth explicit native
  peer policy grants admin JWT source to dedicated API destination group
  `netbird-internal-gateway` containing only the gateway peer. NetBird's native
  input ACL matches the admitted source; no manual global accept rule or source
  IP hardcoding, and no fake JWT group.
- Remote resources use native routed FORWARD ACL + masquerade, returning through
  the existing `wg-socrat` routes/AllowedIPs. A sixth policy preserves only pilot
  TCP2222 to socrat-2 as a routed resource; no observer full-network/local-input
  privilege. Native SSH keys/users and application auth remain unchanged.
- This is intentionally a **single gateway / single control-plane SPOF**, not HA.

## Guarded migration and cleanup

Fresh Authentik and quiesced NetBird backups encrypted and decryption/hash verified
before mutations (private journals; not complete disaster recovery).

1. Created native gateway-only destination and admin INPUT policy first.
2. Added the own WG /32 resource to the surviving Network and its admin route
   policy. Preserved old gateway as a fallback until actual tests.
3. Reduced surviving router metric. Duplicate prefix from separate resource IDs
   stayed selected on the old gateway despite the lower metric, so disabled only
   the old own-address policy before testing. Do not assume cross-resource metric
   change alone forces a route switch.
4. Actual SSH source on socrat-0 became the Mac NetBird address; remote nodes
   still saw socrat-0's WG address. Only then retired old paths.
5. Removed obsolete direct socrat-2 peer SSH policy, disabled old own-address
   policy, old resource/router/Network, and old destination group. A null optional
   policy destinations list halted the cleanup guard after old Network deletion;
   verified completed journal operations and continued only unfinished cleanup
   with null-safe source/destination handling. No blind DELETE replay.
6. Gracefully stopped the socrat-2 NetBird agent, waited for pod deletion, deleted
   only its Deployment with UID/resourceVersion preconditions, then deleted the
   exact NetBird peer. Enrollment keys were already revoked and Secrets removed.
   No active agent can re-register it. Its detached 64Mi private identity PVC is
   retained, unmounted, with the peer revoked; not automatically erased.
7. Native readback confirms one Network, one router, four resources, six enabled
   policies and two connected peers. Old peer and group absent. On socrat-2,
   `nb-host` is absent and `wg-socrat` remains present.

## Actual acceptance checks

- Mac NetBird status Connected, management/Signal connected, one remote peer.
- All four WG addresses route through **utun100**, with the old user WireGuard
  already personally switched off by the owner before this migration.
- `ssh socrat-0` through `ssh socrat-3` all succeeded using preserved native keys,
  strict host-key verification and direct private aliases. Gateway own INPUT sees
  the real Mac overlay source; remote hosts see masquerade source `10.250.0.1`.
- A controlled **INPUT policy revocation** denied new TCP2222 to `10.250.0.1`
  while routed TCP2222 to `10.250.0.2` still worked. Restoring only that exact policy
  restored gateway access. This proves local vs routed separation rather than
  assuming the resource FORWARD rule secures local traffic.
- Private Grafana through `10.250.0.3:443`, correct Host/SNI via curl `--resolve`,
  trusted CA and hostname verification, returned HTTP200. No claim of DNS rewrite.
- General non-admin/Tim device, upstream Authentik group-removal timing,
  session/device expiry and outage/DR acceptance remain separate pending tests.

Canonical offline scope is now `scripts/netbird-internal-network.py` (one staged
agent only). Own-address resource rendering requires explicit
`local_input_authorized=True`; `gateway_input_policy()` supplies the separate
native INPUT rule. Legacy first-activation scripts are not a replay/reconciliation
command for this already-migrated account. Never replay the older two-agent
renderer or historical whole-runtime snapshots over concurrent changes.
