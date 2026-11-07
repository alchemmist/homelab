# Identity and access management

Comprehensive Russian operator manual and session consolidation: [llm-wiki identity](../../llm-wiki/identity.md).

Additive granular app IAM, controller ownership and guarded onboarding/offboarding
(implementation prepared, **not deployed**): [русский runbook](application-iam.md).
The 2026-11-02 GET-only audit preserved the reviewed owner/Tim UUIDs and grants;
no new app memberships were assigned.

Live status: **2026-11-01**. Authentik is the identity provider for the core
administrative services. **Not every application has native SSO.** The distinctions
below are security boundaries, not merely UI details. NetBird remains deferred.

## Requested completion boundary

The approved scope is **every deployed service with human authentication**, not
just this portal catalog. This includes **LiteLLM administration**, now connected through native OIDC + PKCE
with a reviewed owner UUID mapping; the owner confirmed successful SSO login. A complete live service/host/auth-path inventory is still required.
Human login must use Authentik; server-enforced legacy fallback is owner-only.
Scoped machine API keys, robots, webhooks and MCP remain separate and must not be
redirected to an interactive login. A tile or an enabled OAuth provider is not proof
that local bypasses or pre-existing human sessions have been closed.

## Service matrix

| Service | Live authorization | Important limits |
|---|---|---|
| Authentik | Personal users, password + mandatory MFA | Single-node on socrat-0; independent node-admin recovery (see admin-automation.md) |
| Grafana | Native OIDC + PKCE; owner → Grafana server admin, other admitted groups → Viewer | Local emergency login and intentionally existing anonymous Viewer preserved |
| Harbor | Native OIDC, owner group → system admin | Local admin retained; project-scoped robots remain independent |
| Rancher | Native Generic OIDC + PKCE, restricted to the reviewed identities | Separate external identities mirror existing Rancher grants; local identities preserved for emergency/transition |
| Open WebUI | Native OIDC; owner → admin, Tim → user | Existing users/chats retained through exact UUID linking; no generic email merging; local login retained |
| n8n | Authentik MFA/group gate in front of browser UI | **Not native account SSO**: Community lacks the appropriate licensed integration; n8n may still ask for its own login |
| Wiki | Native OIDC + PKCE, owner admin / existing Tim editor / other observers reader | Public reading and machine MCP remain separate; legacy passwords and old local sessions are owner-only |
| LiteLLM | Native Generic OIDC + PKCE, owner-only application; reviewed UUID → existing `socrat-admin` | Existing owner database password fallback and machine keys retained; free SSO ≤5 users; owner recovery-password acceptance pending. See [LiteLLM](../litellm.md) |
| Uptime Kuma | Existing native admin authentication + public status pages | **Not migrated to SSO**: installed auth implementation has no native OIDC; public and administrative socket traffic must be separated safely first |

Other app/API credentials (LiteLLM, CI, MCP, Syncthing, VPN and webhooks) are not
silently replaced with browser credentials. The service catalog is
`deploy/identity/services.json`; it currently covers eight foundation-managed portal services; Argo CD is managed separately,
not every endpoint in the cluster. Do not describe a portal tile as proof of SSO.

## Accounts and rights

Reviewed mappings are in `deploy/identity/account-mappings.json`:

- **alchemmist**: personal Authentik owner, only human in `homelab-owner`.
- **tim**: separate personal Authentik user, `homelab-observer`, mandatory MFA.
  His existing Linux SSH keys and existing app permissions are preserved.
- `homelab-platform-operator`, `homelab-project-maintainer`, `homelab-machine-owner`
  exist without speculative human assignments. Approve actual project/node scopes
  before using these labels to grant administration rights.

Owner group is superuser in Authentik and mapped explicitly in each native app.
No other group may inherit Authentik owner privileges through the initializer.
The initializer refuses a username collision without its bootstrap journal, an
unexpected owner member, or missing OAuth credentials for an existing provider.
It never silently resets a human's changed password.

### Personal login

Portal: **https://auth.socrat.alchemmist.xyz/**. Owner already completed initial
login/MFA. All nine current dashboard applications have local SVG icons uploaded to Authentik's persistent media store,
not a third-party tracking CDN. Pinned assets, hashes and upstream attribution are
in `assets/service-icons/`.

