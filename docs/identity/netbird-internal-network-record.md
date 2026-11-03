# Existing WireGuard + administrative NetBird ingress

> Historical initial two-gateway rollout. The live architecture is now
> [one NetBird gateway](../netbird-single-gateway.md); that migration removed the
> second agent/peer and consolidated the Network after actual INPUT/FORWARD tests.

2026-11-03. Actual deployment and Mac administrative routing/SSH checks passed.
Personal user acceptance, non-admin client and outage/HA acceptance remain separate.
Supersedes the two-application-only target for the new user-authorized admin scope.

## Intended separation

- Inter-node transport remains `wg-socrat`, with existing IPv4 addresses:
  socrat-0 `10.250.0.1`, socrat-1 `.3`, socrat-2 `.2`, socrat-3 `.5`.
- Humans authenticate with Authentik/MFA; NetBird carries administrative ingress.
- Native SSH keys/users and application authorization remain mandatory.
- Only genuine JWT group `netbird-internal-admins` may authorize full node access.
  Pilot admission/observer groups must never authorize the whole internal network.
- No new machines, LAN/Pod/Service/default routes, WireGuard config/AllowedIPs
  rewrite, or replacement of existing inter-node transport.

## Actual completed work

1. All four existing nodes successfully pinged all four WG addresses (16 positive
   checks). From socrat-1/3 the non-local targets explicitly route through
   `wg-socrat`. The two ingress hosts also reach all nodes. Both ingress hosts
   already had IPv4 forwarding enabled, free UDP51871, no `nb-host`, and TUN.
2. Fresh Authentik pg_dump and quiesced NetBird SQLite/runtime backups encrypted
   and decryption/hash verified in private remote journals. Not full DR.
3. Native owner transfer completed after verified recent personal login, exact
   immutable UUID/connector/email checks and a bounded explicit exception for
   the single approved preexisting owner Mac. Human owner is now owner; technical
   owner is admin. Existing Mac identity preserved. No other human role grant.
4. Authentik created a distinct non-superuser, no-parent/no-role admin network
   group with only the existing owner as member. Tim and provider configuration
   unchanged; only the dedicated profile mapping allowlist was extended. Existing
   pilot groups retain their roles. No password/MFA/provider/client-secret change.
5. Actual pinned 0.82.0 agents on **existing socrat-0 and socrat-2** in
   `netbird-host-peers`, hostNetwork, separate `nb-host`/UDP51871, persistent
   identities in individual local-path PVCs. Only NET_ADMIN/NET_RAW/BPF; no
   privileged, host PID, host rootfs, SSH/WG files or cluster API credentials.
   Native NetBird SSH disabled, DNS/client-route imports disabled, server-route
   processing enabled. Limits 96Mi/500m, actual later memory ~20Mi/~29Mi.
   Observed VPS MemAvailable 426720KiB after deployment, no observed restarts/OOM.
6. Distinct one-use, 600-second setup keys with empty auto-groups. Before enrolling,
   real pilot JWT source and an exact directed TCP2222 policy to an empty dedicated
   API destination were verified/created. No Default/All allow rule retained.
7. Both agents actually restarted **without NB_SETUP_KEY**, reconnecting with the
   same peer IDs/IPs from PVC. Setup keys revoked and enrollment Secrets deleted
   using exact UID/resourceVersion preconditions. One immediate API connected
   read raced management Sync after readiness; guarded readback confirmed success,
   then only unfinished cleanup was continued (no identity re-enrollment/replay).
8. Two native Networks / routers with masquerade and exact resources:

   | Gateway | WireGuard destinations | Why |
   |---|---|---|
   | socrat-0 | `10.250.0.2/32`, `.3/32`, `.5/32` | Real FORWARD to remote WG nodes |
   | socrat-2 | `10.250.0.1/32` | Remote WG path to socrat-0 |

   No gateway routes its own WG address; that would use INPUT rather than the
   intended routed FORWARD ACL. Masquerade provides return paths over existing
   WG AllowedIPs; no host routes or WG peer changes needed. This layout is **not
   route HA**; management on socrat-0 remains a separate singleton SPOF.
