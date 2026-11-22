# Administrators: Authentik → NetBird → internal network

## In short: what the owner does and what the person does

**Owner:** creates the personal ordinary account in Authentik, gives the person
a safe way to set their password, adds the single group
**`netbird-internal-admins`**. Does not grant `homelab-owner`, Authentik
superuser, NetBird owner/admin, a setup key, their SSH private key or
kubeconfig.

**User:** installs the official NetBird, specifies the self-hosted server
**`https://netbird.socrat.alchemmist.xyz`**, clicks Connect, goes through their
personal Authentik login and MFA setup. After sync they get routes to the nodes.

No WireGuard config, setup key, personal resolver files, static routes, SSH
jump-host, individual NetBird policy or manual Kubernetes editing is needed.
The self-hosted server address is a mandatory choice in the standard client, not
an extra configuration file; by default the app talks to the Cloud. The app
generates its own unique device identity. Do not copy the owner's profile or
another device's identity.

## The real rights boundaries

- Access to the four host resources `10.250.0.1/32`, `.3/32`, `.2/32`, `.5/32`
  is granted by the existing **group** rules; no user/device policy is needed.
- This is a trusted internal network administrator role, not a limited observer
  role. The existing admin policies allow access to the whole selected host, not
  only SSH. Do not add a random user to this group.
- No default route/exit node, LAN `/24`, Pod/Service CIDR or All-to-All policy.
- NetBird uses four routing peers and the existing server-side `wg-socrat`.
  It does not replace the inter-server transport. Do not remove the nodes'
  mesh keys/AllowedIPs.
- NetBird network admission **does not create a Linux user**, does not add SSH
  `authorized_keys`, Kubernetes RBAC or an application role. Ordinary OpenSSH
  keeps its own authorization; NetBird SSH is off. If the person needs an actual
  shell/kubectl, set up a separate personal authorization; do not hand out the
  owner's keys.

## Persistent settings owners

| Setting | Owner |
|---|---|
| Identity, password, MFA, `netbird-internal-admins` group | Authentik |
| OIDC application/provider, group claim | Authentik; `netbird-access.yml` verifies and additively reconciles |
| JWT allow groups, DNS management exclusions | Native NetBird API; the same audit-first playbook |
| Admin JWT group, route/INPUT policies, devices | Native NetBird API, not YAML copies of the identity DB |
| Workloads/volumes/node agents/relays | Root → NetBird Argo CD, `deploy/netbird/values.yaml` |
| New cluster nodes | The separate `netbird-node-onboarding.md` procedure |
| Mac + Tunnelblick | `netbird-tunnelblick-coexistence.md`; do not change Tunnelblick |

Regularly onboarding **a person does not require running node onboarding**,
reissuing enrollment keys, a deploy or a server/router restart.

## Why groups now propagate correctly

For a new admin, **three** conditions must hold simultaneously:

1. The Authentik application admits the `netbird-internal-admins` group.
2. NetBird `jwt_allow_groups` admits it, with the `groups` claim and propagation
   enabled.
3. OIDC actually passes the groups of the very user who logged in.

In the stock embedded IdP 0.82, the actual redirect to Authentik requests
`openid profile email`, **not `groups`**. Therefore attaching the standard
`groups` scope mapping alone does not work. The dedicated mapping
`homelab-netbird-profile-groups`, attached **only to the NetBird provider**, adds
into the mandatory `profile` scope:

```python
return {"groups": [group.name for group in request.user.ak_groups.all()]}
```

The ordinary profile/email mappings are preserved. There are no fixed
username/email, no favorite-device list and no synthetic `issued: api` instead
of the JWT group. Separate per-SSO-user approval is disabled
(`extra.user_approval_required=false`); peer approval stays off. The verified
Authentik groups and MFA are the entry approval gate; groupless public
registration is not allowed.

The subject stays `user_uuid`; the issuer/application slug `netbird-pilot` is
kept as the stable identity identifier. A cosmetic issuer rename breaks login and
is not useful “cleanup”.

