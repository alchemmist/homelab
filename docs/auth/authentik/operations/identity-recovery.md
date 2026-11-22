# Authorization: backup, recovery, diagnostics and evidence

> Current November 7 snapshot: [logins, first login and native roles](identity-current-state.md),
> [NetBird/network](../../../network/README.md), [monitoring owners](../../../observability/monitoring/observability-current.md).
> The dated rollout/smoke sections below are history of their stage, not general readiness.

Start: [identity.md](../../architecture/identity.md). Any recovery changes a trusted
system: verify the operator's identity/authority, the pre-change snapshot and the
impact on consumers. Do not run a production restore from this document without a
separate incident plan.

## 1. Where the sensitive state lives

| Location | What is there / boundary |
|---|---|
| `socrat-0:~/.cache/homelab-authentik/` | Private runtime deployment root, directory 0700/files 0600 |
| `credentials.json` in this root | DB/installation secret material and the new machine admin's legacy API-key alias; broad privilege |
| `automation-api.json`, `credentials-before-automation-*.json` | Secret-bearing exact-identity migration journal and pre-change rollback; do not publish |
| `owner-login.json`, `antropophag-login.json` | Private bootstrap markers; antropophag has initialized=true without a password; the historical tim-login is not an active credential |
| `oidc-clients.json` | Stable confidential OAuth clients; do not recreate them if the file is lost |
| private integration journals/snapshots | Old config, exact identity bindings, potential secrets |
| `theme-backups/`, brand journal, original flow-title file | Presentation rollback, not a full DB backup |
| Kubernetes runtime Secrets | Authentik/app client credentials/signing keys; refs are public, bodies are not |
| `~/.config/homelab/` on the owner's Mac | Off-node encrypted backups and a separate encryption key |

Do not print credential files, Secret JSON/YAML, pod env, shell history with
tokens, callback URLs, MFA QR/seed, browser storage/cookies. Do not save
Playwright trace/HAR/video by default: they can contain all of the above.

The encryption key defaults to `~/.config/homelab/identity-backup.key`, 0600,
**never sent into the cluster**. Losing the key makes the AES-GCM backup
unusable. Independent escrow/recovery access to it still has to be arranged
separately. File names and digests may be documented; the contents of
keys/archives may not.

## 2. What the existing backup tools can do

`scripts/identity-backup.py`: `--service authentik|harbor|open-webui|litellm`.
Over SSH it runs the reviewed read-only collector, brings the snapshot into the
owner Mac's memory, encrypts it with AES-256-GCM using a random nonce and an
authenticated header, and writes a new 0600 file with an SHA-256 sidecar. It
does not overwrite existing output. The remote collectors' stdout **contains
secrets/plaintext archive**: run it through the encrypting wrapper, not by hand
in a terminal/CI log.

```sh
# From the repo root, in a Python environment with cryptography. The directory must already be private.
python3 scripts/identity-backup.py --service authentik \
  --output "$HOME/.config/homelab/authentik-YYYYMMDDTHHMMSS.aesgcm"
python3 scripts/identity-backup.py --service litellm \
  --output "$HOME/.config/homelab/litellm-YYYYMMDDTHHMMSS.aesgcm"
```

Replace the timestamps in the examples with real ones; do not rely on a
predictable overwrite. The SHA sidecar confirms transport/storage integrity,
while AES-GCM confirms authenticity with the given key. Neither verifies the
logical usability of a full recovery.

- **Authentik:** PostgreSQL dump, protected config/credentials and a `/data`
  snapshot; see the exact file set in `ansible/roles/authentik/files/backup.py`.
- **Harbor:** DB + registry data/config/Secret snapshot; blob hashes are checked
  separately. The snapshot does not by itself make distributed storage
  consistent.
- **WebUI:** a consistent SQLite backup via the stock SQLite mechanism,
  config/Secrets.
- **LiteLLM:** a custom PG dump, Deployment/ConfigMap, original env/DB Secrets,
  an optional dedicated OIDC Secret. The dump contains sensitive account/key
  data.