On socrat-0, `~/.cache/homelab-authentik/` is 0700; credential files are 0600:

- `owner-login.json`: **initial** personal owner password, potentially stale after change;
- `tim-login.json`: Tim's initial password; deliver through an independent secure channel;
- `credentials.json`: installation/signing/PG material and the legacy API-token alias; after migration this alias belongs to the machine automation account, not akadmin;
- `oidc-clients.json`: confidential OAuth clients;
- private pre-migration rollback snapshots.

Never put these values in chat, Git, shell arguments or logs. For clipboard-only
retrieval of Tim's initial password on Mac:

```sh
set -o pipefail
ssh -o Hostname=109.173.40.247 \
  -o 'HostKeyAlias=[socrat.alchemmist.xyz]:2222' socrat-0 \
  'python3 -c '\''import json; from pathlib import Path; print(json.loads((Path.home()/".cache/homelab-authentik/tim-login.json").read_text())["password"], end="")'\''' \
  | pbcopy
```

Tim logs in as `tim`, enrolls his own TOTP and changes the initial password.
`akadmin` was the initial emergency administrator; after the guarded migration it is retired. Current machine API and independent node-admin recovery: [admin-automation.md](admin-automation.md). Do not rely on the retired password/token. Keep an
independent emergency access path and securely escrow MFA recovery codes.
SMTP invitations/reset mail, independent escrow and finer-grained automation RBAC remain follow-up work; the old bootstrap token is retired.

## Grafana incident and acceptance

The first provider omitted **grant_types**. Authentik 2026.8 rejected the browser's
`authorization_code` request with `invalid_request`, before checking group roles.
The source now explicitly sets `authorization_code` and `refresh_token` for every
native OAuth provider, with regression coverage. TLS verification and MFA were not
disabled to work around the error.

`scripts/identity-grafana-smoke.py` exercises a real browser-equivalent HTTP flow:
password, TOTP setup, consent, PKCE/code exchange and authenticated Grafana API.
It asserts the temporary observer is Viewer, not server admin. Both temporary
Authentik and Grafana profiles are removed. The test passed after the fix.
It never uses the real owner's password, MFA secret or session.

The private Grafana gateway intentionally clears Authorization headers. Browser
session cookies still work. Test cleanup uses the internal Grafana API from the
owner node rather than weakening that gateway setting or enabling insecure TLS.

## Linux and Kubernetes hardening — applied

The original audit found socrat-0's `/etc/rancher/k3s/k3s.yaml` world-readable (0644).
**Fixed live** to `0640 root:alchemmist`, with persisted K3s mode/group and updates to
initial-install and HA templates. The owner-only group is checked before applying.
Owner kubectl still works; Tim cannot read the credential.

`ansible/roles/users/` is applied on all four nodes:

- validated names/keys and explicit managed account boundary;
- exact authorized_keys replacement (removed keys really disappear);
- per-host assignment and explicit `disabled` state without deleting files;
- no implicit sudo/docker/root-equivalent groups;
- no management of owner/root/CI through the restricted-user path.

Privileged verification confirmed on all four nodes: Tim has two intended keys,
public-key authentication and PAM enabled, no effective sudo grant and no readable
admin kubeconfig. This is not a network login using Tim's private key (we do not
possess or request it). Owner SSH/automation continues to work.

`sudo -l -U` can return exit 0 while saying the target is not allowed. The verifier
checks the actual C-locale policy result, not merely that exit code.

Closing permissions **does not revoke a previously copied admin certificate**.
Assess historic exposure separately and plan any supported credential/CA rotation;
no CA rotation or node restart was performed. Do not claim no compromise just
because no evidence was collected.

The observer ClusterRole exists but has **no human bindings**. IdP group strings
are not automatically kube-apiserver/Rancher principal IDs. No cluster-admin kubeconfig
is issued to new users. Namespace scopes still require explicit review.

### Apply

From `ansible/`, use appropriate inventory and verified per-node SSH overrides:

```sh
ansible-playbook -i inventory/hosts.yml \
  playbooks/identity-hosts.yml --ask-become-pass
```

