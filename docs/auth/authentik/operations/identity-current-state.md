# Identity: current status and first login

> **PostgreSQL (2026-11-20):** The working Authentik DB is `pg-critical/authentik`, endpoint `pg-critical-rw`; do not confuse it with the stopped authentik-postgres. [Operations and CA](../../../data/postgresql/postgres-platform.md).

> **Live auth audit15Nov:** [actual browser/API boundaries](../../../records/handoffs/browser-auth-audit.md).
> Current public Kuma Admin/Syncthing/Search routes do not have the previously
> described Authentik MFA gate. Native service login is not Authentik SSO. Native
> OIDC apps may serve public HTML but deny private APIs. No auth changes applied.

**External password:** [password change page](password-self-service.md) —
https://auth.socrat.alchemmist.xyz/change-password; `/if/user/` is closed for External.

> **Current B2C contract:** [separate app groups and native roles](../../applications/application-access.md).
> Eight enabled roles for LiteLLM, Open WebUI, Grafana, Wiki and LMS;
> the remaining reserved groups do not imply access. Internal/External is not
> an app permission. The old owner-only/preparation snapshots below are history;
> browser E2E and instant revocation of all sessions/keys are not claimed.

## Current addition — observer accepted November 8

`homelab-observer` gives a native viewer access to **Rancher, Grafana, Wiki, Argo CD**.
Danila has already been added to this group; `authentik Read-only` was removed,
the agreed `netbird-internal-admins` preserved. Passwords/MFA were not changed,
no login on someone's behalf was performed, personal native users/roles were not
provisioned. The next ordinary connection is an IdP group add and native
SSO/JIT, not a repeat of the one-time cutover script.

Allow/deny, old browser/API/MCP credentials, a new login after group removal
and automatic remove/re-add of the native cache were verified. Previous
owner/editor/direct rights are additive. **Harbor observer is not supported:**
admission and the three Guest grants were closed after a real CLI revocation
failure; separate task #134. Do not open it based on an old bootstrap receipt.
Details: [native observer](../../roles/observer/native-observer.md),
[acceptance](../../../records/handoffs/observer-acceptance-20261108.md), [runbook](../../roles/observer/observer-profile.md).

## Historical snapshot — November 7, removal of shared external auth gates

What follows records that stage's acceptance, not a current promise of
anonymous SPI evidence or a zero count of Proxy Providers. Later RustFS got a
separate private single-domain protection:
[live edge](../../../rustfs/private-single-domain-live.md).
Do not cancel it while working with the observer, for whom RustFS was not granted.

Removed 11 obsolete Authentik Applications (including the old Kuma bookmark
card) and 10 Proxy Providers; outpost assignments cleared. 10 native OIDC
Applications, their UUID/client credentials/callbacks/policy bindings
preserved. n8n, 3x-ui, Kuma and Syncthing use their own login; SearXNG and the
published SPI artifacts are public without Authentik and NetBird. The Reader
admits only GET/HEAD, verifies manifest/hash and serves safe types inline.
[Contract and boundaries](../../applications/native-browser-auth.md).