- **Wiki:** a separate encrypted frozen-volume pre-migration snapshot was created
  and verified. The generic wrapper does **not support `--service wiki`** yet;
  do not invent such a CLI. SQLite/WAL and volumes need a reviewed
  quiesce/snapshot procedure.

A backup without a schedule, off-site copies, retention alerts and escrow is a
manual capability, not a finished DR system. A copy on the same physical node is
not an independent backup.

## 3. The restore check: what was really tested

```sh
python3 scripts/identity-restore-check.py --service authentik \
  --backup "$HOME/.config/homelab/REVIEWED_AUTHENTIK_BACKUP.aesgcm"
python3 scripts/identity-restore-check.py --service harbor \
  --backup "$HOME/.config/homelab/REVIEWED_HARBOR_BACKUP.aesgcm"
python3 scripts/identity-restore-check.py --service open-webui \
  --backup "$HOME/.config/homelab/REVIEWED_WEBUI_BACKUP.aesgcm"
```

These are real operations creating disposable restore resources in the cluster
for PG, not a read-only lint. PG runs socket-only without a Service, with a
temporary `emptyDir`, without a runtime SA token; data is not written into the
production DB. Cleanup in `finally`. Run only with sufficient resource headroom
and permission for such a test.

Verified: isolated Authentik PG/role groups, Harbor PG/admin/blob hashes and
WebUI SQLite integrity/preservation of original user IDs. This is **not a full
application recovery**: all users/MFA/devices, network endpoints, DNS,
signing/token continuity, node recovery, consumers and real owner recovery
logins were not checked.

The LiteLLM pre-change archive `litellm-before-oidc-20261101.aesgcm`:
authenticated decryption and `pg_restore --list` passed, but a full restore
drill was **not performed**. `identity-restore-check.py` does **not accept
`--service litellm`** yet. PG16's `pg_restore` rejected archive format 1.16;
the more suitable installed PG17 could read the TOC. For a real recovery choose
a compatible major/tool; a successful listing is not proof of a full PG18
database restore.

The registry of sanitized evidence is `deploy/identity/migration-evidence/`.
Hashes of specific snapshots may live in evidence/old notes; do not keep the
decrypted dump, recovery codes or the key next to them in Git.

## 4. Recovery when Authentik is unavailable

1. Distinguish a TLS/DNS/edge failure from a server/worker/DB/PVC failure. Check
   readiness, certificate state, endpoints, volume attachments and resources
   without dumping env/Secrets.
2. Check both trusted public edges with the correct Host/SNI. Do not disable TLS
   or change WG routing just because a private gateway serves the wrong
   certificate.
3. Do not delete PVC/PG, uninstall the release or generate a new secret key.
4. Use the pre-reviewed local owner recovery of the specific application if it
   is available. It may depend on the private network and the real owner
   password.
5. If IdP restoration is required: first an isolated restore, then a separate
   approved production cutover plan. The DB, installation/signing keys, `/data`,
   client secrets, protected identity journals, TLS/DNS and the correct version
   are all needed.
6. After restoration verify immutable user UUIDs and application subjects. A new
   empty IdP installation with the same usernames is **not the same identities**.
7. Check all consumers, clock, token validation, positive/negative admission,
   the owner's personal MFA, machine keys; reasonably revoke potentially
   compromised sessions/tokens. Having a backup does not undo the consequences
   of a compromise.

The old bootstrap API token was retired together with akadmin after moving the
consumers to a separate machine admin. The new token is still broad as well:
scoped RBAC and rotation remain a debt, not a hidden guarantee of least
privilege. The legacy credential-key name does not mean the old bootstrap token
is still in use.

## 5. Rolling back an integration without destroying data

Private snapshots are meant for point recovery of config, not a blind
`kubectl replace` of the whole Deployment. Otherwise you could erase parallel
env/OTel, placement, resource budgets or an updated image. First compare current
vs snapshot.