All four nodes accepted sudo during this rollout. The socrat-3 inventory now
uses the verified sudo method too.
Do not put become passwords in inventory. Temporary helpers used for this rollout
contained no password, and their environment/inventory files were removed afterward.
The dual-address public hostname can land on the wrong ingress: select verified
home endpoints and matching existing HostKeyAlias, never disable host-key checks.

Removing an account from inventory or changing its hosts list is not revocation.
Disable it explicitly on old hosts first. Removing SSH keys does not terminate
existing sessions/port forwards; IdP disablement does not itself revoke SSH keys,
app API keys or all already-issued sessions. Full offboarding remains a coordinated
runbook/automation task, not a completed guarantee.

## Native service migration details

### Harbor

The saved initial admin password had become stale (401). It was **not reset**.
Instead the supported `CONFIG_OVERWRITE_JSON` activates OIDC through a Kubernetes
Secret; confidential client settings are not embedded in Helm values. Before
cutover a complete encrypted snapshot of its DB, registry blobs and bootstrap
credentials was copied off-node and subsequently restore-checked.

Only the original active admin existed before migration. The deleted anonymous
placeholder is not treated as a human to migrate. Local non-admin identities cause
the migration controller to stop for review. Local admin remains an emergency path.

Public systeminfo confirms `oidc_auth`. A pull-only robot successfully retrieved
the existing private BusyBox manifest after the change. Project visibility and
scoped robot credentials were preserved. Browser owner login remains an explicit
human acceptance step. Do not rerun the initial robot/project initializer with an
obsolete initial password after OIDC activation; the role now guards that path.

### Rancher

Rancher correctly rejects changes to an existing User's immutable principalIds.
The migration does **not** bypass or disable that webhook. Separate external users
`u-authentik-alchemmist` and `u-authentik-tim-v2` bind to exact Authentik UUID subjects.
Their GlobalRoleBindings/ClusterRoleTemplateBindings/ProjectRoleTemplateBindings
mirror only the reviewed original identities. Native Rancher controllers generate
Kubernetes bindings; no hand-written broad cluster-admin binding was added for Tim.
Managed stale mirror bindings are removed on reconciliation. Local users and their
original grants remain for transition/emergency access.

Generic OIDC uses TLS verification, PKCE, a Secret reference in cattle-global-data,
and an explicit allowed-principal list for these two users. The public provider
endpoint exposes both Generic OIDC and local login. End-to-end Rancher browser
acceptance by the owner/Tim remains necessary; a visible provider is not that test.

### Open WebUI

A consistent SQLite snapshot and auth Secrets were encrypted off-node first.
The application model method links **exact existing user IDs** to Authentik UUID
subjects under provider `oidc`. Generic email-based merging is disabled; the
reviewed emails are checked before linking. Original admin/user roles, user IDs
and chats are not recreated. Role mapping follows homelab-owner vs observer.
The UI advertises Authentik; both original identities remain linked. Canonical and
known private callback URLs are strict allowlisted, not wildcarded.

### Reconciliation

- `authentik.yml`: pinned foundation, groups/users/providers/icons and n8n gate;
- `identity-integrations.yml`: explicit service list, empty by default;
- Grafana and Harbor Helm roles load separate identity overlays only when their
  activation Secret exists;
- WebUI deployment/HTTPS/upgrade/tool-guard playbooks import a conditional identity
  reconciliation step after their normal work, preserving unrelated OTel state.

Do not launch a full monitoring upgrade merely to change OAuth variables.
Existing concurrent OTel edits were preserved, not replaced wholesale.

## n8n gate and machine endpoints

The embedded Authentik proxy protects the UI and `/rest` routes, owner group only.
There is no paid-feature bypass: **n8n still owns its application accounts** and may
ask for its own password after Authentik. Native SSO requires an appropriate license.

A higher-priority direct ingress preserves `/webhook`, `/webhook-waiting`, `/form`,
`/form-waiting`, `/healthz`, `/api/v1` and native credential OAuth callbacks. Thus
machine traffic does not depend on Authentik being up. Existing webhook/API
credentials remain enforced by n8n. No real production webhook was invoked to test.

