---
name: netbird-administrator-onboarding
description: "Grant or revoke internal network access for human homelab administrators through Authentik and NetBird. Audit groups, OIDC and DNS; remove legacy access while preserving Tunnelblick and one WireGuard recovery path. Use for people and devices, not cluster node enrollment."
---

# Human administrator admission

1. Read `docs/network/netbird/clients/netbird-administrator-onboarding.md` in full. It is the canonical workflow; the old pilot activation scripts are not.
2. Do not change Tunnelblick, the default route, corporate DNS, inter-server WireGuard, Kubernetes RBAC, SSH users or keys, or real identity UUIDs to grant network access.
3. Use `ansible/playbooks/netbird-access.yml`. Audit is the default; `reconcile`, `grant`, `revoke` and `offboard` are distinct operations. Apply only with a fresh, approved plan hash. If a receipt is inconclusive, do not retry the write.
4. Create or verify the person separately in Authentik as an ordinary, non-superuser account. Grant exactly one group, `netbird-internal-admins`, using the exact username and an independently verified UUID. Do not match by email or copy an owner's memberships.
5. The NetBird 0.82 embedded IdP does not request the `groups` scope. Changing only the standard groups mapping will not fix membership. The dedicated profile mapping supplies actual groups in the required `profile` scope for the NetBird provider only.
6. Server-side DNS management is disabled for new devices through the built-in All group. Publish only the designated internal `/32` routes: no exit, default or LAN-wide routes. The client needs the self-hosted URL and personal SSO/MFA, not a setup key, WireGuard profile, resolver file or per-user policy. Keep `user_approval_required=false` with strictly limited JWT and application groups; peer approval is off. Do not substitute public registration for IdP admission.
7. Verify the actual device, route interface, group source, source policies and fresh connections with native authorization. Standalone WireGuard must be off during NetBird acceptance. Testing an existing owner does not prove a new user can enroll. Never bypass MFA to report success.
8. Removing the group alone is not full offboarding: a cached JWT may remain valid. Offboarding blocks the exact ordinary NetBird user, removes their peers and revokes group membership. Owner and service accounts are protected. Revoke SSH, application and Kubernetes access separately.
9. Remove only identities confirmed to be temporary. Keep the verified `.4` WireGuard recovery path. Do not delete node, phone, TV or unidentified keys based on age. Track the known exposed phone key separately. Keep tokens, passwords, recovery links, UUIDs, email addresses, WireGuard private material and raw API bodies in private artifacts only.
10. Report what was applied, what was a no-op, what readback confirmed, and which positive and negative tests passed. State any limits on new-device/MFA acceptance and outstanding recovery dependencies. Do not claim full HA: a cold client start depends on management and the IdP.

## Kubernetes policy prerequisite

Native host NetBird transport marks can be inherited across the VXLAN boundary
and collide with kube-router allow bits. Before claiming Kubernetes isolation,
audit `ansible/playbooks/k3s-overlay-marks.yml` on all nodes and require zero
operations. Follow `docs/platform/k3s-networkpolicy-overlay-marks.md` after host NetBird,
overlay or node changes. A 403 from S3 is not a network-denial test; test fresh
unprivileged cross-node connections to Pod IP and ClusterIP, plus the allowed
reader. This is infrastructure maintenance, not a per-human client configuration.