For LiteLLM, disable only the dedicated SSO env/Secret wiring from the reviewed
snapshot; keep DB/master/salt/passwords/API keys. Do not reset the owner's
`/fallback/login`. Disable a provider/app after deciding which entrypoint should
remain. A user-count license failure must not be “fixed” by bypassing the
premium check.

For the wiki, keep the original accounts SQLite and the signing key; a wrong key
can invalidate cookies but is no reason to grant the fallback to everyone.
Choose the immutable runtime image and chart explicitly, without deleting the
PVC. Do not revive old non-owner password sessions.

Theme rollback is separate, see [identity-frontend.md](../custom-ui/README.md):
Brand UUID and flow identity guards, the original baseline, retained static
assets. It is not a rollback of the whole identity DB or auth migrations. A live
rollback/reapply for the sake of testing was not done, to avoid interrupting
real logins.

## 6. Diagnostics table

| Symptom | Check before changing policy |
|---|---|
| The tile is missing | The app's real existence, active user, admission bindings; not the icon alone |
| `invalid_request` / provider denied | Client ID, exact callback, grant_types, issuer; the Grafana incident was about grants |
| A new empty profile | Subject mode, exact existing ID links, whether an email merge/new-user creation happened |
| Login works, role is wrong | Signed group claim + app role mapping + the app's own grants |
| MFA is skipped for a new person | `not_configured_action`, native flow binding; not a fixture-only success |
| A previously issued password does not work | The initial journal may be stale; do not reset a real password without the owner |
| Wiki Tim cannot log in locally | That is the intended owner-only fallback; use OIDC |
| WebUI OAuth disappeared after disabling user auth | `Auth.active=False` also turns off get_auth for OAuth |
| LiteLLM callback 500 | Runtime validators, custom scope claim names, account limits and state/PKCE; do not print code/token |
| The API suddenly serves login HTML | A browser proxy captured the machine path; check the route boundary, do not disable API auth |
| Follow redirect instead of auto-transition | The native inspector is open: an intentional debug pause |
| `%(app)s` in the heading | A raw flow title template; the managed authorization titles are already `Redirecting` |
| Inspector history repeats | Native session snapshots of the shared flow, not unique checks of one app |
| The magnifier is unavailable to an observer | Normal: the debug API requires a separate inspect permission |
| Theme assets stopped loading | A persistent signed media JWT URL is not allowed; check the immutable static endpoint/digest |
| CSS does not change the drawer | A LitElement root does not get the AKElement Brand injection; use exported parts |
| The UI is in Russian after the en default | `?locale=`/sessionStorage take precedence over defaults; a hidden picker is not a forced locale |
| kubectl apply's annotation is too big | Server-side apply of an immutable asset CM, not client-side last-applied |
| OpenAPI List validation 503 | Separate documents/strict v3, not `--validate=false` |
| A WG URL serves a foreign certificate | A separate private VH/TLS defect; do not weaken certificate verification |

## 7. The check set and the live-test boundaries

Offline (without credentials/cluster mutations):

```sh
python3 -m unittest discover -s tests -p test_identity.py -v
python3 -m unittest discover -s tests -p test_litellm_identity.py -v
python3 -m unittest discover -s tests -p test_authentik_branding.py -v
python3 -m unittest discover -s tests -p test_authentik_flow_titles.py -v
cd ansible
ansible-playbook playbooks/authentik-branding.yml --syntax-check
ansible-playbook playbooks/identity-integrations.yml --syntax-check
ansible-playbook playbooks/identity-litellm-reconcile.yml --syntax-check
```

Read-only live controls check: `identity-branding-controls-check.py --run`,
including the second edge. This is a local-only browser layout challenge with a
denied inspector API, not a real owner login and not a change to server auth
data.

Actual temporary-identity tests: `identity-branding-smoke.py --run`,
`identity-litellm-smoke.py --run`; they create identities, real temporary TOTP,
app sessions/keys, and LiteLLM additionally a scoped temporary admission
binding. **These are writes**, not a read-only healthcheck. Do not run them
en masse/in parallel with a user migration. The fixture is not the owner; the
existing human factor is not read/reset. Verify cleanup, including temporary
bindings/DB users/keys, even on a callback exception.