Through both public IPs: UI and `/rest/settings` return an Authentik redirect,
healthz 200, missing API key 401 and a nonexistent webhook 404 (not a login page).
The original ingress and certificate stay intact for renewal and rollback. They were created while Fleet owned the route; that GitRepo is retired and must not be recreated to preserve them.
Deleting the two identity-managed gateway ingresses restores the prior routing;
do not delete the native app, database, ingress, or certificate.

## WireGuard and trust

No WG keys, routes or firewall rules were changed. The current Mac profile uses
three direct peers with separate /32 ownership. Assigning the same subnet to all
peers is not a correct routing solution. Stable routing requires an explicit gateway,
per-client ACL and failover design; NetBird remains out of scope for this rollout.

Root on someone else's node implies trust for workloads/secrets on that machine.
SSO, labels, taints and NetworkPolicy do not remove that boundary.

## Backup, restore and availability

Authentik 2026.8.5, PostgreSQL 17.11, server and worker run on socrat-0 with explicit
budgets, retained local PVCs and no mounted runtime Kubernetes API token.
**Single-node, not HA.** Local emergency service logins must remain available.

`scripts/identity-backup.py --service authentik|harbor|open-webui` streams snapshots
into AES-256-GCM encryption on the owner Mac. Archives/key are outside Git:
`~/.config/homelab/`, key `identity-backup.key` (0600), never sent to the cluster.

`scripts/identity-restore-check.py` proved:

- Authentik dump imported into isolated disposable PostgreSQL;
- Harbor PG18 dump imported into isolated PG18, original admin present, all three
  saved registry blobs verified by SHA-256;
- WebUI snapshot passes SQLite integrity checking and contains the two exact
  reviewed original user IDs.

No plaintext archive is kept on Mac. WebUI restore verification uses a private
0600 temporary SQLite file (to handle WAL-mode headers) and removes it afterward.
These are state-restore checks, **not full application/site disaster recovery**.
Scheduled off-node backups, independent key escrow, retention/restore drills and
bootstrap API-token retirement still need implementation. Losing both Mac and key
loses access to these encrypted snapshots.

Rollback is per service and coordinated with writes. Do not blindly apply a whole
old Grafana deployment snapshot over new OTel work or treat Helm rollback as data
rollback. Restoring old identity state can resurrect revoked users/credentials.
Keep original PVCs, app signing/encryption keys and independent local access.

## Remaining acceptance and explicit exceptions

- [ ] Owner verifies Grafana server-admin, Harbor, Rancher and WebUI in his browser;
      Tim completes personal MFA and verifies his restricted roles.
- [ ] Retire normal legacy local logins only after verified native SSO and a tested
      independent break-glass path; don't confuse retained emergency login with exclusive SSO.
- [ ] Decide native n8n SSO licensing vs retaining its MFA gate plus local login.
- [ ] Design Kuma admin/status/socket separation. Wiki native OIDC is now migrated;
      public pages and machine MCP remain available. Fix the pre-existing missing WG virtual hosts/TLS separately.
- [ ] Complete onboarding/offboarding/session/API-key/VPN coordination and role scopes.
- [ ] Schedule protected backups, escrow keys, retire bootstrap token and run full DR.
- [ ] Review historical admin kubeconfig exposure and credential rotation separately.

Source checks and live health evidence are in `deploy/identity/migration-evidence/`.
Do not report every service migrated, every session revocable, or the IdP highly
available until those properties are actually implemented and tested.

## Wiki cutover, 2026-11-01

Native OIDC is live, not a portal shortcut or just a proxy gate. Use
https://wiki.socrat.alchemmist.xyz/login; owner fallback is `/login?local=1`,
username `admin`, unchanged CURRENT password. The stored initial password was stale;
it was not reset. Ordinary users cannot use local passwords, including through direct
API calls, and their pre-migration local sessions are rejected. Reviewed existing IDs
and permissions are preserved (Tim editor, not speculative observer-wide write access).
Real observer MFA/OIDC and read-only enforcement passed; MCP read still works.
See `deploy/wiki-runtime/oidc/README.md` for provenance, backup, GitOps and private TLS gaps.
This does NOT mean all other services have already enforced owner-only legacy fallback.