In the server-side DNS settings, the built-in **All** group is included in
`disabled_management_groups`: the exclusion also applies to new devices. The
user does not need to pass CLI `--disable-dns` themselves. The verified Mac also
keeps this protection locally. The absence of NetBird DNS does not forbid the
user's system DNS and does not change Tunnelblick.

## Primary infrastructure check/recovery

The mandatory safe entrypoint, audit by default:

```sh
cd ansible
ansible-playbook -i inventory/hosts.yml playbooks/netbird-access.yml \
  -e @/private/path/become.yml
```

It prints only purposes/counts/`plan_sha256`. For an agreed change:

```sh
# The same run with a fresh audit approval:
-e netbird_access_apply=true \
-e netbird_access_approve_plan_hash=<FRESH_64_HEX_HASH>
```

`--check` does not modify the API. The helper uses the controller's existing
private credentials; their values are not copied to a person/Git/argv. On an
uncertain receipt, stop, read the protected before/receipt data, compare actual
state. Do not replay POST/DELETE automatically and do not restore the whole
identity DB over live data.

## Adding a new administrator

1. In Authentik, create a separate **ordinary** user with a unique username and
   a verified address. Do not use a shared team user.
2. Hand over the initial registration/recovery through a protected channel and
   a time-limited link if a recovery flow is configured. Do not promise email
   until SMTP/recovery are verified. An alternative is a safely delivered
   temporary password with a personal change. Do not publish the password, MFA
   seed/QR or recovery URL.
3. Add the `netbird-internal-admins` group. Do not add the user to the old pilot
   groups: they preserve separate, previously granted limited access.
4. For automation, instead of a manual group — private extra-vars:

   ```yaml
   netbird_access_action: grant
   netbird_access_username: <EXACT_USERNAME>
   netbird_access_expected_user_uuid: <REVIEWED_AUTHENTIK_UUID>
   ```

   Run the audit playbook with `-e @/private/path/person.yml`, review the plan,
   then apply with its hash. An **add_user** is performed, not a replacement of
   all memberships. Other groups and applications are not modified. A repeated
   grant is a no-op.
5. The person installs the client, selects the specified self-hosted server and
   personally goes through Authentik/MFA. Updating the group of an existing
   user requires a **fresh personal authorization**, not just reuse of a cached
   token.
6. In NetBird make sure: the ordinary human role `user`, the UUID/connector match
   Authentik; the admin JWT group received the device; there is no owner/admin
   escalation, pending approval, blocked or expired session. Do not substitute a
   JWT API group.
7. Verify on **their** device: the four routes appeared; a fresh TCP/SSH to the
   internal address works (the native SSH credential is separate). For web — the
   correct TLS/SNI and the user's own role, not just the login page.
8. Negative check: a non-admin does not get the admin resources; a pilot role
   does not become an administrator. Adding the next admin changes no router,
   resource or policy IDs and requires no restart of the other clients.

## Revocation and offboarding

Do not promise instant revocation from a single Authentik group removal:
current JWTs and devices may live until refresh/expiry (currently 8 hours).

- `action: revoke` removes **only the admin membership**. This is a role change,
  not an emergency kill of an existing NetBird session.
- For complete immediate offboarding — **`action: offboard`**, the same exact
  username/UUID and an approved hash. The helper ties the UUID to the real Dex
  subject/exact Authentik connector, blocks the ordinary NetBird user, deletes
  **only their** devices and removes the admin membership. It does not change
  service peers, real owner/admin accounts, email-linking or other applications.
- Then disable the identity in Authentik per the general procedure, and
  separately revoke SSH keys, kubeconfig/certificates/RBAC and app sessions if
  they were issued.
- If only lesser network rights are needed, design a separate role instead of a
  full offboarding. A blocked person cannot be automatically unblocked by simply
  re-adding an Authentik group — a separate review is required.
- Verify new connections from their device and the absence of a returning peer.
  Deleting the device without blocking the identity does not prevent a new
  enrollment.