Repeat acceptance after restoring socrat-2: **82/82** public checks from HOME
and the VPS, routine TLS verification without disabling validation. All 4 nodes
Ready; socrat-2 Ready since 17:55:34UTC November 7. All 8 affected Argo apps
Synced/Healthy. The old xui gateway Application/Deployment/Service/ConfigMap
and Pod are gone; force-delete was not needed. The 10 native OIDC
registrations/providers/bindings and the preserved icon fields are unchanged;
Proxy Providers0. The published artifact was checked via both entries:
anonymous GET/HEAD/206, manifest/SHA-256, inline, PUT/POST/PATCH/DELETE405.
[Acceptance](../../applications/native-browser-auth.md#recovered-vps-final-acceptance).
This is protocol acceptance, not a fresh verification of a login on behalf of
every person.


Updated **November 7, 2026**; sources:
`deploy/identity/{account-mappings.json,lifecycle.json,browser-auth-policy.json}`,
`docs/records/handoffs/user-recreation-20261107.md` and a read-only IdP check.
This is a state description, not an automatic password reconciler or a grant of
new rights.

## Personal identities

| Person | Authentik login | State |
| --- | --- | --- |
| Owner | `alchemmist` | Protected owner, personal MFA, the only human in `homelab-owner` |
| Tim | `antropophag` | Active/internal, nonsuperuser; on the November 7 check no password set and `last_login=null` |
| Danila | Existing immutable subject preserved | Since November 8 an observer in four services; IdP Read-only removed, NetBird preserved; the real first SSO was not impersonated |

Tim's UUID: `6015c85b-82e9-49ce-a4e3-0270c676e26d`. The old identity was removed
routinely after an explicit owner request. Then **only the username** was changed
from `tim` to `antropophag`, without a new UUID, email change, groups or
provider subject. Tim's display name and the Linux account `tim` remain separate
names.

Groups: `homelab-observer`, `netbird-pilot-login`, `netbird-pilot-grafana`,
`netbird-pilot-ssh-socrat-2`; `netbird-internal-admins` was not granted. The
pilot group names are preserved as real protocol/policy identifiers, not a
proposal to rename the current network or widen access.

## Password and MFA: no invented auto-activation

**Native Create user does not mean the person can log in without a password or
will see a password setup prompt on first login.** For `antropophag` the
password is not set yet; MFA by itself is not a way to start a first login.

The standard administrator action: **Directory → Users → antropophag → Set
password**, with a private credential handoff and a separate agreed procedure
for changing it. Do not call an administratively set password “user-installed”
and do not promise a forced password change until the real flow is configured
and verified.

Self-service setup via the standard Authentik invitation/enrollment/recovery
paths requires separate setup of the corresponding flow and delivery.
SMTP/Brand recovery are not configured now; no invitation was sent. The earlier
separate `homelab-existing-human-activation-v1` flow was removed together with
the owned stage/policy, the token revoked, the delivery file removed. Do not
resurrect it or hand out the old link. Do not set a password or MFA on someone's
behalf for the sake of a test.

The active private bootstrap journal is `antropophag-login.json`,
`initialized=true`, without a plaintext password. The historical
`tim-login.json`/backups are not the source of the active credential. Do not
reset the marker and do not run the old initializer/app smoke to “restore” the
password. The real first password/MFA/login still has not been performed by the
person.

## Native app identities and exceptions

- **Grafana:** the native user2/UID and Viewer were preserved, the exact
  `hashed_user_id` subject updated on recreation; a later username rename does
  not change this subject. Do not replace it with a UUID/email or enable email
  merge.
- **WebUI:** the native user and six chats preserved, role user; the OAuth
  subject is the new UUID. An active auth row is needed for OAuth; the old
  local password was replaced with a discarded random credential, the former
  session stamp revoked. This is not protection against all future
  self-service password routes: a reviewed policy is not permanent enforcement.
- **Wiki:** the same native editor and reviewed UUID mapping; local recovery is
  owner-only. On the subject change, two map entries of the existing Secret were
  updated and one scoped wiki rollout performed, without changing PVC/image/
  accounts.
- **Rancher:** the immutable principal was not bypassed. The current native SSO
  user is `u-authentik-tim-v2`; it has exactly the previous reviewed
  user-base/cluster-member grants. The old `u-authentik-tim` and the legacy
  local `u-22wv2` are disabled, history preserved. Override IDs/prefix in the
  account mapping are needed for a safe next reconcile; renaming the IdP login
  does not require renaming these Rancher resources.
- **Umami3.4.1:** native OIDC is absent; this person's access is **suspended**,
  the existing analytics/team/sites preserved. Do not clear `deleted_at` and do
  not call the delete-user API. Working access comes after issue #85, not after
  an MFA gateway + password.
- Other apps: admission and native permissions are independent; a tile
  appearing does not mean admin/project rights were granted or a user was
  created in each service.

SSH keys/Linux sudo, NetBird device policies and WireGuard recovery were not
changed during the browser identity cutover. An IdP reset is not a revocation
of native app sessions/API keys. Owner recovery, robots, machine API keys and
emergency identities must not be replaced.

## Avatars

For the owner and `antropophag` the API returned a Gravatar URL; there is no
own avatar attribute. This is the stock choice of tenant avatar modes: a link
by email hash, not our photo upload and not proof of login via Google. The
same email after recreation explains the same avatar. The browser reaches out
to external Gravatar; local initials are a separate possible setting that
**was not applied** in this task.

Procedures: [operations](identity-operations.md), [integrations](../integrations/identity-integrations.md),
[NetBird](../../../network/netbird/README.md), [SSH](../../host-access/ssh-user.md), [recovery](identity-recovery.md).