9. Pilot SSH destination contains only socrat-2 peer. From the real owner's Mac,
   TCP2222 on its NetBird overlay succeeds; TCP22 on that overlay and TCP2222 on
   socrat-0 overlay time out. Real native SSH over NetBird authenticated as the
   existing `alchemmist` user to socrat-2 with strict preexisting host-key checking.
   This is automated actual-key acceptance, not a personal GUI usability claim.

## Initial deliberate gate (subsequently passed below)

A default GET-only execution of `netbird-internal-activate.py` **correctly refused**
activation because no genuine `netbird-internal-admins` JWT group has arrived yet.
The initially suggested `netbird up --force-reauth` was incorrect: that flag is
not supported by the installed 0.82.0 CLI. Verified replacement:
`netbird login --extend`. Its regular browser SSO forwards a fresh JWT to native
ExtendAuthSession; server validateToken invokes SyncUserJWTGroups. It preserves
the existing tunnel and device identity, unlike logout/re-enrollment.
No fake API source group, impersonation, cached-password login, or automatic
unrelated user/device grant was substituted.

At that staged checkpoint, resources/routers existed but no full internal-network
admin policy had been created. The one pilot directed SSH policy alone was not
full internal access. Activation was deferred until the real owner refresh.

## Guarded activation procedure

Installed private remote scripts mirror source `netbird-internal-network.py` and
`netbird-internal-activate.py`. The latter is GET-only by default, validates genuine
JWT source, exact admitted owner-device membership, four resource prefixes, router
identity/masquerade, old policy set and recent native owner identity. Explicit
apply requires the freshly calculated plan hash and an exclusive intent journal;
uncertain writes stop without retry. It creates four directed resource policies,
not All-device/default/subnet-wide grants. All protocols are intentional **only
for the explicitly administered four nodes**, matching the new full-admin scope.

### Actual activation and Mac checks after personal `login --extend`

The owner reported successful personal renewal. A genuine JWT-issued admin group
appeared with exactly one admitted owner device. GET-only plan produced four
exact /32 destinations; explicit current-hash apply created and read back four
admin-only directed resource policies. The preexisting pilot SSH policy remains
separate. No All-device policy, API substitute source or other human grant.

- Mac `route -n get` selects **utun100** for all four WG node addresses, not the
  legacy VPN interface. Mac daemon, management and Signal are connected; both
  routing peers connected.
- All four addresses answer actual ICMP and native SSH2222 banners.
- Actual native SSH to **every node** succeeded as existing `alchemmist`, with
  existing key and strict preexisting host-key validation. ProxyJump was disabled
  for these checks, so they were direct through the new private routes.
- SSH-reported source verifies the intended SNAT/return paths: socrat-0 sees
  `10.250.0.2`; socrat-1/2/3 see `10.250.0.1`.
- Verified-TLS HTTPS to private Grafana at `10.250.0.3:443`, retaining correct
  Grafana Host/SNI via curl `--resolve`, returned 200. This does not claim client
  DNS was changed or public Grafana was recreated.
- A bounded revocation test disabled **only** socrat-3's exact resource policy,
  under native policy identity/source/destination checks and private before
  journal. Its Mac route withdrew from NetBird to legacy **utun4**. Restoring only
  that policy brought **utun100** back. The old VPN can still provide fallback;
  withdrawal must not be misreported as total denial while it remains running.
- Latest actual router memory ~25Mi/26Mi within96Mi caps; no cap increase.

Core existing-WG/admin-NetBird ingress is now operational. Old user VPN configuration
is retained pending personal switch-off/usability acceptance. A separate genuine
non-admin/Tim client test, Authentik-group/session/device revocation timing and
outage/recovery acceptance remain outstanding; no claim of route/control-plane
HA, immediate upstream-group removal enforcement or complete disaster recovery.

Source tests: 79 passed, 1 skipped, 97 subtests after this stage. Native private
before/complete journals are recovery evidence, not publishable API snapshots.