The old `identity-grafana-smoke.py`, `identity-webui-smoke.py`,
`identity-wiki-smoke.py` also perform live mutations and need not have a
`--run` guard; before running, read the current version specifically. The
cleanup helper `identity-litellm-cleanup.py` is not a mass user-deletion
command: apply it only to the exact test identity.

The owner personally confirmed LiteLLM SSO; this is not confirmation of all app
roles/recovery passwords, Tim's personal MFA or full offboarding readiness. The
owner inspector was studied from his saved HTML and UI/CSS checks, without
capturing his browser session.

## 8. How to arrange a safe publication

1. Fetch origin and check for a dirty tree/outgoing commits. Do not roll back
   parallel work, do not staging `.` and do not force-push. The changes may have
   already reached main via another operator — review the log/diff first, do not
   copy history blindly.
2. Stage only the reviewed auth paths and guides. Exclude raw private Downloads
   HTML, backup archives, credentials, browser profiles, `/tmp`
   dumps/screenshots.
3. Review the staged diff: no tokens/passwords/seeds/callback queries; do not
   confuse public digests/UUIDs with credentials, but do not allowlist a real
   leak.
4. Run focused unit/syntax/link checks and a secret scan. Do not claim the whole
   repository suite passed if only profiled tests were run.
5. Commit/push to the agreed branch without rewriting origin. Check the remote
   commit, the working tree and the actually configured CI checks; the absence
   of a workflow is not a green pipeline.
6. A push is not a deployment: branding/app controllers apply separately; running
   images and Argo CD Application readiness are checked after the respective rollout. A Fleet GitRepo is no longer a deployment check.

## 9. Remaining backlog

Cluster-wide human-auth inventory; exhaustive Kuma native-account/owner recovery
acceptance (the public/admin boundary is already closed); n8n license/native SSO;
Tim's personal delivery/TOTP/private-key acceptance; owner recovery for every
app; a legacy local sessions/old-password bypass audit beyond the already
verified wiki; strict English enforcement for old overrides; native inspector
JSON highlight/Copy, grouped/filtered history; the owner photo collection; an
independent backup schedule/escrow/full DR; a scoped machine admin
API/rotation; the historic kubeconfig exposure/credential rotation; distributed
Authentik/Harbor HA. Do not close these items merely because of a pretty login
page or the existence of an encrypted archive.


## 10. The default Admin replaced by machine automation

`akadmin` and its bootstrap token were removed after guarded checks; the daily
human users are `alchemmist` and `antropophag` (the former IdP login `tim` was
renamed November 7). The outpost account was kept. The new
`homelab-identity-automation` has a service_account type, a password unusable
for login and **broad** admin API rights of a separate group — do not present
this as completed least-privilege RBAC. The historical AUTHENTIK_BOOTSTRAP_TOKEN
key in the private credentials is now an alias of this token. It does not enter
runtime Secret/pods via bootstrap.py.

Independent node-admin recovery was verified with the official recovery link on
a temporary admin, not on the owner; exact fixture cleanup is complete. The
owner's personal recovery and full DR remain a separate acceptance. The old
backup credentials after retirement will not restore API access to the current
DB; check journal/backup consistency first. The procedure, guards and proven
limits: [admin-automation.md](admin-automation.md).

## Network closeout and new private receipts

See [network-access.md](../../../network/README.md): the VPS migration, the
removal of the owned Mac DNS, the NetBird lifecycle/overlay guard, Kuma
credential recovery and the TV peer/alias retirement each have separate
root-private before/uncertain/after receipts. Do not delete historical
backups/keys because of new public HTTPS. In particular, the Kuma Secret data
changed during recovery; old SQL passwords and the DB lifecycle did not change.
With an uncertain marker, do not re-run apply or blindly restore an old Secret.
This documentation does not imply full DR or instant revocation of old
sessions.