## What is verified and what cannot be claimed yet

Live 2026-11-06: OIDC-only, JWT propagation, genuine admin JWT source, MFA
enrollment `configure`; application and account admission reconciled; server DNS
excludes All. A real public OAuth redirect confirmed the absence of the `groups`
scope, so the dedicated `profile` mapping was created and read back. A repeated
reconcile is a no-op.

A separate temporary ordinary Authentik user without a password: grant,
readback, no-op, revoke, no-op and deletion passed without superuser/app grants,
MFA bypass or changes to real users. This does **not** pretend to be a new
person's personal OIDC/MFA login and full new-device enrollment. The first real
admin must go through steps 5–8; the owner's credentials/session are not such an
acceptance.

Current Mac: real SSH with the standalone WireGuard off passes through NetBird
to all four nodes. The backup WG `.4` was verified separately with NetBird off,
then turned off again and the primary NetBird restored. Tunnelblick stayed on
the same OpenVPN process and internet routes.

## Cleanup and preserved dependencies

- Local SSH: one unambiguous block per node, no ProxyJump/public fallback, the
  existing pinned host keys. The separate explicit `socrat-2-recovery`/`-direct`
  is break-glass, not part of the ordinary route.
- The default Ansible inventory is now internal, port 2222, pinned legacy
  host-key aliases; `direct.yml`/`lan.yml` remain explicit recovery overlays.
- The temporary assistant WG `.6` was removed from the registry and the
  persistent/runtime peers of all four nodes; the owned firewall was reloaded
  without restarting the mesh interfaces.
- The owner's backup is **one** identity/profile `.4` `wg-socrat-admin`,
  disabled. Its key/config is one credential, not several different keys.
- Phone/TV identities were not deemed unnecessary for lack of fresh traffic.
  The historical note about the exposed phone key requires separate owner
  confirmation/rotation; do not present it as done or safely forgotten.
- The old local bootstrap NetBird admin is blocked and demoted to user; the real
  owner and the bound automation service are preserved. The foreign PAT was not
  permitted to read: there was no bypass/deletion of tokens, do not claim
  otherwise.
- The historical activation/owner-transfer scripts and migration evidence are
  not a reconcile API. Do not replay. They are kept for provenance and dependent
  tests; the current procedure uses `netbird-access.yml`.
- Old SSH rollback files and WG config duplicates were moved from working
  folders to the private `~/Backups/homelab-access-cleanup-20261106/`, not
  destroyed. The server's full emergency backups and node/DB identities were not
  touched.
- The old macOS resolver overrides are a separate root-owned item. Do not delete
  them and do not flush DNS during the mandatory Tunnelblick session. A fresh
  client does not need them; their revision/removal on this Mac is a separate
  safe window.

The control-plane/Auth singleton and the failed cold start without management
are described in `netbird-independent-access.md`; new users do not remove these
HA limits.

### Verification record

Focused offline regression run: **179 passed, 4 skipped, 135 subtests passed**;
Ansible syntax check and live `--check` audit passed with **changed=0 / operations=0**.
Checks cover additive admission, real-scope mapping, bound mandatory MFA, rejection
of All-device policies, user/peer approval semantics, exact UUID/connector pinning,
owner/service protection, scoped offboarding and partial-write stop behavior.
This is not a full repository-suite or new-human-MFA acceptance claim.

One inactive `socrat-assistant` service entry can still be visible in the Mac
WireGuard GUI. Automated UI access was unavailable; its `.6` credentials are
revoked on all nodes and cannot be used. Do not delete the tested `.4` recovery
profile to make the list look shorter. Removal of that obsolete GUI entry is a
cosmetic remaining action, not a second working recovery identity.

Infrastructure prerequisite: preserve the installed [Kubernetes overlay mark
guard](../../../platform/kubernetes/k3s-networkpolicy-overlay-marks.md). Its audit is necessary after node,
host NetBird or overlay changes, not a new step for each person's enrollment.
