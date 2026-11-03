# Existing WireGuard + administrative NetBird ingress

2026-11-03. Actual staged deployment, **not yet full administrative VPN acceptance**.
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

## Current deliberate gate

A default GET-only execution of `netbird-internal-activate.py` **correctly refused**
activation because no genuine `netbird-internal-admins` JWT group has arrived yet.
The user was asked to perform `netbird up --force-reauth` and finish personal OIDC.
No fake API source group, impersonation, cached-password login, or automatic
unrelated user/device grant was substituted.

Resources/routers exist, but **no full internal-network admin policy has been
created**. The one pilot directed SSH policy is not full internal access.
Do not tell the user their old VPN can be removed yet.

## Continue after the human step

Installed private remote scripts mirror source `netbird-internal-network.py` and
`netbird-internal-activate.py`. The latter is GET-only by default, validates genuine
JWT source, exact admitted owner-device membership, four resource prefixes, router
identity/masquerade, old policy set and recent native owner identity. Explicit
apply requires the freshly calculated plan hash and an exclusive intent journal;
uncertain writes stop without retry. It creates four directed resource policies,
not All-device/default/subnet-wide grants. All protocols are intentional **only
for the explicitly administered four nodes**, matching the new full-admin scope.

After apply, verify from Mac that all four WG routes actually use NetBird (not the
still-running legacy VPN), then TCP/native SSH and verified-TLS private Grafana
positive tests, correct SNAT return paths, forbidden non-admin access, group and
session/device revocation, restart/outage behavior. Preserve old client VPN until
real acceptance. A missing Tim test client is a real acceptance gap, not a pass.

Source tests: 79 passed, 1 skipped, 97 subtests after this stage. Native private
before/complete journals are recovery evidence, not publishable API snapshots.
